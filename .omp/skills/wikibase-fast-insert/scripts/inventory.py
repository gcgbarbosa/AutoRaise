#!/usr/bin/env python3
"""Describe the version-dependent parts of this wiki from the wiki itself.

The skill does not carry a table list or a namespace number: a Wikibase release
moves both. This script reads the live database and API and prints what the current
version actually uses, so the writer is built from facts and not from a version.

    scripts/inventory.py
    scripts/inventory.py --json

It reports:

* the server version (as information, never as a branch);
* the entity namespaces, from existing rows or from the API's canonical namespaces;
* the content-model ids;
* the term-store tables and the id columns that join them;
* whether the comment and actor are in the revision columns or in a temp table;
* whether text lives in ``slots`` or in a revision column;
* whether links use ``linktarget`` or the legacy ``pagelinks`` columns;
* the id-counter types, the change table (if present) and the ``page_props`` names that
  existing entities actually carry.

Every answer is a query or a column signature, not a version check. The capture is
still the final authority for the row order and the values.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import pymysql
except ImportError as error:  # pragma: no cover
    raise SystemExit("inventory.py needs pymysql: uv add pymysql") from error


ENV_FILE = os.environ.get("ENV_FILE") or os.environ.get("DB_ENV_FILE") or ".env"


def load_env_file(path: str) -> None:
    file = Path(path)
    if not file.is_file():
        return
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ")
        name, separator, value = line.partition("=")
        if not separator or not name.replace("_", "").isalnum():
            continue
        value = value.removesuffix("\r").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(name, value)


def connect():
    load_env_file(ENV_FILE)
    host = os.environ.get("DB_HOST", "") or "127.0.0.1"
    if host in ("localhost", "::1"):
        host = "127.0.0.1"
    settings = {
        "host": host,
        "port": int(os.environ.get("DB_PORT") or 3306),
        "user": os.environ.get("DB_USER", ""),
        "database": os.environ.get("DB_NAME", ""),
        "connect_timeout": 10,
    }
    password = os.environ.get("DB_PASSWORD") or os.environ.get("MYSQL_PWD")
    if password:
        settings["password"] = password

    return pymysql.connect(**settings)


def columns_by_table(connection, database: str) -> dict[str, list[str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, ORDINAL_POSITION",
            (database,),
        )
        tables: dict[str, list[str]] = {}
        for table, column in cursor.fetchall():
            tables.setdefault(table, []).append(column)

    return tables


def one(connection, sql: str, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def all_rows(connection, sql: str, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def table_with(tables: dict[str, list[str]], *required: str) -> str | None:
    for table, columns in tables.items():
        if all(column in columns for column in required):
            return table

    return None


def table_with_suffix(
    tables: dict[str, list[str]], suffixes: tuple[str, ...], required: str
) -> str | None:
    for table, columns in tables.items():
        if required in columns and any(
            column.endswith(suffixes) for column in columns
        ):
            return table

    return None


def text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def namespaces_from_rows(connection, page_table: str | None) -> dict[str, int]:
    if not page_table:
        return {}
    rows = all_rows(
        connection,
        f"SELECT page_content_model, page_namespace, COUNT(*) FROM `{page_table}` "
        f"WHERE page_content_model LIKE 'wikibase-%%' "
        f"GROUP BY page_content_model, page_namespace ORDER BY COUNT(*) DESC",
    )
    kinds = {"wikibase-item": "item", "wikibase-property": "property"}
    result = {}
    for model, namespace, _ in rows:
        name = kinds.get(text(model))
        if name:
            result.setdefault(name, int(namespace))

    return result


def namespaces_from_api() -> dict[str, int]:
    api_url = os.environ.get("MEDIAWIKI_API_URL", "")
    if not api_url:
        return {}
    separator = "&" if "?" in api_url else "?"
    url = f"{api_url}{separator}action=query&meta=siteinfo&siprop=namespaces&format=json"
    context = ssl._create_unverified_context()  # a dev wiki often has a self-signed certificate
    try:
        with urllib.request.urlopen(url, timeout=20, context=context) as answer:
            payload = json.load(answer)
    except Exception as error:  # noqa: BLE001 - report, do not fail the inventory
        print(f"inventory: API namespaces unavailable: {error}", file=sys.stderr)
        return {}

    result = {}
    for namespace in payload.get("query", {}).get("namespaces", {}).values():
        canonical = namespace.get("canonical") or namespace.get("*") or ""
        if canonical == "Item":
            result["item"] = int(namespace["id"])
        elif canonical == "Property":
            result["property"] = int(namespace["id"])

    return result


def term_tables(tables: dict[str, list[str]], suffix: str) -> dict:
    found = {}
    for table, columns in tables.items():
        id_columns = [
            column
            for column in columns
            if column.endswith(suffix) and column != suffix.strip("_")
        ]
        term_column = next(
            (column for column in columns if column.endswith("_term_in_lang_id")),
            None,
        )
        if id_columns and term_column:
            found[table] = {
                "entity_column": id_columns[0],
                "term_in_lang_column": term_column,
            }

    return found


def inventory(connection) -> dict:
    database = os.environ.get("DB_NAME", "")
    tables = columns_by_table(connection, database)
    version = one(connection, "SELECT VERSION()")[0]
    page_table = table_with(tables, "page_id", "page_namespace")
    model_table = table_with(tables, "model_id", "model_name")
    models = {}
    if model_table:
        models = {
            text(name): int(identifier)
            for identifier, name in all_rows(
                connection, f"SELECT model_id, model_name FROM `{model_table}`"
            )
        }

    namespaces = namespaces_from_rows(connection, page_table)
    api_namespaces = namespaces_from_api()
    namespaces.setdefault("item", api_namespaces.get("item", 0))
    namespaces.setdefault("property", api_namespaces.get("property", 0))

    revision = table_with(tables, "rev_id", "rev_page")
    revision_columns = tables.get(revision, []) if revision else []
    comment_table = table_with(tables, "comment_id", "comment_text")
    actor_table = table_with(tables, "actor_id", "actor_name")
    comment_temp = table_with_suffix(tables, ("_rev",), "revcomment_rev")
    actor_temp = table_with_suffix(tables, ("_rev",), "revactor_rev")
    slots = table_with(tables, "slot_revision_id", "slot_content_id")

    links = {}
    linktarget = table_with(tables, "lt_id")
    pagelinks = table_with(tables, "pl_from")
    if linktarget:
        links["linktarget"] = linktarget
    if pagelinks:
        links["pagelinks_columns"] = tables[pagelinks]

    slot_roles = table_with(tables, "role_id", "role_name")
    counters = []
    counter_table = table_with(tables, "id_type", "id_value")
    if counter_table:
        counters = [
            text(row[0])
            for row in all_rows(
                connection, f"SELECT DISTINCT id_type FROM `{counter_table}`"
            )
        ]

    page_props = table_with(tables, "pp_page", "pp_propname")
    props = {}
    if page_props:
        page_for_props = page_table or "page"
        for model, name, count in all_rows(
            connection,
            f"SELECT p.page_content_model, pp.pp_propname, COUNT(*) "
            f"FROM `{page_props}` pp JOIN `{page_for_props}` p "
            f"ON p.page_id = pp.pp_page "
            f"WHERE p.page_content_model LIKE 'wikibase-%%' "
            f"GROUP BY p.page_content_model, pp.pp_propname "
            f"ORDER BY p.page_content_model, pp.pp_propname",
        ):
            props.setdefault(text(model), {})[text(name)] = int(count)

    term_in_lang = table_with_suffix(tables, ("_text_in_lang_id",), "wbtl_type_id")
    if term_in_lang is None:
        term_in_lang = table_with_suffix(
            tables, ("_text_in_lang_id",), "wbtl_id"
        )
    text_in_lang = table_with_suffix(
        tables, ("_language",), "wbxl_language"
    ) or table_with_suffix(tables, ("_text_id",), "wbxl_id")
    text_store = table_with_suffix(tables, ("_text",), "wbx_id")

    return {
        "server_version": str(version),
        "database": database,
        "content_models": models,
        "namespaces": {key: value for key, value in namespaces.items() if value},
        "revision_table": revision,
        "revision_columns": revision_columns,
        "comment_table": comment_table,
        "comment_temp_table": comment_temp
        or ("revision.rev_comment_id" if "rev_comment_id" in revision_columns else None),
        "actor_table": actor_table,
        "actor_temp_table": actor_temp
        or ("revision.rev_actor" if "rev_actor" in revision_columns else None),
        "slots_table": slots
        or ("revision.rev_text_id" if "rev_text_id" in revision_columns else None),
        "term_store": {
            "item_terms": term_tables(tables, "_item_id"),
            "property_terms": term_tables(tables, "_property_id"),
            "term_in_lang": term_in_lang,
            "text_in_lang": text_in_lang,
            "text": text_store,
        },
        "links": links,
        "wb_changes": table_with(tables, "change_object_id", "change_info"),
        "id_counter_table": counter_table,
        "id_counters": counters,
        "slot_roles": slot_roles,
        "property_info": table_with(tables, "pi_property_id", "pi_type"),
        "page_props": props,
        "tables": sorted(tables),
    }


def print_text(result: dict) -> None:
    print(f"server      {result['server_version']}")
    print(f"database    {result['database']}")
    print(
        "models      "
        + ", ".join(f"{name}={identifier}" for name, identifier in result["content_models"].items())
    )
    print(
        "namespaces  "
        + ", ".join(f"{name}={value}" for name, value in result["namespaces"].items())
    )
    print(f"revision    {result['revision_table']}")
    print(f"comment     {result['comment_temp_table']} (store {result['comment_table']})")
    print(f"actor       {result['actor_temp_table']} (store {result['actor_table']})")
    print(f"text        {result['slots_table']}")
    for label, tables in (
        ("item terms", result["term_store"]["item_terms"]),
        ("property terms", result["term_store"]["property_terms"]),
    ):
        for table, columns in tables.items():
            print(
                f"{label:<11} {table} "
                f"({columns['entity_column']}, {columns['term_in_lang_column']})"
            )
    print(f"term/lang   {result['term_store']['term_in_lang']}")
    print(f"text/lang   {result['term_store']['text_in_lang']}")
    print(f"text store  {result['term_store']['text']}")
    links = result["links"]
    if "linktarget" in links:
        print(f"links       linktarget={links['linktarget']}, pagelinks")
    elif "pagelinks_columns" in links:
        print("links       pagelinks " + ", ".join(links["pagelinks_columns"]))
    else:
        print("links       none discovered")
    print(f"wb_changes  {result['wb_changes'] or 'absent'}")
    print(f"counter tbl {result['id_counter_table'] or 'none'} ({', '.join(result['id_counters']) or 'no rows'})")
    print(f"prop info   {result['property_info'] or 'absent'}")
    print(f"slot roles  {result['slot_roles'] or 'absent'}")
    for model, props in result["page_props"].items():
        print(f"props {model:<16} " + ", ".join(f"{name}={count}" for name, count in props.items()))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Describe the schema this wiki actually uses, without a version check."
    )
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()

    connection = connect()
    try:
        result = inventory(connection)
    finally:
        connection.close()

    if arguments.json:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print_text(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

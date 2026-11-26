#!/usr/bin/env python3
"""Turn a captured window into named columns, filtered and optionally JSON.

It reads the ``###`` lines that ``binlog-diff.sh`` prints and joins every ``@N`` to
the column of that ordinal position, taken from ``information_schema.COLUMNS``. The
result is ``page_namespace=<n>``, not ``@2=<n>``.

Filters, in the order they apply:

* the noise tables (``objectcache``, ``l10n_cache``, ``job``, ``querycache*``,
  ``site_stats``, ``user``) are dropped unless ``--keep-noise``;
* ``--tables`` keeps only the named tables (shell globs allowed);
* ``--entity Q123`` and ``--page-id 157`` keep the rows that belong to that save:
  the page, its revisions, text, content, slots, terms, links, log rows, watchlist
  and recent-changes row. The relation is computed by closure over the row ids, so
  the order of the events does not matter.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path

try:
    import pymysql
except ImportError as error:  # pragma: no cover - the message is the feature
    raise SystemExit(
        "capture-format.py needs pymysql: uv add pymysql"
    ) from error


DEFAULT_EXCLUDES = (
    "objectcache",
    "l10n_cache",
    "job",
    "querycache*",
    "site_stats",
    "user",
)

HEADER = re.compile(r"^### (INSERT INTO|UPDATE|DELETE FROM) `([^`]+)`\.`([^`]+)`$")
VALUE = re.compile(r"^###\s+@(\d+)=(.*)$")

TITLE_COLUMNS = frozenset(
    {"page_title", "log_title", "rc_title", "wl_title", "change_object_id"}
)

# The columns that carry an id of each kind. A row whose value is already known
# belongs to the entity; a row that belongs to the entity adds the ids it carries.
PAGE_COLUMNS = frozenset(
    {"page_id", "rev_page", "pp_page", "pl_from", "rc_cur_id", "log_page", "revactor_page"}
)
REVISION_COLUMNS = frozenset(
    {
        "rev_id",
        "revcomment_rev",
        "revactor_rev",
        "slot_revision_id",
        "rc_this_oldid",
        "rc_last_oldid",
        "change_revision_id",
    }
)
CONTENT_COLUMNS = frozenset({"content_id", "slot_content_id"})
TEXT_COLUMNS = frozenset({"old_id"})
LOG_COLUMNS = frozenset({"log_id", "ls_log_id"})
ENTITY_COLUMNS = frozenset({"wbit_item_id", "wbpt_property_id", "pi_property_id"})
TERM_COLUMNS = frozenset({"wbtl_id", "wbit_term_in_lang_id", "wbpt_term_in_lang_id"})
TEXT_LANG_COLUMNS = frozenset({"wbtl_text_in_lang_id", "wbxl_id"})
TEXT_ID_COLUMNS = frozenset({"wbxl_text_id", "wbx_id"})
LINK_COLUMNS = frozenset({"lt_id", "pl_target_id"})


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


def connection() -> pymysql.connections.Connection | None:
    load_env_file(os.environ.get("ENV_FILE") or ".env")
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
    try:
        return pymysql.connect(**settings)
    except pymysql.MySQLError as error:
        print(f"capture-format: no column names ({error})", file=sys.stderr)
        return None


def column_names(connection_, database: str) -> dict[str, list[str]]:
    if connection_ is None:
        return {}
    with connection_.cursor() as cursor:
        cursor.execute(
            "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, ORDINAL_POSITION",
            (database,),
        )
        columns: dict[str, list[str]] = {}
        for table, column in cursor.fetchall():
            columns.setdefault(table, []).append(column)

    return columns


class Schema:
    """The tables that play a role, detected from their columns, not from a version."""

    def __init__(self, columns: dict[str, list[str]]) -> None:
        self.page = _table(columns, "page_id", "page_title")
        self.revision = _table(columns, "rev_id", "rev_page")
        self.content = _table(columns, "content_id", "content_address")
        self.legacy_text = _table(columns, "old_id", "old_text")
        self.logging = _table(columns, "log_id", "log_page")
        self.slots = _table(columns, "slot_revision_id", "slot_content_id")
        self.wb_changes = _table(columns, "change_object_id", "change_info")
        self.log_search = _table(columns, "ls_log_id", "ls_field")
        self.recentchanges = _table(columns, "rc_cur_id", "rc_title")
        self.linktarget = _table(columns, "lt_id")
        self.id_counters = _table(columns, "id_type", "id_value")
        self.item_terms = _term_table(columns, "_item_id")
        self.property_terms = _term_table(columns, "_property_id")
        self.term_in_lang = _suffix_table(
            columns, ("_type_id",), "_text_in_lang_id"
        )
        self.text_in_lang = _suffix_table(columns, ("_language",), "_text_id")
        self.text_store = _table(columns, "wbx_id", "wbx_text") or self.legacy_text


def _table(columns: dict[str, list[str]], *required: str) -> str | None:
    for table, names in columns.items():
        if all(name in names for name in required):
            return table

    return None


def _term_table(columns: dict[str, list[str]], suffix: str) -> str | None:
    for table, names in columns.items():
        if any(name.endswith(suffix) for name in names) and any(
            name.endswith("_term_in_lang_id") for name in names
        ):
            return table

    return None


def _suffix_table(
    columns: dict[str, list[str]], suffixes: tuple[str, ...], required_suffix: str
) -> str | None:
    for table, names in columns.items():
        if any(name.endswith(required_suffix) for name in names) and any(
            name.endswith(suffixes) for name in names
        ):
            return table

    return None


def parse_values(raw_values: list[str], names: list[str]) -> dict:
    result = {}
    for position, raw in enumerate(raw_values, 1):
        name = names[position - 1] if position <= len(names) else f"c{position}"
        result[name] = raw

    return result


def typed(raw: str):
    if raw == "NULL":
        return None
    if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        text = raw[1:-1]
        return text.replace("\\'", "'").replace("\\\\", "\\")
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def read_events(source, columns: dict[str, list[str]]) -> list[dict]:
    events = []
    block = None
    mode = None
    where: list[str] = []
    values: list[str] = []

    def flush():
        nonlocal block, where, values
        if block is None:
            return
        names = columns.get(block["table"], [])
        if block["op"] == "UPDATE":
            block["before"] = parse_values(where, names)
            block["after"] = parse_values(values, names)
        else:
            block["values"] = parse_values(values, names)
        events.append(block)
        block = None
        where = []
        values = []

    for line in source:
        line = line.rstrip("\n")
        header = HEADER.match(line)
        if header:
            flush()
            operation = header.group(1)
            block = {
                "op": "INSERT" if operation.startswith("INSERT") else
                       "DELETE" if operation.startswith("DELETE") else "UPDATE",
                "schema": header.group(2),
                "table": header.group(3),
            }
            mode = "set"
            continue
        if block is None:
            continue
        if line == "### WHERE":
            mode = "where"
            continue
        if line == "### SET":
            mode = "set"
            continue
        match = VALUE.match(line)
        if match:
            (where if mode == "where" else values).append(match.group(2))

    flush()

    return events


def matches_table(table: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(table, pattern) for pattern in patterns)


def keep_entity(
    events: list[dict],
    entity: str | None,
    page_id: int | None,
    schema: Schema,
) -> list[dict]:
    if not entity and page_id is None:
        return events

    titles = {entity} if entity else set()
    numbers = set()
    if entity and re.fullmatch(r"[QP][0-9]+", entity):
        numbers.add(int(entity[1:]))

    pages = {page_id} if page_id is not None else set()
    revisions: set[int] = set()
    contents: set[int] = set()
    texts: set[int] = set()
    logs: set[int] = set()
    terms: set[int] = set()
    term_languages: set[int] = set()
    text_languages: set[int] = set()
    links: set[int] = set()

    def values_of(event: dict):
        if event["op"] == "UPDATE":
            yield event["before"]
            yield event["after"]
        else:
            yield event["values"]

    def matches(event: dict) -> bool:
        for values in values_of(event):
            for column, raw in values.items():
                value = typed(raw) if isinstance(raw, str) else raw
                if column in TITLE_COLUMNS and value in titles:
                    return True
                if column in PAGE_COLUMNS and value in pages:
                    return True
                if column in REVISION_COLUMNS and value in revisions:
                    return True
                if column in CONTENT_COLUMNS and value in contents:
                    return True
                if column in TEXT_COLUMNS and value in texts:
                    return True
                if column in LOG_COLUMNS and value in logs:
                    return True
                if column in ENTITY_COLUMNS and value in numbers:
                    return True
                if column in TERM_COLUMNS and value in terms:
                    return True
                if column in TEXT_LANG_COLUMNS and value in text_languages:
                    return True
                if column in TEXT_ID_COLUMNS and value in texts:
                    return True
                if column in LINK_COLUMNS and value in links:
                    return True
                if (
                    column == "content_address"
                    and str(value).startswith("tt:")
                    and int(str(value)[3:] or 0) in texts
                ):
                    return True
                if column == "ls_value" and value in revisions:
                    return True
        return False

    def discover(event: dict) -> None:
        table = event["table"]

        def get(values: dict, column: str):
            raw = values.get(column)
            return typed(raw) if isinstance(raw, str) else raw

        for values in values_of(event):
            if table == schema.page:
                pages.add(get(values, "page_id"))
                title = get(values, "page_title")
                if isinstance(title, str):
                    titles.add(title)
                    if re.fullmatch(r"[QP][0-9]+", title):
                        numbers.add(int(title[1:]))
            elif table == schema.revision:
                revisions.add(get(values, "rev_id"))
            elif table == schema.content:
                contents.add(get(values, "content_id"))
                address = get(values, "content_address")
                if isinstance(address, str) and address.startswith("tt:"):
                    texts.add(int(address[3:] or 0))
            elif table == schema.legacy_text:
                texts.add(get(values, "old_id"))
            elif table == schema.logging:
                logs.add(get(values, "log_id"))
            elif table == schema.slots:
                revisions.add(get(values, "slot_revision_id"))
                contents.add(get(values, "slot_content_id"))
            elif table == schema.item_terms:
                terms.add(get(values, "wbit_term_in_lang_id"))
            elif table == schema.property_terms:
                terms.add(get(values, "wbpt_term_in_lang_id"))
            elif table == schema.term_in_lang:
                term_languages.add(get(values, "wbtl_id"))
                text_languages.add(get(values, "wbtl_text_in_lang_id"))
            elif table == schema.text_in_lang:
                text_languages.add(get(values, "wbxl_id"))
                texts.add(get(values, "wbxl_text_id"))
            elif table == schema.text_store:
                texts.add(get(values, "wbx_id"))
            elif table == schema.linktarget:
                links.add(get(values, "lt_id"))
            elif table == schema.wb_changes:
                revisions.add(get(values, "change_revision_id"))
            elif table == schema.log_search:
                revisions.add(get(values, "ls_value"))
            elif table == schema.recentchanges:
                pages.add(get(values, "rc_cur_id"))
                revisions.add(get(values, "rc_this_oldid"))

    kept: set[int] = set()
    for index, event in enumerate(events):
        if event["table"] == schema.id_counters:
            kept.add(index)

    changed = True
    passes = 0
    while changed and passes < 20:
        changed = False
        passes += 1
        for index, event in enumerate(events):
            if index in kept:
                discover(event)
                continue
            if matches(event):
                kept.add(index)
                discover(event)
                changed = True

    return [event for index, event in enumerate(events) if index in kept]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Name the columns of a binlog capture and filter its noise."
    )
    parser.add_argument("-i", "--input", default="-")
    parser.add_argument("-o", "--output")
    parser.add_argument("-d", "--database")
    parser.add_argument("--tables")
    parser.add_argument("--entity")
    parser.add_argument("--page-id", type=int)
    parser.add_argument("--exclude")
    parser.add_argument("--keep-noise", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--list-tables",
        action="store_true",
        help="print the distinct tables of the filtered capture, one per line",
    )
    arguments = parser.parse_args()

    with ExitStack() as stack:
        source = (
            sys.stdin
            if arguments.input == "-"
            else stack.enter_context(
                open(arguments.input, encoding="utf-8", errors="replace")
            )
        )
        events = read_events(source, {})

    database = arguments.database or os.environ.get("DB_NAME", "")
    if not database:
        load_env_file(os.environ.get("ENV_FILE") or ".env")
        database = os.environ.get("DB_NAME", "")
    connection_ = connection() if database else None
    names: dict[str, list[str]] = {}
    if connection_ is not None:
        names = column_names(connection_, database)
        connection_.close()
        events = _rename_columns(events, names)
    schema = Schema(names)

    excludes = ()
    if not arguments.keep_noise:
        excludes = tuple((arguments.exclude or ",".join(DEFAULT_EXCLUDES)).split(","))
    if excludes:
        events = [event for event in events if not matches_table(event["table"], excludes)]

    if arguments.tables:
        patterns = [value.strip() for value in arguments.tables.split(",") if value.strip()]
        events = [event for event in events if matches_table(event["table"], patterns)]

    if arguments.list_tables:
        for table in sorted({event["table"] for event in events}):
            print(table)
        return 0

    events = keep_entity(events, arguments.entity, arguments.page_id, schema)
    if (
        (arguments.entity or arguments.page_id is not None)
        and events
        and all(event["table"] == schema.id_counters for event in events)
    ):
        print(
            "capture-format: the entity filter matched no page or revision; "
            "check the title or the page id",
            file=sys.stderr,
        )
        events = []

    with ExitStack() as stack:
        out = (
            sys.stdout
            if not arguments.output
            else stack.enter_context(open(arguments.output, "w", encoding="utf-8"))
        )
        if arguments.json:
            json.dump(_typed_events(events), out, indent=2, ensure_ascii=False)
            out.write("\n")
        else:
            for event in events:
                out.write(_text_event(event) + "\n")

    return 0


def _rename_columns(events: list[dict], names: dict[str, list[str]]) -> list[dict]:
    renamed = []
    for event in events:
        table_names = names.get(event["table"], [])
        if event["op"] == "UPDATE":
            event["before"] = _rekey(event["before"], table_names)
            event["after"] = _rekey(event["after"], table_names)
        else:
            event["values"] = _rekey(event["values"], table_names)
        renamed.append(event)

    return renamed


def _rekey(values: dict, names: list[str]) -> dict:
    return {
        (names[position - 1] if position <= len(names) else f"c{position}"): value
        for position, value in enumerate(values.values(), 1)
    }


def _typed_events(events: list[dict]) -> list[dict]:
    typed_events = []
    for event in events:
        if event["op"] == "UPDATE":
            typed_events.append(
                {
                    "op": "UPDATE",
                    "schema": event["schema"],
                    "table": event["table"],
                    "before": {key: typed(value) for key, value in event["before"].items()},
                    "after": {key: typed(value) for key, value in event["after"].items()},
                }
            )
        else:
            typed_events.append(
                {
                    "op": event["op"],
                    "schema": event["schema"],
                    "table": event["table"],
                    "values": {key: typed(value) for key, value in event["values"].items()},
                }
            )

    return typed_events


def _text_event(event: dict) -> str:
    if event["op"] == "UPDATE":
        before = " ".join(f"{key}={value}" for key, value in event["before"].items())
        after = " ".join(f"{key}={value}" for key, value in event["after"].items())
        return f"UPDATE {event['table']} WHERE {before} SET {after}"

    values = " ".join(f"{key}={value}" for key, value in event["values"].items())
    return f"{event['op']} {event['table']} {values}"


if __name__ == "__main__":
    raise SystemExit(main())

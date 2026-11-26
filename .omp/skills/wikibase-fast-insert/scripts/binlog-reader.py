#!/usr/bin/env python3
"""Read the server's binary log over the MySQL protocol and print its row events.

This is the default behind ``binlog-diff.sh``: it needs no local decoder binary, no
Docker and no client/server version match, only ``mysql-replication`` and the two
replication grants that the capture needs anyway.

    binlog-reader.py pos
    binlog-reader.py diff START STOP [--file NAME]

The output is the format the binary decoder prints with
``--base64-output=DECODE-ROWS -v``: one ``### INSERT INTO `db`.`table``` (or
``UPDATE`` / ``DELETE``) block per row, with the values numbered ``@1``…``@N`` in
table-column order. ``binlog-diff.sh`` keeps only those lines, so the two paths are
interchangeable.

Connection values come from ``DB_*`` (the environment, then ``./.env``); a host of
``localhost`` becomes ``127.0.0.1`` and TCP is used. The password travels in
``DB_PASSWORD`` or ``MYSQL_PWD``.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
from contextlib import nullcontext
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

try:
    import pymysql
    from pymysqlreplication import BinLogStreamReader
    from pymysqlreplication.row_event import (
        DeleteRowsEvent,
        UpdateRowsEvent,
        WriteRowsEvent,
    )
except ImportError as error:  # pragma: no cover - the message is the feature
    if getattr(error, "name", "") == "distutils":
        raise SystemExit(
            "mysql-replication<1.0 imports distutils, which Python 3.12 removed: "
            "uv add setuptools"
        ) from error
    raise SystemExit(
        "binlog-reader.py needs pymysql and mysql-replication: "
        f"uv add mysql-replication ({error})"
    ) from error


ENV_FILE = os.environ.get("ENV_FILE") or os.environ.get("DB_ENV_FILE") or ".env"


def load_env_file(path: str) -> None:
    """Read ``DB_*`` values from ``.env``; the environment wins over the file."""
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


def connection_settings() -> dict:
    load_env_file(ENV_FILE)
    host = os.environ.get("DB_HOST", "") or "127.0.0.1"
    if host in ("localhost", "::1"):
        host = "127.0.0.1"
    settings = {
        "host": host,
        "port": int(os.environ.get("DB_PORT") or 3306),
        "user": os.environ.get("DB_USER", ""),
    }
    password = os.environ.get("DB_PASSWORD") or os.environ.get("MYSQL_PWD")
    if password:
        settings["password"] = password

    return settings


def version_tuple(text: str) -> tuple[int, ...]:
    match = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(part) for part in match.groups(default="0")) if match else ()


def library_version() -> tuple[int, ...]:
    try:
        from importlib.metadata import version

        return version_tuple(version("mysql-replication"))
    except Exception:  # noqa: BLE001 - the package is the thing being inspected
        return ()


def check_compatibility(settings: dict) -> None:
    """Refuse the combination that returns no row events, with the fix in the message.

    The library prints a warning for old servers and then silently skips every row
    event. Read the server version instead of documenting a list of versions.
    """
    library = library_version()
    if not library or library < (1,):
        return

    connection = pymysql.connect(**settings, connect_timeout=10)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            server = str(cursor.fetchone()[0])
    finally:
        connection.close()

    version = version_tuple(server)
    if not version:
        return
    mariadb = "mariadb" in server.lower()
    too_old = version < ((10, 5) if mariadb else (8, 0, 14))
    if too_old:
        raise SystemExit(
            f"the installed mysql-replication {'.'.join(map(str, library))} does not "
            f"decode row events on {server}: install the pre-1.0 line and setuptools "
            "(uv add 'mysql-replication<1.0' setuptools)"
        )


def database_name(explicit: str | None) -> str:
    return explicit or os.environ.get("DB_NAME", "")


def server_position(settings: dict) -> tuple[str, int]:
    """The binlog file and position the server writes at now."""
    connection = pymysql.connect(**settings, connect_timeout=10)
    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute("SHOW MASTER STATUS")
            except pymysql.MySQLError:
                cursor.execute("SHOW BINARY LOG STATUS")
            row = cursor.fetchone()
            if row is None:
                raise SystemExit("binary logging is not active on this server")
            return str(row[0]), int(row[1])
    finally:
        connection.close()


def quote(value) -> str:
    """A value as the binary decoder prints it: a quoted string, or a bare number."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, Decimal)):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (datetime, date, time, timedelta)):
        return "'" + escape(str(value)) + "'"
    if isinstance(value, (bytes, bytearray)):
        return "'" + escape_bytes(bytes(value)) + "'"

    return "'" + escape(str(value)) + "'"


def escape(text: str) -> str:
    out = []
    for character in text:
        if character == "\\":
            out.append("\\\\")
        elif character == "'":
            out.append("\\'")
        elif character == "\n":
            out.append("\\n")
        elif character == "\r":
            out.append("\\r")
        elif character == "\t":
            out.append("\\t")
        elif character == "\0":
            out.append("\\0")
        elif ord(character) < 32:
            out.append(f"\\x{ord(character):02x}")
        else:
            out.append(character)

    return "".join(out)


def escape_bytes(raw: bytes) -> str:
    out = []
    for byte in raw:
        character = chr(byte)
        if character == "\\":
            out.append("\\\\")
        elif character == "'":
            out.append("\\'")
        elif character == "\n":
            out.append("\\n")
        elif character == "\r":
            out.append("\\r")
        elif character == "\t":
            out.append("\\t")
        elif character == "\0":
            out.append("\\0")
        elif 32 <= byte < 127:
            out.append(character)
        else:
            out.append(f"\\x{byte:02x}")

    return "".join(out)


def block(out, operation: str, schema: str, table: str, values: dict) -> None:
    out.write(f"### {operation} `{schema}`.`{table}`\n")
    out.write("### SET\n")
    for position, value in enumerate(values.values(), 1):
        out.write(f"###   @{position}={quote(value)}\n")


def update_block(out, schema: str, table: str, before: dict, after: dict) -> None:
    out.write(f"### UPDATE `{schema}`.`{table}`\n")
    out.write("### WHERE\n")
    for position, value in enumerate(before.values(), 1):
        out.write(f"###   @{position}={quote(value)}\n")
    out.write("### SET\n")
    for position, value in enumerate(after.values(), 1):
        out.write(f"###   @{position}={quote(value)}\n")


def read_window(
    settings: dict,
    schema: str,
    file: str,
    start: int,
    stop: int,
    out,
) -> None:
    stream = BinLogStreamReader(
        connection_settings=settings,
        server_id=random.randint(1, 2**31 - 1),
        log_file=file,
        log_pos=start,
        end_log_pos=stop,
        resume_stream=True,
        blocking=False,
        only_schemas=[schema] if schema else None,
        only_events=[WriteRowsEvent, UpdateRowsEvent, DeleteRowsEvent],
        # The flag changes MariaDB-specific header handling, and with some
        # server/library combinations it hides the row events. Leave it off; set
        # DB_IS_MARIADB=1 only if your server needs the MariaDB events.
        is_mariadb=os.environ.get("DB_IS_MARIADB", "0") in ("1", "true"),
    )
    try:
        for event in stream:
            if event.packet.log_pos > stop:
                break
            table = getattr(event, "table", "")
            event_schema = getattr(event, "schema", schema)
            if isinstance(event_schema, bytes):
                event_schema = event_schema.decode("utf-8", "replace")
            if isinstance(table, bytes):
                table = table.decode("utf-8", "replace")
            if schema and event_schema != schema:
                continue
            if isinstance(event, WriteRowsEvent):
                for row in event.rows:
                    block(out, "INSERT INTO", event_schema, table, row["values"])
            elif isinstance(event, UpdateRowsEvent):
                for row in event.rows:
                    update_block(
                        out,
                        event_schema,
                        table,
                        row["before_values"],
                        row["after_values"],
                    )
            elif isinstance(event, DeleteRowsEvent):
                for row in event.rows:
                    block(out, "DELETE FROM", event_schema, table, row["values"])
    finally:
        stream.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read a MariaDB/MySQL binlog window over the MySQL protocol."
    )
    parser.add_argument("command", choices=("pos", "diff"))
    parser.add_argument("start", nargs="?")
    parser.add_argument("stop", nargs="?")
    parser.add_argument("-f", "--file")
    parser.add_argument("-d", "--database")
    parser.add_argument("-o", "--output")
    arguments = parser.parse_args()

    settings = connection_settings()
    check_compatibility(settings)
    schema = database_name(arguments.database)

    if arguments.command == "pos":
        file, position = server_position(settings)
        print(f"{file} {position}")

        return 0

    if not arguments.start or not arguments.stop:
        parser.error("diff needs START and STOP")
    start, stop = int(arguments.start), int(arguments.stop)
    if stop < start:
        parser.error("STOP is before START")
    file = arguments.file
    if not file:
        file, _ = server_position(settings)

    with (
        open(arguments.output, "w", encoding="utf-8")
        if arguments.output
        else nullcontext(sys.stdout)
    ) as out:
        read_window(settings, schema, file, start, stop, out)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None

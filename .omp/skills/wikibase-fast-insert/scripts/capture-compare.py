#!/usr/bin/env python3
"""Compare two JSON captures and print only where they differ.

The captures are what ``capture.sh --json`` writes. The comparison has two parts,
the two checks of step 5:

* the operation sequence: the ordered list of ``(op, table)`` pairs. A difference
  here is a table the two paths touched in another order, or did not touch.
* the row footprint: for each ``(op, table)``, the multiset of rows. Only the
  groups that differ are printed, with the API row as ``-`` and the writer row as
  ``+``.

Exit status is 0 when the captures agree and 1 when anything differs, so this can
run in CI.
"""

from __future__ import annotations

import argparse
import difflib
import fnmatch
import json
from collections import Counter


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as file:
        events = json.load(file)
    if not isinstance(events, list):
        raise SystemExit(f"{path}: expected a JSON list of events")

    return events


def sequence(events: list[dict]) -> list[str]:
    return [f'{event["op"]} {event["table"]}' for event in events]


def canonical(event: dict, ignore_columns: set[str]) -> str:
    payload = {
        key: value
        for key, value in event.items()
        if key not in ("before", "after", "values")
    }
    for key in ("values", "before", "after"):
        if key in event:
            payload[key] = {
                column: value
                for column, value in event[key].items()
                if column not in ignore_columns
            }

    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print the (op, table) and row differences of two captures."
    )
    parser.add_argument("api")
    parser.add_argument("writer")
    parser.add_argument(
        "--ignore-columns",
        default="",
        help="comma separated columns to leave out of the row comparison",
    )
    parser.add_argument(
        "--ignore-tables",
        default="",
        help="comma separated table patterns to leave out",
    )
    arguments = parser.parse_args()

    ignore_columns = {
        value.strip()
        for value in arguments.ignore_columns.split(",")
        if value.strip()
    }
    ignored_tables = [
        value.strip()
        for value in arguments.ignore_tables.split(",")
        if value.strip()
    ]

    def kept(event: dict) -> bool:
        return not any(
            fnmatch.fnmatchcase(event["table"], pattern)
            for pattern in ignored_tables
        )

    api = [event for event in load(arguments.api) if kept(event)]
    writer = [event for event in load(arguments.writer) if kept(event)]

    differences = 0
    api_sequence = sequence(api)
    writer_sequence = sequence(writer)
    if api_sequence == writer_sequence:
        print(f"sequence: equal ({len(api_sequence)} events)")
    else:
        differences += 1
        print("sequence: differs")
        for line in difflib.unified_diff(
            api_sequence,
            writer_sequence,
            fromfile="api",
            tofile="writer",
            lineterm="",
            n=0,
        ):
            print(line)

    groups: dict[tuple[str, str], tuple[Counter, Counter]] = {}
    for side, events in (("api", api), ("writer", writer)):
        for event in events:
            key = (event["op"], event["table"])
            api_rows, writer_rows = groups.setdefault(key, (Counter(), Counter()))
            target = api_rows if side == "api" else writer_rows
            target[canonical(event, ignore_columns)] += 1

    row_differences = 0
    for (operation, table), (api_rows, writer_rows) in sorted(groups.items()):
        if api_rows == writer_rows:
            continue
        row_differences += 1
        differences += 1
        print(f"\n{operation} {table}: api {sum(api_rows.values())} row(s), "
              f"writer {sum(writer_rows.values())} row(s)")
        for row, count in (api_rows - writer_rows).items():
            for _ in range(count):
                print(f"- api:    {row}")
        for row, count in (writer_rows - api_rows).items():
            for _ in range(count):
                print(f"+ writer: {row}")

    if differences:
        print(
            f"\n{differences} difference(s): "
            f"{row_differences} of the (op, table) groups differ."
        )
        return 1

    print("rows: equal")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

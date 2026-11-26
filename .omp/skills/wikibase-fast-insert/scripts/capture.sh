#!/usr/bin/env bash
#
# capture.sh — run one operation and print only the rows it wrote.
#
#   scripts/capture.sh -- python write_entity.py
#   scripts/capture.sh --tables page,revision,text -- python write_entity.py
#   scripts/capture.sh --entity Q123 --json --output /tmp/item.json -- python write_entity.py
#
# It records the binlog position, runs the command, waits for the deferred updates
# (term store, page_props, recentchanges), records the position again, and decodes
# the window. The output names the columns (`page_namespace=…`), drops the noise
# tables, and can be filtered to one entity.
#
# The command's stdout goes to stderr, so stdout carries the capture alone: a
# `--json` capture stays valid even when the write prints the new id.

set -euo pipefail

prog=${0##*/}
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

wait_seconds=1
tables=
entity=
page_id=
exclude=
keep_noise=
json=
output=
binlog_tool=
command=()

die() { printf '%s: error: %s\n' "$prog" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $prog [options] -- COMMAND [ARGS...]

Runs COMMAND, captures the binlog window around it, names the columns, and prints
the filtered events. The command's stdout is sent to stderr.

Options:
  -w, --wait SECONDS    wait after the command for deferred updates (default: 1)
  -t, --tables LIST     keep only these tables (comma separated, globs allowed)
  -e, --entity TITLE    keep only the rows of this entity, e.g. Q123 or P45
      --page-id N       keep only the rows of this page id
      --exclude LIST    noise tables to drop (default: objectcache, l10n_cache,
                        job, querycache*, site_stats, user)
      --keep-noise      keep the default noise tables
  -j, --json            write JSON events instead of one line per row
  -o, --output FILE     write the capture to FILE (default: stdout)
  -b, --binlog-tool P   force this binary decoder (default: the Python reader when
                        mysql-replication is importable)
  -h, --help            show this help

The wait matters: MediaWiki writes the term store 30-113 ms after the response,
and the job queue and site statistics later still. One second covers the instance
this skill was measured on; raise it on a slower one.

Examples:
  $prog -- python write_item.py
  $prog --entity Q123 --json -o /tmp/api.json -- python api_write.py
  $prog --tables page,revision,text -- python write.py
EOF
}

while (($#)); do
    case $1 in
        -w|--wait)        wait_seconds=${2:?$1 requires a value}; shift 2 ;;
        -w=*|--wait=*)    wait_seconds=${1#*=};                    shift   ;;
        -t|--tables)      tables=${2:?$1 requires a value};        shift 2 ;;
        -t=*|--tables=*)  tables=${1#*=};                          shift   ;;
        -e|--entity)      entity=${2:?$1 requires a value};        shift 2 ;;
        -e=*|--entity=*)  entity=${1#*=};                          shift   ;;
        --page-id)        page_id=${2:?$1 requires a value};       shift 2 ;;
        --page-id=*)      page_id=${1#*=};                         shift   ;;
        --exclude)        exclude=${2:?$1 requires a value};       shift 2 ;;
        --exclude=*)      exclude=${1#*=};                         shift   ;;
        --keep-noise)     keep_noise=1;                            shift   ;;
        -j|--json)        json=1;                                  shift   ;;
        -o|--output)      output=${2:?$1 requires a value};        shift 2 ;;
        -o=*|--output=*)  output=${1#*=};                          shift   ;;
        -b|--binlog-tool) binlog_tool=${2:?$1 requires a value};   shift 2 ;;
        -b=*|--binlog-tool=*) binlog_tool=${1#*=};                 shift   ;;
        -h|--help)        usage; exit 0 ;;
        --)               shift; command=("$@"); break ;;
        *)                usage >&2; die "unknown argument: $1" ;;
    esac
done

((${#command[@]})) || { usage >&2; die "name the command after --"; }
[[ $wait_seconds =~ ^[0-9]+$ ]] || die "--wait must be a whole number of seconds"

python_tool=$(command -v python3 || command -v python || true)
[[ -n $python_tool ]] || die "no python3: install it (check-env.sh prints the command)"
[[ -f $script_dir/binlog-diff.sh ]] || die "binlog-diff.sh is missing beside this script"
[[ -f $script_dir/capture-format.py ]] || die "capture-format.py is missing beside this script"

position() {  # position — the binlog file and position the server writes at now
    "$script_dir/binlog-diff.sh" pos
}

before=$(position) || die "cannot read the position before the command"
read -r start_file start_position <<<"$before"
[[ -n $start_file && $start_position =~ ^[0-9]+$ ]] ||
    die "the server reported no position: $before"

printf '%s: before  %s %s\n' "$prog" "$start_file" "$start_position" >&2
printf '%s: run     %s\n' "$prog" "${command[*]}" >&2

command_status=0
"${command[@]}" >&2 || command_status=$?

sleep "$wait_seconds"

after=$(position) || die "cannot read the position after the command"
read -r stop_file stop_position <<<"$after"
[[ -n $stop_file && $stop_position =~ ^[0-9]+$ ]] ||
    die "the server reported no position: $after"

printf '%s: after   %s %s\n' "$prog" "$stop_file" "$stop_position" >&2
if [[ $stop_file != "$start_file" ]]; then
    die "the binlog rotated during the window ($start_file -> $stop_file); rerun the capture"
fi
if [[ $command_status -ne 0 ]]; then
    printf '%s: the command exited %s; capturing the window anyway\n' \
        "$prog" "$command_status" >&2
fi

raw=$(mktemp)
trap 'rm -f "$raw"' EXIT

decoder_args=()
[[ -n $binlog_tool ]] && decoder_args+=(--binlog-tool "$binlog_tool")

printf '%s: decode  %s..%s\n' "$prog" "$start_position" "$stop_position" >&2
"$script_dir/binlog-diff.sh" diff --file "$start_file" \
    ${decoder_args[@]+"${decoder_args[@]}"} \
    "$start_position" "$stop_position" >"$raw"

formatter_args=(--input "$raw")
[[ -n $tables ]]     && formatter_args+=(--tables "$tables")
[[ -n $entity ]]     && formatter_args+=(--entity "$entity")
[[ -n $page_id ]]    && formatter_args+=(--page-id "$page_id")
[[ -n $exclude ]]    && formatter_args+=(--exclude "$exclude")
[[ -n $keep_noise ]] && formatter_args+=(--keep-noise)
[[ -n $json ]]       && formatter_args+=(--json)
[[ -n $output ]]     && formatter_args+=(--output "$output")
[[ -n ${DB_NAME:-} ]] && formatter_args+=(--database "$DB_NAME")

"$python_tool" "$script_dir/capture-format.py" "${formatter_args[@]}"

events=$(grep -cE '^### (INSERT INTO|UPDATE|DELETE FROM)' "$raw" || true)
printf '%s: %s event(s) in the window\n' "$prog" "$events" >&2

exit "$command_status"

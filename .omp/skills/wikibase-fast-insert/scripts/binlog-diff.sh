#!/usr/bin/env bash
#
# binlog-diff.sh — read the server's binary log over TCP and print the row events
# recorded between two positions: the lines the decoder prefixes with `###`, and
# nothing else. That is the complete list of INSERT and UPDATE statements a real
# save wrote, including the tables no write-up mentions.
#
#   binlog-diff.sh pos              the binlog file and position in use right now
#   binlog-diff.sh diff START STOP  the events between two positions
#
# It serves the capture loop: `pos`, one operation through the API, `pos` again,
# `diff` across the two. Meant as cheap, safe context for an LLM — it reads rows
# out of the log, never out of the database.
#
# Connection values come from the DB_* variables: they are read from the environment
# and from ./.env, and passed to the client. A value that is unset or empty is left to
# the client, which then falls back to its own defaults and to ~/.my.cnf, section
# [client]. When a host is set, both the client and the decoder go over TCP: a value
# of localhost is rewritten to 127.0.0.1. A client that gets localhost opens a Unix
# socket. The password travels in MYSQL_PWD, not on a command line.

set -euo pipefail

prog=${0##*/}
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
command=
file=
start=
stop=
output=
client=
binlog_tool=

die() { printf '%s: error: %s\n' "$prog" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $prog pos [options]
       $prog diff START STOP [options]

pos prints the binlog file and the position the server writes at, one space
apart. Take one before the operation and one after it.

diff prints the row events between START and STOP, one per line, as the decoder
writes them: lines beginning with ###. Nothing else.

Options:
  -f, --file NAME       binlog file to read (default: the server's current one —
                        pass the file that pos printed before the write, if the
                        server may have rotated since)
  -d, --database NAME   only read events for this database (default: \$DB_NAME)
  -o, --output FILE     write the events to FILE (default: stdout)
  -c, --client PATH     mariadb/mysql client for the position (default: first found)
  -b, --binlog-tool P   force a binary decoder (mariadb-binlog/mysqlbinlog) to read
                        the log. Without it the Python reader beside this script is
                        used when mysql-replication is importable, and the binary is
                        the fallback: no local decoder is needed, only the two
                        replication grants
  -h, --help            show this help

Notes:
  * Connection values come from DB_HOST, DB_PORT, DB_USER, DB_PASSWORD and
    DB_NAME. They are read from the environment and from ./.env (name another file
    with \$DB_ENV_FILE); the environment wins over the file.
  * A value that is unset or empty is not passed to the client, which then falls
    back to its own defaults and to ~/.my.cnf, section [client].
  * When DB_HOST is set the client uses --protocol=TCP, and localhost becomes
    127.0.0.1. Set DB_PROTOCOL=socket to ask for the socket explicitly.
  * The password goes in MYSQL_PWD, for the client and for the decoder.
  * The decoder streams the log from the server, so the user needs replication
    rights (REPLICATION SLAVE) and no local copy of the binlog is needed.
  * START and STOP must be positions the server reported — the two pos calls
    around the operation. A position that falls inside an event (anything you
    computed yourself, such as "the current position minus 13000") makes the
    decoder read the rest of that event as a length, and it fails with a packet
    or truncation error rather than with a bad-position one.
  * STOP must not be past where the server has written yet: a read that reaches
    beyond the end of the log can come back empty. Re-read pos after the
    operation, which is what the capture loop does by construction.
  * A window can be empty: a save that only touches tables the decoder reports as
    statement events, or no save at all, prints nothing and exits 0.
EOF
}

# --- configuration ---------------------------------------------------------

# The DB_* values, read from the shell's environment and from ./.env. A runner that
# loads .env into the environment works too; the environment wins over the file.
load_env_file() {
    local file=$1 line name value
    [[ -f $file ]] || return 0

    while IFS= read -r line || [[ -n $line ]]; do
        line=${line#"${line%%[![:space:]]*}"}   # drop leading blanks
        [[ -z $line || $line == '#'* ]] && continue
        line=${line#export }
        name=${line%%=*}
        [[ $name == "$line" || ! $name =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && continue
        value=${line#*=}
        value=${value%$'\r'}
        [[ $value == \"* || $value == \'* ]] && value=${value:1:${#value}-2}
        [[ -n ${!name+x} ]] && continue         # the environment wins
        export "$name=$value"
    done <"$file"
}

load_env_file "${DB_ENV_FILE:-.env}"

# Any of these may stay unset: the client and the decoder then take over.
db_host=${DB_HOST:-}
db_port=${DB_PORT:-}
db_user=${DB_USER:-}
db_password=${DB_PASSWORD:-}
db_protocol=${DB_PROTOCOL:-}
database=${DB_NAME:-}

# A client that gets localhost opens a Unix socket. The capture must work the same on
# every machine. The decoder speaks only TCP.
[[ $db_host == localhost || $db_host == ::1 ]] && db_host=127.0.0.1
if [[ -z $db_protocol && -n $db_host ]]; then
    db_protocol=TCP
fi
if [[ -n $db_password ]]; then
    export MYSQL_PWD=$db_password
fi

# --- arguments -------------------------------------------------------------

while (($#)); do
    case $1 in
        pos|diff)          command=$1;                        shift   ;;
        -f|--file)         file=${2:?$1 requires a value};    shift 2 ;;
        -f=*|--file=*)     file=${1#*=};                      shift   ;;
        -d|--database)     database=${2:?$1 requires a value}; shift 2 ;;
        -d=*|--database=*) database=${1#*=};                   shift   ;;
        -o|--output)       output=${2:?$1 requires a value};   shift 2 ;;
        -o=*|--output=*)   output=${1#*=};                     shift   ;;
        -c|--client)       client=${2:?$1 requires a value};   shift 2 ;;
        -c=*|--client=*)   client=${1#*=};                     shift   ;;
        -b|--binlog-tool)  binlog_tool=${2:?$1 requires a value}; shift 2 ;;
        -b=*|--binlog-tool=*) binlog_tool=${1#*=};             shift   ;;
        -h|--help)         usage; exit 0 ;;
        -*)                usage >&2; die "unknown argument: $1" ;;
        *)                 case $command in
                               diff)
                                   if [[ -z $start ]]; then
                                       start=$1
                                   elif [[ -z $stop ]]; then
                                       stop=$1
                                   else
                                       die "diff takes exactly two positions, got a third: $1"
                                   fi
                                   ;;
                               *) die "unexpected argument: $1" ;;
                           esac
                           shift ;;
    esac
done

[[ -n $command ]] || { usage >&2; die "name a command: pos or diff"; }

if [[ $command == pos ]]; then
    [[ -z $file && -z $output && -z $binlog_tool ]] ||
        die "pos prints the position alone; --file, --output and --binlog-tool belong to diff"
fi

if [[ $command == diff ]]; then
    [[ -n $start && -n $stop ]] || die "diff needs START and STOP"
    [[ $start =~ ^[0-9]+$ ]] || die "START is not a position: $start"
    [[ $stop =~ ^[0-9]+$ ]] || die "STOP is not a position: $stop"
    ((stop >= start)) || die "STOP ($stop) is before START ($start)"
fi

# --- tools -----------------------------------------------------------------

find_tool() {  # find_tool <candidate>... — the first one in PATH, or nothing
    local candidate
    for candidate in "$@"; do
        if command -v "$candidate" >/dev/null 2>&1; then printf '%s' "$candidate"; return 0; fi
    done

    return 0
}

# --- SQL client, for the position ------------------------------------------

sql() {  # sql <query> — tab separated rows, no header, raw (unescaped) output
    local args=(--batch --raw --skip-column-names --connect-timeout=10 --default-character-set=utf8mb4)

    [[ -n $db_host     ]] && args+=(--host "$db_host")
    [[ -n $db_port     ]] && args+=(--port "$db_port")
    [[ -n $db_user     ]] && args+=(--user "$db_user")
    [[ -n $db_protocol ]] && args+=(--protocol "$db_protocol")

    "$client" "${args[@]}" --execute "$1"
}

server_position() {  # the binlog file and position the server writes at now
    local status name position rest error_file detail

    # Keep stderr out of the value: a client warning must never become the first
    # field of the position. The environment already carries MYSQL_PWD, so a
    # password warning must not exist at all.
    error_file=$(mktemp)
    if ! status=$(sql "SHOW MASTER STATUS" 2>"$error_file"); then
        detail=$(cat "$error_file")
        # Some servers renamed the statement; MariaDB kept both.
        if ! status=$(sql "SHOW BINARY LOG STATUS" 2>"$error_file"); then
            detail=$(cat "$error_file")
            rm -f "$error_file"
            die "cannot read the binlog position: ${detail:-the server did not answer}"
        fi
    fi
    rm -f "$error_file"

    # A client that still writes a warning to stdout must not shift the fields.
    status=$(printf '%s\n' "$status" |
        grep -v -E '^(\[Warning\]|Warning|mysql:|mariadb:)' || true)
    status=$(printf '%s\n' "$status" | sed -n '1p')
    [[ -n $status ]] || die "binary logging is not active on this server"

    IFS=$'\t' read -r name position rest <<<"$status"
    [[ -n $name && $position =~ ^[0-9]+$ ]] ||
        die "the server reported no binlog position: $status"

    printf '%s %s\n' "$name" "$position"
}

resolve_client() {  # only the position needs the SQL client
    if [[ -n $client ]]; then
        command -v "$client" >/dev/null 2>&1 || die "client not found: $client"
        return 0
    fi

    client=$(find_tool mariadb mysql)
    [[ -n $client ]] || die "neither 'mariadb' nor 'mysql' found in PATH (or pass --client)"
}

# --- read the log ----------------------------------------------------------

if [[ $command == pos ]]; then
    resolve_client
    server_position
    exit 0
fi

reader="$script_dir/binlog-reader.py"
python_tool=$(find_tool python3 python)
use_reader=
if [[ -z $binlog_tool && -f $reader && -n $python_tool ]]; then
    # A broken interpreter must not hang the capture: probe it with a timeout
    # where the host has one.
    if command -v timeout >/dev/null 2>&1; then
        timeout 10 "$python_tool" -c 'import pymysqlreplication' >/dev/null 2>&1 &&
            use_reader=1
    elif "$python_tool" -c 'import pymysqlreplication' >/dev/null 2>&1; then
        use_reader=1
    fi
fi

if [[ -n $use_reader ]]; then
    cmd=("$python_tool" "$reader" diff "$start" "$stop" --file "$file")
    [[ -n $database ]] && cmd+=(--database "$database")
elif [[ -n $binlog_tool ]]; then
    command -v "$binlog_tool" >/dev/null 2>&1 || die "binlog tool not found: $binlog_tool"
    cmd=("$binlog_tool" --read-from-remote-server --base64-output=DECODE-ROWS -v
         "--start-position=$start" "--stop-position=$stop")
    [[ -n $db_host     ]] && cmd+=(--host="$db_host")
    [[ -n $db_port     ]] && cmd+=(--port="$db_port")
    [[ -n $db_user     ]] && cmd+=(--user="$db_user")
    [[ -n $db_protocol ]] && cmd+=(--protocol="$db_protocol")
    [[ -n $database    ]] && cmd+=(--database="$database")
    cmd+=("$file")
else
    binlog_tool=$(find_tool mariadb-binlog mysqlbinlog)
    if [[ -z $binlog_tool ]]; then
        die "no binlog reader: install mysql-replication (uv add mysql-replication), or a decoder (mariadb-binlog/mysqlbinlog), or pass --binlog-tool"
    fi
    cmd=("$binlog_tool" --read-from-remote-server --base64-output=DECODE-ROWS -v
         "--start-position=$start" "--stop-position=$stop")
    [[ -n $db_host     ]] && cmd+=(--host="$db_host")
    [[ -n $db_port     ]] && cmd+=(--port="$db_port")
    [[ -n $db_user     ]] && cmd+=(--user="$db_user")
    [[ -n $db_protocol ]] && cmd+=(--protocol="$db_protocol")
    [[ -n $database    ]] && cmd+=(--database="$database")
    cmd+=("$file")
fi

if [[ -z $file ]]; then
    # The file the server writes at now: right unless it rotated during the window.
    resolve_client
    read -r file rest <<<"$(server_position)"
fi

if ! raw=$("${cmd[@]}" 2>&1); then
    # The decoder opens with session noise; keep the lines that name the failure.
    detail=$(printf '%s\n' "$raw" | while IFS= read -r line; do
        [[ $line == ERROR* || $line == WARNING* ]] && printf '%s; ' "$line"
    done)

    # A position that is not one the server reported falls inside an event, and
    # the decoder reads the rest of it as a length: it then fails as a huge or
    # truncated packet rather than as a bad position.
    hint=
    case $raw in
        *"truncated in the middle"* | *"exceeded max_allowed_packet"*)
            hint=" (use the positions pos printed: a position inside an event reads as a truncated packet)" ;;
    esac

    die "reading $file from $start to $stop failed: ${detail:-$raw}$hint"
fi

# --- print ------------------------------------------------------------------

if [[ -n $output ]]; then
    exec 3>"$output"
else
    exec 3>&1
fi

events=0
while IFS= read -r line; do
    if [[ $line == '###'* ]]; then
        printf '%s\n' "$line" >&3
        events=$((events + 1))
    fi
done <<<"$raw"

if [[ -n $output ]]; then
    printf '%s: wrote %s (%s events from %s, %s..%s)\n' \
        "$prog" "$output" "$events" "$file" "$start" "$stop" >&2
fi

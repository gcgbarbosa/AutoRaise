#!/usr/bin/env bash
#
# db-structure.sh — print the structure of a MariaDB/MySQL database as markdown:
# the tables with their CREATE statement, and no rows at all. The tables can be
# limited with --table, which takes a comma or space separated list.
#
# Meant as cheap, safe context for an LLM: it describes what is in there (tables,
# columns, types, keys, engines) without copying any data, and never reads rows.
#
# Connection values come from the DB_* variables: they are read from the environment
# and from ./.env, and passed to the client. A value that is unset or empty is left to
# the client, which then falls back to its own defaults and to ~/.my.cnf, section
# [client]. When a host is set, the client goes over TCP: a value of localhost is
# rewritten to 127.0.0.1. A client that gets localhost opens a Unix socket.
# A requested table that this version does not have is listed as absent instead of
# stopping the report. --allow-missing makes that an exit status of 0.

set -euo pipefail

prog=${0##*/}
database=
output=
client=
allow_missing=
tables_filter=()

die() { printf '%s: error: %s\n' "$prog" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $prog [options]

Prints the structure of a MariaDB/MySQL database in markdown: a table index, then
the CREATE statement of every table. No rows are read or printed.

Options:
  -d, --database NAME   database to describe (default: \$DB_NAME, else the
                        only non-system database on the server)
  -t, --table LIST      only these tables: separate names with commas or spaces
                        (-t page,revision or -t 'page revision'), and the flag may
                        also be repeated. A name this database does not have is
                        reported as absent. The report still prints the rest
      --allow-missing   exit 0 when a requested table is absent (the default exits
                        1 after printing the report, so a typo still fails)
  -o, --output FILE     write the description to FILE (default: stdout)
  -c, --client PATH     mariadb/mysql client to use (default: first found)
  -h, --help            show this help

Notes:
  * Connection values come from DB_HOST, DB_PORT, DB_USER, DB_PASSWORD and
    DB_NAME. They are read from the environment and from ./.env (name another file
    with \$DB_ENV_FILE). The environment wins over the file.
  * A value that is unset or empty is not passed to the client, which then falls
    back to its own defaults and to ~/.my.cnf, section [client].
  * When DB_HOST is set the client uses --protocol=TCP, and localhost becomes
    127.0.0.1. Set DB_PROTOCOL=socket to ask for the socket explicitly.
  * The password goes in MYSQL_PWD, never on the command line.
  * The row count in the index is information_schema's estimate, never COUNT(*),
    so no data is scanned.
EOF
}

# --- configuration ---------------------------------------------------------

# The DB_* values, read from the shell's environment and from ./.env. A runner that
# loads .env into the environment also works. The environment wins over the file.
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

# Any of these may stay unset: the client and the lookup below then take over.
db_host=${DB_HOST:-}
db_port=${DB_PORT:-}
db_user=${DB_USER:-}
db_password=${DB_PASSWORD:-}
db_protocol=${DB_PROTOCOL:-}
database=${DB_NAME:-}

# A host of localhost means the client's Unix socket. The scripts read the binlog
# and run statements over TCP, so keep the one behavior across every machine.
[[ $db_host == localhost || $db_host == ::1 ]] && db_host=127.0.0.1
if [[ -z $db_protocol && -n $db_host ]]; then
    db_protocol=TCP
fi

# --- arguments -------------------------------------------------------------

# One --table value may hold several names — "page,revision" or "page revision"
# — and the flag may also be repeated. Names are literal: no globbing, since a
# name that does not exist is an error rather than a pattern.
add_tables() {
    local list="${1//,/ }" name added=0
    set -f
    for name in $list; do
        if [[ -n $name ]]; then
            tables_filter+=("$name")
            added=$((added + 1))
        fi
    done
    set +f
    ((added > 0)) || die "--table needs at least one table name"
}

while (($#)); do
    case $1 in
        -d|--database)     database=${2:?$1 requires a value}; shift 2 ;;
        -d=*|--database=*) database=${1#*=};                    shift   ;;
        -t|--table)        add_tables "${2:?$1 requires a value}"; shift 2 ;;
        -t=*|--table=*)    add_tables "${1#*=}";                   shift   ;;
        -o|--output)       output=${2:?$1 requires a value};   shift 2 ;;
        -o=*|--output=*)   output=${1#*=};                      shift   ;;
        -c|--client)       client=${2:?$1 requires a value};    shift 2 ;;
        -c=*|--client=*)   client=${1#*=};                      shift   ;;
        --allow-missing)   allow_missing=1;                     shift   ;;
        -h|--help)         usage; exit 0 ;;
        *)                 usage >&2; die "unknown argument: $1" ;;
    esac
done

if [[ -n $client ]]; then
    command -v "$client" >/dev/null 2>&1 || die "client not found: $client"
else
    for candidate in mariadb mysql; do
        if command -v "$candidate" >/dev/null 2>&1; then client=$candidate; break; fi
    done
    [[ -n $client ]] || die "neither 'mariadb' nor 'mysql' found in PATH"
fi

# --- SQL helpers -----------------------------------------------------------

client_args=(--batch --raw --skip-column-names --connect-timeout=10 --default-character-set=utf8mb4)
[[ -n $db_host     ]] && client_args+=(--host "$db_host")
[[ -n $db_port     ]] && client_args+=(--port "$db_port")
[[ -n $db_user     ]] && client_args+=(--user "$db_user")
[[ -n $db_protocol ]] && client_args+=(--protocol "$db_protocol")
# A password on the command line is visible in the process list and makes the
# client print a warning; MYSQL_PWD keeps both out of the output the scripts parse.
if [[ -n $db_password ]]; then
    export MYSQL_PWD=$db_password
fi

sql() {  # sql <query> — tab separated rows, no header, raw (unescaped) output
    local args=("${client_args[@]}")
    [[ -n $database ]] && args+=(--database "$database")
    "$client" "${args[@]}" --execute "$1"
}

qi() { printf '`%s`' "${1//\`/\`\`}" ; }   # backtick quote an identifier
sq() { printf "'%s'" "${1//\'/\'\'}"  ; }   # single quote a SQL string literal

# --- resolve database ------------------------------------------------------

if [[ -z $database ]]; then
    if ! candidates_raw=$(sql "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA
                                WHERE SCHEMA_NAME NOT IN ('information_schema','mysql','performance_schema','sys')
                                ORDER BY SCHEMA_NAME" 2>&1); then
        die "cannot list databases: $candidates_raw"
    fi
    candidates=()
    while IFS= read -r name; do
        [[ -n $name ]] && candidates+=("$name")
    done <<<"$candidates_raw"
    ((${#candidates[@]} == 1)) ||
        die "no --database given and the server holds ${#candidates[@]} user databases (${candidates[*]:-none}); pick one with --database"
    database=${candidates[0]}
    printf '%s: no --database given, using the only user database: %s\n' "$prog" "$database" >&2
fi

if ! err=$(sql "USE $(qi "$database")" 2>&1); then
    die "cannot use database '$database': $err"
fi

# --- collect structure -----------------------------------------------------

# table, type, engine, estimated rows, column count — metadata only, no data read
tables=$(sql "SELECT t.TABLE_NAME, t.TABLE_TYPE, COALESCE(t.ENGINE, '-'),
                     COALESCE(t.TABLE_ROWS, 0),
                     (SELECT COUNT(*) FROM information_schema.COLUMNS c
                       WHERE c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME)
                FROM information_schema.TABLES t
               WHERE t.TABLE_SCHEMA = $(sq "$database")
               ORDER BY t.TABLE_NAME")
[[ -n $tables ]] || die "database '$database' has no tables"

# A requested name that this version does not have is not a reason to print
# nothing: a table list carried over from another Wikibase release will name a few
# that this one dropped. Collect them, print the rest, and fail only in the status.
missing=()
if ((${#tables_filter[@]})); then
    for name in ${tables_filter[@]+"${tables_filter[@]}"}; do
        exists=''
        while IFS=$'\t' read -r candidate _; do
            [[ $candidate == "$name" ]] && exists=1 && break
        done <<<"$tables"
        [[ -n $exists ]] || missing+=("$name")
    done
fi

# --table limits the report; the database's own order is kept either way.
selected=
selected_names=
missing_names=
missing_plain=
for name in ${missing[@]+"${missing[@]}"}; do
    missing_names+="${missing_names:+, }\`$name\`"
    missing_plain+="${missing_plain:+, }$name"
done
all_count=0
table_count=0
while IFS=$'\t' read -r table type engine est_rows columns; do
    [[ -n $table ]] || continue
    all_count=$((all_count + 1))

    if ((${#tables_filter[@]})); then
        wanted=''
        for name in ${tables_filter[@]+"${tables_filter[@]}"}; do
            [[ $table == "$name" ]] && wanted=1 && break
        done
        [[ -n $wanted ]] || continue
    fi

    table_count=$((table_count + 1))
    selected_names+="${selected_names:+, }$table"
    selected+="$table"$'\t'"$type"$'\t'"$engine"$'\t'"$est_rows"$'\t'"$columns"$'\n'
done <<<"$tables"

charset=$(sql "SELECT CONCAT(DEFAULT_CHARACTER_SET_NAME, ' / ', DEFAULT_COLLATION_NAME)
                 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = $(sq "$database")")

# --- print ------------------------------------------------------------------

if [[ -n $output ]]; then
    exec 3>"$output"
else
    exec 3>&1
fi
emit() { printf '%s\n' "$@" >&3; }

emit "# MariaDB database structure: \`$database\`" ""
emit "- Server: $(sql 'SELECT VERSION()')"
emit "- Generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
emit "- Database: \`$database\`"
emit "- Default character set / collation: $charset"
if ((${#tables_filter[@]})); then
    emit "- Tables: $table_count of $all_count (selected: $selected_names)"
else
    emit "- Tables: $table_count"
fi
if ((${#missing[@]})); then
    emit "- Absent: $missing_names"
fi
emit "- Row counts are information_schema estimates; no rows are read." ""
emit "## Table index" ""
emit "| # | Table | Type | Engine | Est. rows | Columns |"
emit "| --- | --- | --- | --- | --- | --- |"

n=0
while IFS=$'\t' read -r table type engine est_rows columns; do
    [[ -n $table ]] || continue
    n=$((n + 1))
    if [[ $type == 'VIEW' ]]; then est_rows='-'; fi
    emit "| $n | \`${table//|/\\|}\` | $type | $engine | $est_rows | $columns |"
done <<<"$selected"

emit "" "## Table structures" ""

n=0
while IFS=$'\t' read -r table type engine est_rows columns; do
    [[ -n $table ]] || continue
    n=$((n + 1))

    emit "<!-- table: $table -->" ""
    emit "### $n. \`$table\`" ""
    emit "\`$type\` · engine \`$engine\` · $columns columns" ""
    emit '```sql'
    # Field 2 is the DDL for tables and for views alike; views add charset and
    # collation columns after it, which `cut -f2-` appends to the statement.
    sql "SHOW CREATE TABLE $(qi "$table")" | cut -f2 >&3
    emit '```' ""
done <<<"$selected"

if [[ -n $output ]]; then
    printf '%s: wrote %s (%s tables)\n' "$prog" "$output" "$table_count" >&2
fi

if ((${#missing[@]})); then
    printf '%s: absent from database %s: %s\n' "$prog" "$database" "$missing_plain" >&2
    if [[ -z $allow_missing ]]; then
        printf '%s: rerun with --allow-missing when the list spans versions\n' "$prog" >&2
        exit 1
    fi
fi

#!/usr/bin/env bash
#
# check-env.sh — say whether this machine can run the method at all: the values the
# API write and the database connection read, the API that serves the write, the
# database that receives it, and the tools the capture needs.
#
#   check-env.sh            every check, in the order the method needs them
#   check-env.sh --quiet    only the failures, and the exit status
#
# Run it before step 1. A missing value, a wrong password, or a database account
# without the replication right all fail the capture halfway, and the error then
# looks like a bug in the writer you have not written yet.
#
# It reads MEDIAWIKI_*, WIKIBASE_* and DB_* from the environment and from ./.env
# (name another file with $ENV_FILE), and it never prints a secret: a password is
# reported as set or empty. A database host of localhost is rewritten to 127.0.0.1
# and the client is pinned to TCP, so a connection never falls back to a Unix socket
# by accident. The password travels in MYSQL_PWD, never on a command line.
#
# A missing tool is reported with the command that installs it, and the database
# account is checked for the four privileges the two write paths need: SELECT,
# INSERT, REPLICATION SLAVE and REPLICATION CLIENT.
#
# What the values mean:
#   MEDIAWIKI_API_URL   the api.php of the wiki: the write, and the read-back
#   WIKIBASE_USERNAME   the account that writes: it needs the page-edit right
#   WIKIBASE_PASSWORD   that account's password, or its bot password
#   DB_HOST             the database server, reachable from here
#   DB_PORT             its port, usually 3306
#   DB_USER             an account with SELECT, INSERT and REPLICATION SLAVE:
#                       the capture reads the binary log over the wire
#   DB_PASSWORD         that account's password
#   DB_NAME             the wiki's database, usually my_wiki

set -euo pipefail

prog=${0##*/}
quiet=

die() { printf '%s: error: %s\n' "$prog" "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $prog [--quiet]

One line per check, in the order the method needs them:

  .env            the file the values come from, if there is one
  the eight values  each one present, with a secret reported as set
  tools           the SQL client, the binlog decoder, curl and python3; a
                  missing one names the command that installs it
  api             the wiki answers, with the versions that serve it
  login           the account the write needs can log in
  database        the database answers, with its version, the two server
                  variables a fast writer depends on, the binary log position
                  the capture reads from, and the grants of the account

Options:
  --quiet         print the failures alone

Every failure is printed, so one run names everything to fix. The exit status is 0
when all of them passed, 1 when one failed.
EOF
}

while (($#)); do
    case $1 in
        -q|--quiet) quiet=1; shift ;;
        -h|--help)  usage; exit 0 ;;
        *)          usage >&2; die "unknown argument: $1" ;;
    esac
done

# --- reporting --------------------------------------------------------------

failures=0
rows=()

report() {  # report <ok|FAIL> <name> [detail]
    local status=$1 name=$2 detail=${3:-}

    if [[ $status == FAIL ]]; then
        failures=$((failures + 1))
    fi
    rows+=("$status|$name|$detail")
}

flush() {
    local row status name detail
    for row in ${rows[@]+"${rows[@]}"}; do
        IFS='|' read -r status name detail <<<"$row"
        if [[ $status != FAIL && -n $quiet ]]; then
            continue
        fi
        if [[ -z $detail ]]; then
            printf '%-5s %s\n' "$status" "$name"
        else
            printf '%-5s %-28s %s\n' "$status" "$name" "$detail"
        fi
    done
}

find_tool() {  # find_tool <candidate>... — the first one in PATH, or nothing
    local candidate
    for candidate in "$@"; do
        if command -v "$candidate" >/dev/null 2>&1; then printf '%s' "$candidate"; return 0; fi
    done

    return 0
}

# --- configuration ---------------------------------------------------------

# The DB_* values: the environment wins over ./.env, and a host of localhost is
# rewritten so the client cannot choose the socket over TCP.
normalise_db_host() {
    [[ $db_host == localhost || $db_host == ::1 ]] && db_host=127.0.0.1
    db_protocol=${DB_PROTOCOL:-}
    if [[ -z $db_protocol && -n $db_host ]]; then
        db_protocol=TCP
    fi
    if [[ -n $db_password ]]; then
        export MYSQL_PWD=$db_password
    fi
}

# The DB_* values, read from the shell's environment and from ./.env. A runner that loads
# .env into its environment works too; the environment wins over the file.
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

env_file=${ENV_FILE:-.env}
if [[ -f $env_file ]]; then
    report ok ".env" "$(cd "$(dirname "$env_file")" && pwd)/$(basename "$env_file")"
else
    report ok ".env" "absent: the environment and each tool's own defaults only"
fi
load_env_file "$env_file"

api_url=${MEDIAWIKI_API_URL:-}
wiki_user=${WIKIBASE_USERNAME:-}
wiki_password=${WIKIBASE_PASSWORD:-}
db_host=${DB_HOST:-}
db_port=${DB_PORT:-}
db_user=${DB_USER:-}
db_password=${DB_PASSWORD:-}
db_protocol=${DB_PROTOCOL:-}
database=${DB_NAME:-}

normalise_db_host

# --- the eight values ------------------------------------------------------

required() {  # required <name> — report the value, or its absence
    local name=$1 value=${!1:-}

    if [[ -z $value ]]; then
        report FAIL "$name" "empty or unset: the method cannot run without it"
    else
        report ok "$name" "$value"
    fi
}

secret() {  # secret <name> — report a password by its presence, never by its value
    local name=$1 value=${!1:-}

    if [[ -z $value ]]; then
        report FAIL "$name" "empty or unset: the method cannot run without it"
    else
        report ok "$name" "set (${#value} characters)"
    fi
}

required MEDIAWIKI_API_URL
required WIKIBASE_USERNAME
secret WIKIBASE_PASSWORD
required DB_HOST
required DB_PORT
required DB_USER
secret DB_PASSWORD
required DB_NAME

if ((failures)); then
    flush
    printf '\n%s: %s value(s) missing. Fill .env (carry it from .env.example) and run again.\n' \
        "$prog" "$failures" >&2
    exit 1
fi

# --- tools -----------------------------------------------------------------

install_hint() {  # install_hint <sql|binlog|curl|python> — the command that provides it
    local kind=$1 platform
    platform=$(/usr/bin/uname -s 2>/dev/null || uname -s 2>/dev/null || printf '%s' "${OSTYPE:-unknown}")

    case $platform in
        Darwin)
            case $kind in
                sql)        printf 'brew install mariadb, then add "$(brew --prefix mariadb)/bin" to PATH' ;;
                binlog)     printf 'uv add mysql-replication (some servers need <1.0 + setuptools), or brew install mariadb and add its bin to PATH' ;;
                curl)       printf 'brew install curl' ;;
                python)     printf 'brew install python@3.12' ;;
            esac
            ;;
        Linux)
            if [[ -x /usr/bin/apt-get || -x /bin/apt-get ]]; then
                case $kind in
                    sql)        printf 'sudo apt-get install mariadb-client' ;;
                    binlog)     printf 'uv add mysql-replication (some servers need <1.0 + setuptools), or sudo apt-get install mariadb-client' ;;
                    curl)       printf 'sudo apt-get install curl' ;;
                    python)     printf 'sudo apt-get install python3' ;;
                esac
            elif [[ -x /usr/bin/dnf || -x /bin/dnf ]]; then
                case $kind in
                    sql)        printf 'sudo dnf install mariadb' ;;
                    binlog)     printf 'uv add mysql-replication (some servers need <1.0 + setuptools), or sudo dnf install mariadb' ;;
                    curl)       printf 'sudo dnf install curl' ;;
                    python)     printf 'sudo dnf install python3' ;;
                esac
            elif [[ -x /usr/bin/yum || -x /bin/yum ]]; then
                case $kind in
                    sql)        printf 'sudo yum install mariadb' ;;
                    binlog)     printf 'uv add mysql-replication (some servers need <1.0 + setuptools), or sudo yum install mariadb' ;;
                    curl)       printf 'sudo yum install curl' ;;
                    python)     printf 'sudo yum install python3' ;;
                esac
            elif [[ -x /sbin/apk || -x /usr/bin/apk ]]; then
                case $kind in
                    sql)        printf 'sudo apk add mariadb-client' ;;
                    binlog)     printf 'uv add mysql-replication (some servers need <1.0 + setuptools), or sudo apk add mariadb-client' ;;
                    curl)       printf 'sudo apk add curl' ;;
                    python)     printf 'sudo apk add python3' ;;
                esac
            else
                printf 'install a MariaDB client (mariadb, mariadb-binlog), curl and python3 with your package manager'
            fi
            ;;
        *)
            printf 'install a MariaDB/MySQL client, curl and python3 with your package manager'
            ;;
    esac
}

client=$(find_tool mariadb mysql)
curl_tool=$(find_tool curl)
python_tool=$(find_tool python3 python)
decoder=$(find_tool mariadb-binlog mysqlbinlog)
python_decoder=
if [[ -n $python_tool ]]; then
    # Do not let a broken interpreter hang the check: probe with a timeout when
    # the host has one.
    if command -v timeout >/dev/null 2>&1; then
        timeout 10 "$python_tool" -c 'import pymysqlreplication' >/dev/null 2>&1 &&
            python_decoder=1
    elif "$python_tool" -c 'import pymysqlreplication' >/dev/null 2>&1; then
        python_decoder=1
    fi
fi

if [[ -n $client ]]; then
    report ok "tools: sql client" "$client"
else
    report FAIL "tools: sql client" "none of: mariadb, mysql — install: $(install_hint sql)"
fi

if [[ -n $decoder ]]; then
    report ok "tools: binlog decoder" "$decoder"
elif [[ -n $python_decoder ]]; then
    report ok "tools: binlog decoder" "python: pymysqlreplication"
else
    report FAIL "tools: binlog decoder" "no pymysqlreplication and none of: mariadb-binlog, mysqlbinlog — install: $(install_hint binlog)"
fi

if [[ -n $curl_tool ]]; then
    report ok "tools: curl" "$curl_tool"
else
    report FAIL "tools: curl" "none of: curl — install: $(install_hint curl)"
fi

if [[ -n $python_tool ]]; then
    report ok "tools: python3" "$python_tool"
else
    report FAIL "tools: python3" "none of: python3, python — install: $(install_hint python)"
fi

if ((failures)); then
    flush
    printf '\n%s: install the missing tool(s) and run again\n' "$prog" >&2
    exit 1
fi

# --- api and login ---------------------------------------------------------

separator='?'
[[ $api_url == *\?* ]] && separator='&'

api_answer=$("$curl_tool" -sk --max-time 20 \
    "$api_url${separator}action=query&meta=siteinfo&siprop=general%7Cextensions&format=json" \
    2>&1) || true

if ! versions=$("$python_tool" -c '
import json, sys

try:
    answer = json.load(sys.stdin)
except Exception as error:
    raise SystemExit("the API did not answer with JSON: %s" % error)

general = answer.get("query", {}).get("general")
if general is None:
    raise SystemExit("the API answered without siteinfo: %s" % str(answer)[:200])

# The method writes the rows of a Wikibase save, so a wiki without the Wikibase
# extension is not a wiki this can run against.
wikibase = []
for extension in answer.get("query", {}).get("extensions", []):
    if extension.get("type") != "wikibase":
        continue
    version = extension.get("version")
    wikibase.append("%s %s" % (extension.get("name"), version) if version
                    else extension.get("name"))

if not wikibase:
    raise SystemExit("no extension of type 'wikibase' is loaded: nothing writes entities here")

print("%s; Wikibase: %s" % (general.get("generator", "?"), ", ".join(wikibase)))
' <<<"$api_answer" 2>&1); then
    report FAIL "api" "$versions"
else
    report ok "api" "$versions"
fi

cookies=$(mktemp)
trap 'rm -f "$cookies"' EXIT

token_answer=$("$curl_tool" -sk --max-time 20 -c "$cookies" \
    "$api_url${separator}action=query&meta=tokens&type=login&format=json" 2>&1) || true
login_token=$("$python_tool" -c '
import json, sys

try:
    print(json.load(sys.stdin)["query"]["tokens"]["logintoken"], end="")
except Exception as error:
    raise SystemExit("no login token: %s" % error)
' <<<"$token_answer" 2>&1) || login_token=

if [[ -z $login_token ]]; then
    report FAIL "login" "cannot read a login token: $token_answer"
else
    login_answer=$("$curl_tool" -sk --max-time 20 -b "$cookies" -c "$cookies" -X POST \
        --data-urlencode action=clientlogin \
        --data-urlencode "username=$wiki_user" \
        --data-urlencode "password=$wiki_password" \
        --data-urlencode "loginreturnurl=$api_url" \
        --data-urlencode "logintoken=$login_token" \
        --data-urlencode format=json "$api_url" 2>&1) || true

    if ! login_line=$("$python_tool" -c '
import json, sys

try:
    answer = json.load(sys.stdin).get("clientlogin", {})
except Exception as error:
    raise SystemExit("the login did not answer with JSON: %s" % error)

status = answer.get("status", "?")
if status == "PASS":
    print("ok as %s" % answer.get("username", "?"), end="")
else:
    reason = answer.get("message") or answer.get("messagecode") or str(answer)[:200]
    raise SystemExit("status %s: %s" % (status, reason))
' <<<"$login_answer" 2>&1); then
        report FAIL "login" "$login_line (WIKIBASE_USERNAME and WIKIBASE_PASSWORD)"
    else
        report ok "login" "$login_line"
    fi
fi

# --- database --------------------------------------------------------------

sql() {  # sql <query> — tab separated rows, no header, raw (unescaped) output
    local args=(--batch --raw --skip-column-names --connect-timeout=10
                --default-character-set=utf8mb4
                --host "$db_host" --port "$db_port" --user "$db_user")

    [[ -n $db_protocol ]] && args+=(--protocol "$db_protocol")
    "$client" "${args[@]}" --execute "$1"
}

if ! db_versions=$(sql "SELECT VERSION(), @@binlog_format, @@auto_increment_increment" 2>&1); then
    flush
    report FAIL "database" "cannot connect to $db_host:$db_port as $db_user: $db_versions"
    flush
    printf '\n%s: fix the DB_* values and run again\n' "$prog" >&2
    exit 1
fi
IFS=$'\t' read -r db_version binlog_format increment <<<"$db_versions"

held=$(sql "SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = '$database'" 2>&1) || held=0
if [[ $held != 1 ]]; then
    report FAIL "database" "no database named '$database' on $db_host"
else
    report ok "database" "$database, $db_version (binlog_format $binlog_format, auto_increment_increment $increment)"
fi

if [[ $binlog_format != ROW ]]; then
    report FAIL "binlog" "binlog_format is $binlog_format: the capture needs ROW, or the decoder prints statement text instead of rows"
fi

if [[ $increment != 1 ]]; then
    report FAIL "increment" "auto_increment_increment is $increment: a writer that reads back the ids of a multi-row INSERT must insert one row at a time"
fi

if ! position=$(sql "SHOW MASTER STATUS" 2>&1); then
    position=$(sql "SHOW BINARY LOG STATUS" 2>&1) || position=
fi
if [[ -z $position ]]; then
    report FAIL "binlog position" "the server reports none: binary logging is off, or $db_user lacks REPLICATION SLAVE"
else
    report ok "binlog position" "capture from here, in step 1"
fi

# --- grants -----------------------------------------------------------------

# The writer needs SELECT and INSERT on the wiki's database; the capture needs both
# replication rights, which are global. A grant is matched on the database it names,
# so a privilege on another database does not count. ALL PRIVILEGES on *.* covers
# the two global rights; ALL PRIVILEGES on the wiki's database covers the two local
# ones, and not the global pair.
if ! grants=$(sql "SHOW GRANTS FOR CURRENT_USER()" 2>&1); then
    report FAIL "grants" "cannot read SHOW GRANTS FOR CURRENT_USER(): $grants"
else
    select_held=0
    insert_held=0
    slave_held=0
    client_held=0
    while IFS= read -r grant; do
        [[ -n $grant ]] || continue
        upper=$(printf '%s' "$grant" | tr '[:lower:]' '[:upper:]')
        # SHOW GRANTS escapes _ and % in a database name; drop the escapes for
        # the scope match, or `my\_wiki` never equals `my_wiki`.
        scoped=${grant//\\/}
        in_scope=0
        if [[ $scoped == *"ON \`$database\`."* || $scoped == *"ON $database."* ]]; then
            in_scope=1
        elif [[ $upper == *"ON *.*"* ]]; then
            in_scope=1
        fi

        if ((in_scope)); then
            if [[ $upper == *"ALL PRIVILEGES"* || $upper =~ (^|[ ,])SELECT([ ,]|$) ]]; then
                select_held=1
            fi
            if [[ $upper == *"ALL PRIVILEGES"* || $upper =~ (^|[ ,])INSERT([ ,]|$) ]]; then
                insert_held=1
            fi
        fi

        if [[ $upper == *"ON *.*"* && $upper == *"ALL PRIVILEGES"* ]]; then
            slave_held=1
            client_held=1
        fi
        [[ $upper == *"REPLICATION SLAVE"* ]] && slave_held=1
        [[ $upper == *"REPLICATION CLIENT"* ]] && client_held=1
    done <<<"$grants"

    if ((select_held)); then
        report ok "grant: SELECT" "held"
    else
        report FAIL "grant: SELECT" "missing: GRANT SELECT ON \`$database\`.* TO '$db_user'@'%'; (as an admin)"
    fi
    if ((insert_held)); then
        report ok "grant: INSERT" "held"
    else
        report FAIL "grant: INSERT" "missing: GRANT INSERT ON \`$database\`.* TO '$db_user'@'%'; (as an admin)"
    fi
    if ((slave_held)); then
        report ok "grant: REPLICATION SLAVE" "held"
    else
        report FAIL "grant: REPLICATION SLAVE" "missing: GRANT REPLICATION SLAVE ON *.* TO '$db_user'@'%'; (as an admin)"
    fi
    if ((client_held)); then
        report ok "grant: REPLICATION CLIENT" "held"
    else
        report FAIL "grant: REPLICATION CLIENT" "missing: GRANT REPLICATION CLIENT ON *.* TO '$db_user'@'%'; (as an admin)"
    fi
fi

# --- summary ---------------------------------------------------------------

flush
if ((failures)); then
    printf '\n%s: %s check(s) failed. The capture and the write both fail without them.\n' \
        "$prog" "$failures" >&2
    exit 1
fi

printf '\n%s: every check passed. Capture an API save next: step 1 of the method.\n' "$prog"

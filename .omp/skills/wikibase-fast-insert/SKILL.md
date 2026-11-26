---
name: wikibase-fast-insert
description: >
  Use this skill when a user asks for faster Wikibase or WikibaseIntegrator
  inserts. It replaces one HTTP request for each entity with direct SQL rows.
  It covers terms, claims, qualifiers, references, and the links that a claim
  adds. It also shows how to derive the method for a new wiki.
---

# Fast Wikibase inserts

`wbeditentity` sends each write through PHP, hooks, the job queue, and one HTTP
round trip. When you write the rows yourself, one entity creation becomes one SQL
transaction. The SQL is not the hard part. MediaWiki stores values that you cannot
guess. For example, `content_size` is the length of the PHP serialization, not the
length of the JSON. `rev_sha1` is base-36. `comment_hash` is a signed crc32. A
partly correct row set corrupts the wiki without an error.

The method has three steps:

1. Capture one real save.
2. Reproduce its rows.
3. Prove with the binlog that the rows match.

Never write a MediaWiki row from documentation or memory. Never use a final-row
`SELECT` as proof. A `SELECT` cannot show what it missed. Accept the cost of a
capture.

The API is the specification. The tables move. A Wikibase release can add a table,
drop a table, or move a value. No table list, namespace number, or row count in this
file is a contract. Each one is an example. Use `scripts/inventory.py` to find the
schema of your wiki. Then use the capture to decide what to write.

The SQL write must match the API write. For one entity, both saves must produce the
same rows and the same values. Do not omit a table because its values are hard to
find. Do not approximate a value. A missing row stays in the wiki, and nothing
reports it. If a value comes from the request, write the value that MediaWiki
writes with no request. Name the difference in the code. Step 5 proves this
requirement.

An item and a property use different tables. The namespace, content model, id
counter, summary, term table, and JSON differ. Capture both types. Let one writer
serve both. `references/worked-example.md` has one capture of each type and one
capture with claims.

## 0. Start in an empty repository

The method needs three things where you work: Python with a few packages, an `.env` with
the connection values, and this skill's scripts. Nothing else.

```toml
# mise.toml — the interpreter, the virtualenv, and .env exported into the shell
[tools]
python = "3.12"

[env]
_.python.venv = { path = ".venv", create = true }
_.file = ".env"
PYTHONPATH = "src"

[tasks]
"lint" = "uv run ruff check src test"
"test:api" = "uv run pytest test/api"
"test:db" = "uv run pytest test/sql"
```

```toml
# pyproject.toml — the writers, and the two clients the tests read rows with
[project]
name = "fast-wikibase"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "asyncmy>=0.2.15",             # the async driver a batched writer uses
    "loguru>=0.7.3",
    "mysql-replication>=1.0.9",    # the Python binlog reader; see "The binlog decoder"
    "pydantic-settings>=2.15.0",
    "pymysql>=1.2.3",              # the sync driver a test reads rows with
    "wikibaseintegrator>=0.12.15",
]

[dependency-groups]
dev = ["pytest>=8.4.2", "ruff>=0.16.4"]

[tool.pytest.ini_options]
pythonpath = ["src", "test"]
markers = ["integration: needs a running Wikibase instance and writes to it"]
```

```bash
mkdir -p src/fastwbi test/api test/sql scripts
cp <skill>/scripts/* scripts/           # the scripts
cp <skill>/.env.example .env            # then fill it in
uv sync
scripts/check-env.sh                    # never skip this: it names every value that is wrong
scripts/inventory.py                    # what this version calls the namespaces and tables
```

**Run `scripts/check-env.sh` before the first write.** It prints one line for each
check, in this order:

- The eight values
- The four tools
- The API and its versions
- The login
- The database and its version
- The binary log position
- The grants of the database account

The grants are `SELECT`, `INSERT`, `REPLICATION SLAVE`, and `REPLICATION CLIENT`.
The script prints all failures in one run. It names the install command for a missing
tool. The exit status is 1 when one check fails.

A missing value or a wrong password stops the capture halfway. The error then looks
like a bug in a writer that you have not written yet.

The eight values:

| Variable            | Read by                      | What it must be                                                                 |
| ------------------- | ---------------------------- | ------------------------------------------------------------------------------- |
| `MEDIAWIKI_API_URL` | the API write, the read-back | the `api.php` of the wiki, ready to answer `action=query`                       |
| `WIKIBASE_USERNAME` | the API write                | the account that writes. It needs the page-edit right.                          |
| `WIKIBASE_PASSWORD` | the API write                | the password of that account. A bot password works with its account.            |
| `DB_HOST`           | the scripts, writer, tests   | the database server, reachable from where you run                               |
| `DB_PORT`           | the scripts, writer, tests   | its port, usually 3306                                                          |
| `DB_USER`           | the scripts, writer, tests   | `SELECT`, `INSERT`, `REPLICATION SLAVE`, and `REPLICATION CLIENT`               |
| `DB_PASSWORD`       | the scripts, writer, tests   | the password of that account                                                    |
| `DB_NAME`           | the scripts, writer, tests   | the database of the wiki, usually `my_wiki`                                     |

Never print a password. The script shows only "set" and the length. The scripts read
the environment first and `./.env` second. A shell that mise exported works. A plain
`bash` next to the file also works. Fill `DB_HOST` even for the read-only scripts,
because the writer connects with it.

When `DB_HOST` is set, the scripts use TCP and rewrite `localhost` to `127.0.0.1`.
A client that gets `localhost` opens a Unix socket. That fails when only the port is
published. The password goes in `MYSQL_PWD`, not in the command line.

The scripts:

- `scripts/check-env.sh` performs the checks above. Run it first. Run it again after
  you change `.env`.
- `scripts/inventory.py` reads the schema facts from the live database and API. It
  reports namespaces, model ids, term tables, comment/actor/text/link storage, the
  change table, the counter table, and the `page_props` names in use. It takes no
  version parameter. It asks the wiki.
- `scripts/db-structure.sh` prints the DDL of the tables that you name as markdown. It
  reads no rows. A missing table is listed as absent and the rest still prints.
  `--allow-missing` makes that exit 0. Step 2.
- `scripts/binlog-diff.sh` prints the row events of one binlog window. That window is
  the capture of a real save. Steps 1 and 5.
- `scripts/binlog-reader.py` is the decoder that `binlog-diff.sh` uses by default. It
  uses the replication protocol. It needs no local binary.
- `scripts/capture.sh` runs one command and captures the window around it. It records
  the position, runs the command, waits, records the position, and filters the rows.
  Step 1.
- `scripts/capture-format.py` names the columns of a capture. It also applies the
  noise, table, and entity filters. `capture.sh` runs it.
- `scripts/capture-compare.py` prints the `(op, table)` pairs and rows that differ
  between two JSON captures. Step 5.

The scripts are safe on a live wiki. `check-env.sh` and `db-structure.sh` read no
rows. The decoder reads the log. `capture-format.py` reads only
`information_schema` for column names. Each script prints a usage note with `--help`.

### The binlog decoder

`scripts/binlog-diff.sh` uses `scripts/binlog-reader.py` by default. The reader uses
the MySQL replication protocol. It needs `mysql-replication`, `REPLICATION SLAVE`, and
`REPLICATION CLIENT`. It needs no local binary, no Docker, and no version match. It
prints the same `###` lines as the binary decoder.

The package must match the server. The reader reads `SELECT VERSION()`. If the pair
cannot decode rows, the reader stops and gives the install command. No version is
passed to a script. The reader leaves `is_mariadb` off by default. That flag can hide
row events. Set `DB_IS_MARIADB=1` only if your server needs MariaDB events.
`check-env.sh` reports the decoder that it found.

To use a binary decoder, install it and pass `--binlog-tool`:

| Host              | Install                          | Notes                                                                 |
| ----------------- | -------------------------------- | --------------------------------------------------------------------- |
| macOS             | `brew install mariadb`           | gives `mariadb-binlog`. Prefer a client at least as new as the server. |
| Debian/Ubuntu     | `sudo apt install mariadb-client`| gives `mariadb-binlog`. The grants above are sufficient.               |
| Fedora/RHEL       | `sudo dnf install mariadb`       | uses the same binary name.                                            |
| No package access | the Python reader                | needs only `pymysql`/`asyncmy` and `mysql-replication`.               |

Do not copy the decoder from a container. It fails on `libssl.so.1.1` on a modern host.
The Python reader avoids that problem.

## Before you start: is this the right fix?

Tell the user these limits before you write code. The SQL path gives up safety for
speed.

- Use this method only on a wiki that you control. The wiki must have a snapshot that
  you can restore. There is no validation, no hook, no change dispatch, no edit
  conflict handling, and no extension notification.
- Measure the bottleneck first. If the user creates hundreds of items with one
  `write()` at a time, try concurrency before this method. The API is latency-bound.
  A worker pool usually gives most of the gain with no risk.
- Use SQL when the count is in the tens of thousands. Use SQL also when the API path is
  already parallel and still too slow.
- Batch the write. A writer that takes one entity per call keeps the shape of the HTTP
  path. Each entity pays a transaction, a dozen lookups, and about twenty inserts. One
  call with a list of entities pays the lookups once. It writes one statement per table
  for each few hundred entities. On the reference instance, a hundred items cost 2731
  statements one call each, and 30 in one call. The reference writer is async on
  `asyncmy`. Its `write` is a coroutine that takes a dict or a list. A caller with
  several batches awaits them together. Step 6 gives the shape.
- Keep the API for all operations except creation. An edit must operate on
  `rev_parent_id`, `page_latest` chaining, term-store differences, and edit conflicts.
  That is a different problem. This skill is for new entities only. Write a claim with
  its entity. Do not add a claim to an entity that exists.
- A property also carries its datatype in the property-info table that the inventory
  names. The API refuses a create for a datatype that the instance does not offer. The
  writer cannot know that list, because it lives in `LocalSettings.php`. The writer
  writes the datatype that it is given. The API then serves that property back like any
  other. That is a real divergence. The writer can put a datatype on the wiki that no
  API call can create.

## Method

### 1. Capture one real save

The binlog is the only complete description of a write. Application logs and write-ups
usually stop early. The capture in `references/worked-example.md` is no exception, but
it shows the shape of that trap. Make sure that every claim agrees with a capture that
you took yourself.

Use `scripts/capture.sh` for the whole loop. It records the position. It runs the
command. It waits for the deferred updates: the term store, `page_props`, and
`recentchanges` land after the response. It records the position again. It decodes the
window. It names every column from `information_schema.COLUMNS`. It drops the noise
tables:

```bash
scripts/capture.sh -- python write_entity.py
scripts/capture.sh --tables page,revision,text -- python write_entity.py
scripts/capture.sh --json --output /tmp/api.json -- python write_entity.py
```

The default window excludes `objectcache`, `l10n_cache`, `job`, `querycache*`,
`site_stats`, and `user`. `--keep-noise` keeps them. `--exclude` replaces the list.
The output is one line per row with `column=value` pairs, or typed JSON with `--json`.

`--entity Q123` or `--page-id 157` reduces a saved window to one entity. It follows
the ids: the page, its revisions, text, content, slots, term-store rows, links, log
rows, watchlist row, and recent-changes row. A create has no Q-number until the
counter moves. Use `--tables` for the live capture. Or run the formatter over a saved
window later. `--wait` covers a slow instance.

The command's stdout goes to stderr, so a `--json` capture on stdout stays valid even
when the write prints the new id. The exit status is the command's.

To repeat a decode without a new write, use the manual form:

```bash
scripts/binlog-diff.sh pos                    # -> "mariadb-bin.000002 20993148"
scripts/binlog-diff.sh diff 20993148 21012212 # the window that write landed in
```

Use positions that `pos` printed. Do not calculate an offset. A position inside an
event makes the decoder read the rest of that event as a length. The decoder then
stops with a packet error. That error is not clear.

Give the entity a token value (`f"New item {uuid4().hex[:8]}"`). Without a token, the
API rejects a second run as a duplicate label.

A claim names properties that the wiki must already hold. Capture the properties first.
Write the entity with claims in a second window. The property save is one exhibit. The
item that claims it is another. A property that the API has just written is not visible
to a claim, because the property-info row lands in a deferred update. Wait for that row.
If you do not wait, the API refuses the claim.

The window is the specification for the write. It holds every table that the save
touched, in the order of the touches. Five traps can make a capture look complete:

- **The decoder prints values, not column names.** `capture-format.py` joins each `@N`
  to `information_schema.COLUMNS`. Use that output. Do not map a number from memory. A
  wrong column name fails loudly. A wrong mapping writes a plausible row, and nothing
  reports it.
- **The stop position decides what you see.** Deferred updates commit after the
  response. If you read the stop position immediately, the capture holds only the
  transaction block. `recentchanges`, job rows, the actor edit count, and site
  statistics are missing. Wait about one second. Read the position again. Capture both
  blocks.
- **The term store is visible late.** It is a deferred update. `capture.sh` waits
  before the second position. A test that reads the term store immediately needs the
  same wait. Step 5 has the result.
- **Do not trust a pasted diff.** A capture can stop in the middle of a transaction.
  If it stops inside a group of related inserts, more inserts follow. Capture the
  window again. Get-or-create rows appear only in the first capture on a fresh wiki.
  A later capture is missing them, and it is not truncated.
- **The window holds every write of the server.** Other processes, deferred updates,
  and the job queue land between your positions. Find your save by entity id, page
  title, or revision. Compare that save. The number of `page` inserts is not the number
  of entities that you wrote. `capture.sh` drops known noise tables. `--entity` reduces
  a saved window to one save.

A claim does not write a table of its own. Every claim travels inside the entity blob.
The capture of an item with claims has the same rows as an item with terms alone, plus
the link rows beside the page. Do not look for a claims table before step 2 lists the
tables. The capture shows whether one exists.

### 2. Enumerate what it touched

List the distinct `(operation, table)` pairs in the capture. That list is the
specification. Do not copy a table list from this file. `capture-format.py
--list-tables` prints the list from the window:

```bash
scripts/binlog-diff.sh diff --file BINLOG START STOP > /tmp/window.txt
tables=$(scripts/capture-format.py --list-tables < /tmp/window.txt | paste -sd,)
scripts/db-structure.sh --allow-missing -t "$tables"
```

`db-structure.sh` prints the DDL as markdown. It reads no row. It takes the `DB_*`
values from the environment, from `./.env`, or from `~/.my.cnf` `[client]`. It finds
the database. A missing table is listed as absent, and the rest of the report prints.
Run it from the skill directory, or use an absolute path.

One capture covers one entity type and its claims. Capture the other type too. Merge
the two table lists. A property-only table and a claim-only table stay invisible until
a window holds them. `--entity` and `--tables` filter a saved window. They do not add
a table that the capture never had.

The DDL is not sufficient. Reproduce a **captured** row in Python. Compare your result
with the captured value. That method found every formula in step 3. It also catches a
column that moved.

A final-row `SELECT` is not a substitute for the capture. It cannot show a touched
table, the order, a get-or-create that wrote nothing, or a row that a later statement
updated. A wrong `SELECT` passes silently. Step 5 gives the full proof.

Never write a table from an example in this file. Run the scripts on your wiki. A
version that dropped a table or renamed a column fails here, cheaply, not in the wiki.

### 3. Reproduce the values

MediaWiki does not document these formulas. Each formula here was proved by
reproducing the stored value. The table gives the exceptions.

| Column                                                                                            | Formula                                                                                                                                                                                                                                                              |
| ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `content.content_size`, `revision.rev_len`, `page.page_len`, `recentchanges.rc_new_len`           | `strlen(serialize($entityArray))`. **This is the PHP serialize of the entity array, not the length of the JSON.** The stored JSON can be shorter than the serialized array. Compare both with the capture. Plain wikitext is the exception: its size is the text length. |
| `content.content_sha1`, `revision.rev_sha1`                                                       | The sha1 of the text, as hex, converted from base 16 to base 36 and zero-padded to 31 digits. MediaWiki uses its own arbitrary-precision `Wikimedia\base_convert`. The native PHP `base_convert` loses precision on a 160-bit value without an error. Do not use it. |
| `comment.comment_hash`                                                                            | crc32 of `comment_text`, wrapped into a **signed** 32-bit int                                                                                                                                                                                                        |
| `page.page_random`                                                                                | any double in `[0, 1)`                                                                                                                                                                                                                                               |
| `page.page_touched`, `page.page_links_updated`, `revision.rev_timestamp`, `logging.log_timestamp` | `binary(14)` UTC: `YYYYMMDDHHMMSS`                                                                                                                                                                                                                                   |
| `content.content_address`                                                                         | `"tt:" + text.old_id` (the old text-table address form)                                                                                                                                                                                                              |
| `text.old_flags`                                                                                  | `utf-8` for text stored as-is                                                                                                                                                                                                                                        |
| the entity blob in `text`                                                                         | Compact JSON, no spaces, `\uXXXX` escapes for non-ASCII, keys in Wikibase's order. An item: `type, id, labels, descriptions, aliases, claims, sitelinks`. A property: `type, datatype, id, labels, descriptions, aliases, claims` — no sitelinks, and the datatype sits directly after the type. |
| `logging.log_params`                                                                              | `a:1:{s:17:"associated_rev_id";i:<rev_id>;}`                                                                                                                                                                                                                         |
| `page_props`                                                                                      | The names and rows depend on the version. Take them from the capture and `inventory.py`. Captures show `wb-claims` (properties with a claim), `wb-identifiers` (the same over external-id properties), and `wb-sitelinks`. A version can write other names or a marker row. Use the capture. |
| `comment.comment_text` (the summary of the save)                                                  | The API's create summary for the type, e.g. `/* wbeditentity-create-item:0| */` or `/* wbeditentity-create-property:0| */`. The two texts differ, so the wiki holds two comment rows. Take the texts and hashes from the capture. |
| the counter table's `id_type`                                                                     | The content model name of the entity type, as `inventory.py` reports it. One counter for each type, so property numbers do not interleave with item numbers.                                                                                                          |
| the property-info table                                                                           | The property number, the datatype, and `pi_info` = `{"type":"<datatype>"}`, compact. One row, and only for a property. The API serves the datatype from this row, and a read-back of a SQL-written property returns whatever it holds. |

**Empty maps are `[]`, not `{}`.** Wikibase writes an empty term map as an empty PHP
array. JSON writes that as `[]`. If you write `{}`, the blob, its size, and its sha1
are all wrong.

#### The claims, and the three hashes they carry

A claim lives in the blob, and the blob is what the API serves back. Nothing else
stores it. The stored statement has this shape, and the order of the keys is the order
Wikibase writes them in:

```json
{
  "mainsnak": {
    "snaktype": "value",
    "property": "P205",
    "hash": "af50c51a46df4e21ec068d3a6c4723e153053128",
    "datavalue": { "value": "the value f072246b", "type": "string" }
  },
  "type": "statement",
  "qualifiers": { "P206": [ { "snaktype": "value", "property": "P206", "hash": "…", "datavalue": { … } } ] },
  "qualifiers-order": [ "P206" ],
  "id": "Q2709$A0257A82-E266-4456-BE94-7F4D67C22D9D",
  "rank": "normal",
  "references": [
    { "hash": "dd5e37863f5adc08db4082c577f9531e2ad9df2a",
      "snaks": { "P206": [ { "snaktype": "value", "property": "P206", "hash": "…", "datavalue": { … } } ] },
      "snaks-order": [ "P206" ] }
  ]
}
```

The writer input has a different shape. Here is the first claim of the capture, as
`new_item.get_json()` built it before the write:

```json
{
  "mainsnak": {
    "snaktype": "value",
    "property": "P205",
    "datatype": "string",
    "datavalue": {
      "value": "the value f072246b",
      "type": "string"
    }
  },
  "type": "statement",
  "rank": "normal",
  "qualifiers": {
    "P206": [
      {
        "snaktype": "value",
        "property": "P206",
        "datatype": "string",
        "datavalue": {
          "value": "the qualifier f072246b",
          "type": "string"
        }
      }
    ]
  },
  "qualifiers-order": [],
  "references": [
    {
      "snaks": {
        "P206": [
          {
            "snaktype": "value",
            "property": "P206",
            "datatype": "string",
            "datavalue": {
              "value": "first reference f072246b",
              "type": "string"
            }
          }
        ]
      },
      "snaks-order": []
    },
    {
      "snaks": {
        "P206": [
          {
            "snaktype": "value",
            "property": "P206",
            "datatype": "string",
            "datavalue": {
              "value": "second reference f072246b",
              "type": "string"
            }
          }
        ]
      },
      "snaks-order": []
    }
  ]
}
```

Four rules follow from the difference:

- **No `hash` on a snak.** The writer computes it. It refuses an input that carries
  one. A hash that agrees with the blob but not with the value is a silent lie.
- **No `id` on a statement.** The id starts with the entity number. That number does
  not exist until the counter moves. The writer generates the id after the allocation.
- **A `datatype` on every snak.** The wiki drops it. The writer drops it too. It
  computes the hash over the snak without the datatype.
- **An empty `qualifiers-order` and `snaks-order`.** The wiki fills both from the map
  order. The writer derives them. A caller that sends a populated order is refused.
  The writer can only reproduce the order of the map.

A claim with no references has no `references` key. A reference with no snak is
dropped, as the API drops it.

Three values are computed, and none of them can be read:

| Value                    | Formula                                                                                                                                                                                                                                                                                                                                                              |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| the snak `hash`          | `sha1` of the snak's legacy `Serializable` form. The form is `C:<len>:"Wikibase\DataModel\Snak\PropertyValueSnak":<len>:{a:2:{i:0;s:<len>:"<property>";i:1;<datavalue>}}`. `<len>` counts **bytes**. `<datavalue>` is the datavalue class's own `serialize()`. |
| the reference `hash`     | `sha1` of the reference's snak hashes, **sorted**, joined with `\|`                                                                                                                                                                                                                                                                                                    |
| the statement `id`       | `<entity id>$<random UUID v4, upper case>` — generated, not computed, and unique per statement                                                                                                                                                                                                                                                                        |

Each datavalue type serializes in its own way. Each shape here was proved against a
capture:

| Datavalue                | The payload hashed for the snak hash                                                                                          |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `string`                 | the string itself, as `DataValues\StringValue`                                                                                 |
| `time`                   | a JSON list of `time, timezone, before, after, precision, calendarmodel` under `DataValues\TimeValue`                          |
| `monolingualtext`        | a **PHP serialized** list of `[language, text]` under `DataValues\MonolingualTextValue` — not the JSON beside it               |
| `globecoordinate`        | a JSON list of `latitude, longitude, altitude, precision, globe` under `DataValues\Geo\Values\GlobeCoordinateValue`             |
| `quantity`               | one `a:4:{}` under `DataValues\QuantityValue`. It holds the amount, the unit as a PHP string, and both bounds. Each of the three decimals is wrapped in its own `DataValues\DecimalValue`. |
| `wikibase-entityid`      | `Wikibase\DataModel\Entity\EntityIdValue` around the id's own class — `Wikibase\DataModel\Entity\ItemId` for a Q id, `NumericPropertyId` for a P id |

The table has two consequences. First, the caller `datatype` is dropped. The stored
snak has no `datatype` key. A writer that copies the input writes a different hash, a
different size, and a different sha1. Second, an entity id value is hashed through the
class of the id that it holds. An item value and a property value with the same number
hash differently.

The claims capture in `references/worked-example.md` has the expected hash of each
snak. Hash your reproduction of that JSON. Compare the two. They must be equal to the
character. That is the cheapest proof that the three formulas are right.

### 4. Reproduce the order and the ids

The capture gives the order. It has one `(op, table)` pair for each row, in write
order. Build the writer from that list. Do not use a sequence from this file.

Some dependencies are real and do not move:

- The page needs its revision before it can report one
- The term store creates a text row before the row that refers to it
- The counter moves before the entity id can appear anywhere

Everything else comes from the capture and `inventory.py`. That includes the link
table, the position of the property-info row, and the comment/actor storage.

The two types differ in values, not steps. Resolve each value:

- **page and talk namespaces:** `inventory.py`. Use the page and watchlist rows to
  make sure.
- **content model name and id:** `inventory.py`.
- **counter table and types:** `inventory.py`.
- **create summary:** the API action. The comment row shows the text.
- **term table and columns:** `inventory.py`.
- **property info:** `inventory.py`.
- **`page_props` names:** the capture and `inventory.py`.

**The namespace pair is a trap.** A property namespace is not the item talk namespace.
Take both from the capture. The page row gives the entity namespace. The two watchlist
rows give the entity and talk namespaces. `inventory.py` gives the API namespaces when
the wiki has no entity yet. Do not add one from memory.

**The link rows are the second trap.** The capture shows `linktarget` plus `pagelinks`,
or `pagelinks` with `pl_namespace` and `pl_title`. Keep one row for each distinct
target page. Main snaks, qualifiers, and references that name the same page share a
row. A `linktarget` get-or-create writes nothing when the target exists. That is not
an `ON DUPLICATE KEY UPDATE`. The decoder shows such an event differently.

`recentchanges` goes last in the writer sequence. The API capture usually does not show
it in the transaction block. MediaWiki writes it after the response. Insert it
yourself. Use the request-derived columns of a maintenance script. Build the column
list from the table that `inventory.py` found and from the capture. Use the values of
a maintenance script, not the values of the request. The section "What differs from an
API save" names the request values.

Id allocation: the value after the statement is the new entity number. Q1 is the first
item. The counter has one row for each entity type. Key it by the content model name
from `inventory.py`. A property number does not use an item number. Use the counter
table that the inventory names:

```sql
INSERT INTO <counter table> (id_type, id_value)
  VALUES ('wikibase-property', 1)          -- or 'wikibase-item'
  ON DUPLICATE KEY UPDATE id_value = id_value + 1;
SELECT id_value FROM <counter table> WHERE id_type = 'wikibase-property';
```

Then `id_value` becomes the entity id. Use `P<number>` for a property and
`Q<number>` for an item. Keep the prefix in the entity kind. Do not branch at each use
site.

Shared dimension tables need atomic get-or-create. Where the table has a unique key,
this idiom makes `lastrowid` return the existing row on a duplicate:

```sql
INSERT INTO <text table> (<text column>) VALUES (%s)
  ON DUPLICATE KEY UPDATE <text id> = LAST_INSERT_ID(<text id>);
```

Use this idiom at every level that the inventory names: text, text-in-lang,
term-in-lang, and item/property terms. All levels are shared across entities. A second
entity that reuses a label must find the existing rows. The dimension tables are shared
between items and properties. The item/property term table is not. An item and a
property never share a row there. The comment store is the exception. Its hash index
is not unique. It needs a `SELECT` and then an `INSERT`, as `CommentStore` does.

Resolve these values. Do not assume them: `content_models` for the model id, the
slot-role table for `main`, and the actor table by name. `inventory.py` reports the
first two and the stores that exist. MediaWiki capitalizes the first letter of a user
name. A configuration value of `admin` is `Admin` in the `actor` table.

### 5. Prove it

Two checks are mandatory on each change. Both compare your write with a capture of the
same operation through the API. A difference is a defect in the writer. Fix the writer.

Do not replace a check with a `SELECT` of the final rows. A final-row read cannot show
the order. It cannot show a table that the save updated, a get-or-create that wrote
nothing, or a table that the save never touched. A wrong `SELECT` passes silently. Use a `SELECT` to
inspect a value while you develop a formula. Do not use it as proof. Run the captures
on a quiet wiki. Accept the cost.

**Operation sequence.** This check proves that you touched the same tables in the same
order. Capture once around your write and once around an API write of the same entity.
`scripts/capture.sh --json` writes one file for each path.
`scripts/capture-compare.py` prints only the `(op, table)` pairs and rows that differ:

```bash
scripts/capture.sh --json -o /tmp/api.json -- python api_write.py
scripts/capture.sh --json -o /tmp/writer.json -- python writer_write.py
scripts/capture-compare.py /tmp/api.json /tmp/writer.json
```

It exits 1 on a difference. `--ignore-columns page_random,page_touched,...` keeps
surrogate values out of the row part. The sequence part is always exact.

Without the tool, the sequence is the same regex over the `###` output:

```python
import re

# events = the output of scripts/binlog-diff.sh diff --file BINLOG START STOP
sequence = re.findall(r"### (INSERT INTO|UPDATE) `[^`]+`\.`([^`]+)`", events)
```

Compare the **core sequence**: every pair that the transaction wrote. A capture that
waits before the stop position also carries the post-send block. That block differs by
version and is not part of the contract. Read it from the capture. The API usually
queues `job` rows and updates counters after the response. The writer carries
`recentchanges` in its place. Reproduce the core. Name the block.

Use a different token for each run. If you do not, the second write finds the shared
term rows and removes the duplicates. The sequences then differ.

**Row footprint.** Compare the rows of the two **captures**, table by table. Mask the
surrogate ids, the timestamps, and `page_random`. Four lessons:

- **Normalize at each depth.** The token and the entity id sit inside strings, tuples,
  and lists. A normalizer that handles only `str` and `bytes` skips the term rows.
  Those rows arrive as tuples of `(int, bytes, bytes)`.
- **Compare the blob identity, not only the blob.** The id is inside the stored JSON.
  Two correct writes have a different `content_size` and a different `rev_sha1`. Prove
  the formulas, not the values. Recompute the PHP-serialize size and the base-36 sha1
  from the stored text. Compare them with `content_size`, `content_sha1`, and
  `rev_sha1`. Also compare `content_address` with `"tt:" + old_id` as a string.
- **Recompute from the captured blob.** That check needs no second write. It cannot
  pass by agreeing with itself. The decoder prints the blob with its `\uXXXX` escapes
  intact. The captured value **is** the stored text. Remove the quotes and give it to
  your hash and your PHP serializer.
- **Read the entity back** with `wbi.item.get(id)` or `wbi.property.get(id)`. That
  read, not the row comparison, proves that the API accepts your rows. Examine the
  claims there too. Qualifiers and references come back from the blob. A wrong
  datavalue type, a lost qualifier, or a dropped reference shows there and nowhere
  else.

For a claim, the capture proves the three formulas without a second write. The
captured blob has the hash of each snak, the hash of each reference, and the statement
id. Recompute each one from the datavalue beside it. Compare the results. The worked
example does this and prints the hashes that it compared.

**The same proof as a test.** Keep both checks as a test suite. Write the test twice:
once against the API and once against your writer. Keep all other lines the same:

```python
# the reference: the API write
return new_item.write()

# the writer under test
return write_item(new_item.get_json())
```

Identical fixtures and identical assertions make a divergence fail a test. A suite
that reads only final rows is a regression aid, not the acceptance gate. It cannot see
order, get-or-create, or a table that nobody knew about. When the test runner cannot
read the binlog, run `capture-compare` as a required release check. Do not claim
parity without it. Six rules make the test work:

- **The read stays on the API.** Both files read the entity with `wbi.item.get(id)`.
  A comparison of two database rows proves only that the writer agrees with itself.
  The API read proves that Wikibase accepts the rows.
- **Do not take a reference entity from the API when the guard reads the term store.**
  The writer refuses a duplicate pair by querying the term store. An API save reaches
  the term store in a deferred update after the response. A test that creates the
  reference item through the API and then writes the duplicate is a race. The guard
  sees no terms. The write succeeds. The test reports `DID NOT RAISE`. Write both
  entities through the writer, or wait for the term store before the second write.
- **One entity for each module.** Use three fixtures with module scope: `wbi` (the
  login), `written_item` (the write), and `stored_item` (the read-back). The write
  occurs in a fixture. If it fails, each test that needs it fails, and the traceback
  points at the write.
- **One token for each run.** `TOKEN = uuid4().hex[:8]` goes in each label, alias, and
  description. The API refuses an item when its label and description repeat an
  existing pair in the same language. It refuses a property when its label repeats.
  Fixed values make the second run fail.
- **One id assertion.** `ITEM_ID = re.compile(r"^Q[1-9][0-9]*$")`, and `PROPERTY_ID`
  with `P` for a property. It finds a write that reused an id or returned no id. The
  round-trip assertions do not find that error.
- **Aliases are a list.** Use `[alias.value for alias in stored_aliases]`, where
  `stored_aliases = stored_item.aliases.get(language)`. One language holds many
  aliases and only one label.

### 6. Write a whole call in one transaction

A writer that takes one entity per call reproduces the API one save at a time. That is
the right first version. It is the easiest to prove. When it is proven, take a list.
The rows of the call go in together. The round trips stop being the cost. On the
reference instance, a hundred items cost 2731 statements one call each, and 30 in one
call.

The rules:

- **One statement per table for the batch.** Chunk at a few hundred rows. Keep the
  order from step 4. Each lookup is one query for the call: property datatypes,
  entity-value pages, existing terms, content model, slot role, comment, and actor.
- **Read ids from the first id of an `INSERT`.** A multi-row statement reports its
  first id. The rows that follow take the next ids, but only if the server gives
  consecutive ids. Read `SELECT @@auto_increment_increment` once per connection. If it
  is not 1, insert one row per statement. `check-env.sh` prints this variable.
- **Read term-store ids back.** An upsert that matched a row reports no id.
  `lastrowid` says nothing. Write with
  `INSERT … ON DUPLICATE KEY UPDATE <id> = <id>`. Then read the ids by the unique key
  in one query with a row constructor:
  `WHERE (wbxl_text_id, wbxl_language) IN ((%s, %s), …)`. Two statements for each level
  for the whole call.
- **A link-target table is the exception.** If the capture writes one, read it first
  and insert only what is missing. The capture shows no event for an existing target.
  An upsert shows one. Two calls can race. Both read the target as missing. The
  second insert fails on the unique key. Use the `INSERT IGNORE` that MediaWiki uses.
  Read the ids with a locking read (`FOR UPDATE`). A row committed after your read is
  not in your snapshot. If the capture has no such table, the link row is `pagelinks`
  alone.
- **Update the page from the rows just written.** `page_latest`, `page_len`, and
  `page_content_model` come from the revision and content rows. `page_links_updated`
  comes from `rev_timestamp`. Both updates are one statement each for the call.
- **Group the guards.** Use one query for each language for the terms of the whole
  call. Reduce to the lowest id for each pair in Python. Walk the call in input order.
  An entity also clashes with an earlier entity in the same call. A refused entity
  must roll back the whole call, entity number included.
- **Make the driver async.** `asyncmy` with a prepared-statement cache turns
  `executemany` into one bulk round trip on MariaDB. A caller can await several calls
  together. Concurrency alone gave 15% of the gain on the reference instance. The
  statements are the win. Bound the calls in flight. Each call takes a connection. A
  group with no bound asks for one connection per entity and fails with
  `1040 Too many connections`.

The transaction boundary is the whole call. State this in the code and the docstring.
One refused entity means that no entity of the call is written, and no entity number
is taken. A caller that is used to one entity per call must know this.

## What differs from an API save

State these limits. Do not hide them. The rows must match the API save. Each difference
here is a decision with a reason. Before you call a table impossible, examine what
MediaWiki writes for a maintenance script. It often writes that table with no request.

- **The post-send block.** MediaWiki commits work after the response. A capture that
  ends immediately does not show it. Take the table list from the capture. It varies by
  version and extensions. The writer reproduces the `recentchanges` row and nothing
  else from that block. The jobs carry the request id, the root job signature, and a
  timestamp. MediaWiki deduplicates them by `job_sha1`. No writer without a request can
  queue them faithfully. The counters are reproducible if the caller needs exact
  statistics. This skill does not claim the block.
- **`recentchanges` arrives late.** MediaWiki writes this table in the post-send block.
  A capture that ends at the response does not show it. The writer must insert the row
  itself. Two columns come from the request: `rc_ip` and `rc_patrolled`. With no
  request, write the values of a maintenance script (`127.0.0.1`, `0`), unless the
  capture shows another value. Without this table, the entity never appears in
  Special:RecentChanges.
- **Search.** `wbsearchentities` reads the term store that the inventory names. It does
  not read the entity blob. The term store holds a label, a description, or an alias.
  It never holds a claim value. If you omit the term store, the entity is readable but
  not searchable. The difference is not visible.
- **A claim is not always indexed.** A claim lives in the blob. A query for a value
  can find it in the text row and nowhere else. A claim or usage table is a capture
  fact. Add the table if the capture writes it. Do not invent one if it does not.
- **Hooks, the change table (if present), the parser cache, and each extension that
  listens to `PageContentSave`.** No component invalidates the caches for you. A new id
  is safe because nothing can cache it. Other ids are not safe.
- **The datatype of a property.** The API refuses a create for a datatype that the
  instance does not offer. The writer writes what it is given. The API then serves that
  property back, datatype included. The list of offered datatypes lives in
  `LocalSettings.php`, not in the tables. The writer cannot know it.
- **The datatypes whose claims write a table of their own.** A `url` claim writes
  `externallinks`. A `commonsMedia` or `localMedia` claim writes `imagelinks`. A
  `geo-shape` or `tabular-data` claim needs a `Data:` page on the shared repository. A
  writer that does not reproduce those rows must refuse those datatypes by name. Do not
  write a claim with missing link rows.
- **The guards of the API.** Wikibase refuses a create on its terms. The writer makes
  the same checks. The section "Guard the writer" gives the messages and the queries.

## Guard the writer

Use a whitelist at the entry point. Reproduce only the fields that you write. Raise an
error for every other field and name it. A writer that drops `claims` writes an entity
that looks correct but is not. Make sure that the entity type and the top-level keys
are correct. Each term map must have the correct shape. Do this before the database.

The whitelist depends on the type. An item has `sitelinks` and never `datatype`. A
property has `datatype` and never `sitelinks`. A property without a datatype is not
writable. The property-info row needs a value that the caller did not give. The API
refuses the create.

Then guard the claims before the first `INSERT`. Use the messages of the API:

- **Take the JSON of an unsaved entity.** The input must have no entity `id`, no
  statement `id`, and no snak `hash`. The API refuses a create that names an id. The
  statement id starts with the entity number, which does not exist yet. The writer
  computes the hash. Refuse all three by name. A caller that passes
  `wbi.item.get(id)` writes a second entity that looks like an edit.
- **A property that a snak names must exist.** The API answers
  `Property [[Property:P99999|P99999]] not found`.
- **A value must have the type that its property carries.** The API answers
  `Bad value type string, expected time`. `string` and `external-id` carry a string.
  `edtf` is stored as a string. `time` carries a time. `quantity` carries a quantity.
  `monolingualtext` carries a monolingual text. `globe-coordinate` carries a globe
  coordinate. `wikibase-item` and `wikibase-property` carry an entity id.
- **An entity that a value names must exist.** The API answers
  `[[Item:Q99999999|Q99999999]] not found` for an item value. It answers
  `[[Property:P99999|P99999]] not found` for a property value.
- **The rank must be `deprecated`, `normal`, or `preferred`.** The API answers
  `The rank bogus is not a valid rank.` A claim with no rank is `normal`.
- **`novalue` and `somevalue` snaks hash with a different class.** A `url`,
  `commonsMedia`, `localMedia`, `geo-shape`, or `tabular-data` claim writes rows beside
  the page. Refuse both groups by name until you have a capture of each.

Two shapes are dropped, not refused, because the API drops them. The first is the
`datatype` key of a snak. The second is a reference with no snak. The stored statement
then has no `references` key. An **empty** `qualifiers-order` or `snaks-order` is what
`get_json()` sends. The writer ignores it too. A **populated** order is refused. The
writer derives both orders from the map. A caller order is one that the API does not
reproduce.

**Make the term checks of the API too.** Wikibase guards both types, and the rule
differs. The difference changes which creates the writer must refuse:

- A language whose label and description have the same text. Both types. The API
  answers `Label and description for language code en can not have the same value.`
- **An item:** a label and description **pair** that another item already carries. The
  API answers `Item [[Item:Q67|Q67]] already has label "…" associated with language
  code en, using the same description text.` The same label with another description
  is accepted.
- **A property:** a **label** that another property already carries, whatever its
  description. The API answers `Property [[Property:P67|P67]] already has label "…"
  associated with language code en.` A property is referenced by its label. The label
  alone is unique.

Raise with those messages. Name the entity that holds the terms. A caller can then
move between the two write paths without a change to its error handling. The
uniqueness is per language, not per wiki. The same label in another language is a new
entity.

A label **without** a description is not always checked for an item. Test the behavior
on your version with one API write. Make the writer match it. For a property, the check
is on the label alone. A property with no description still clashes. Run the checks
before the first `INSERT`.

`inventory.py` names the item term table, its entity column, its term-in-lang column,
and the three term-store tables. Substitute those names. The join shape is:

```sql
SELECT label_terms.<entity column>
  FROM <item terms> AS label_terms
  JOIN <term in lang> AS label_term
    ON label_term.<term id> = label_terms.<term in lang column>
  JOIN <text in lang> AS label_lang
    ON label_lang.<text in lang id> = label_term.<text in lang column>
  JOIN <text> AS label_text ON label_text.<text id> = label_lang.<text column>
  JOIN <item terms> AS description_terms
    ON description_terms.<entity column> = label_terms.<entity column>
  JOIN <term in lang> AS description_term
    ON description_term.<term id> = description_terms.<term in lang column>
  JOIN <text in lang> AS description_lang
    ON description_lang.<text in lang id> = description_term.<text in lang column>
  JOIN <text> AS description_text
    ON description_text.<text id> = description_lang.<text column>
 WHERE label_term.<type column> = 1 AND label_lang.<language> = <language>
   AND label_text.<text column> = <label>
   AND description_term.<type column> = 2
   AND description_lang.<language> = <language>
   AND description_text.<text column> = <description>
 LIMIT 1;
```

The type column is 1 for a label, 2 for a description, and 3 for an alias. For a
property, use the property term table and one term, not two.

Two more checks belong before the first `INSERT`. A property needs a datatype. The term
table to write is the one that `inventory.py` names for the entity type. A guessed name
fails with `1054 Unknown column`. A guessed **table** writes terms that nothing can
read.

## When the wiki version changes

A Wikibase release moves tables. Re-derive the method. Do not use a list of statements.
When the version moves:

1. Run `check-env.sh`. It prints the MediaWiki version, the Wikibase version, the
   database version, `binlog_format`, and `auto_increment_increment`. Run
   `inventory.py`. It prints the namespaces, model ids, term tables, and storage.
2. Capture one save of each kind again: an item, a property, and an item with claims,
   qualifiers, and references.
3. Run the two checks in step 5 against the new captures. Fix the writer until they
   agree. The two test suites do this if you keep them.
4. Compare the DDL of the tables that you write with `scripts/db-structure.sh`. Add or
   drop a table that the capture no longer holds.

A capture cannot change these items, because they are not tables:

- **The API shapes.** The JSON that a caller builds and the JSON that the API serves
  back are the interface. A claim is a snak with a datavalue. A statement has a rank and
  an id. A reference has an order. This does not move with the schema.
- **The formulas of step 3.** A hash is still the sha1 of a legacy `Serializable` form.
  A size is still the PHP serialization. Those are PHP class methods, not schema.
  Recapture to make sure, but expect them to hold.
- **The three hashes of a claim.** Wikibase classes compute them. The tables do not
  touch them.
- **The method and its scripts.** Count the events, compare the sequences, compare the
  rows, and read the entity back over the API.

This file has values that name an id, a namespace, a version, an `AUTO_INCREMENT`, or a
row count. Each one comes from one instance on one day. Treat each one as an example.
Do not treat it as a contract.

## Worked reference

`references/worked-example.md` shows three entities from start to end: an item, a
property, and an item with claims, a qualifier, and two references. It has the
`WikibaseIntegrator` call that wrote each one, the entity JSON, and the binlog capture
of each save. It also has the DDL of each touched table and the tables that a property and a claim
add. It has the post-send block and the login helper that the API write needs. Read it before you capture your own. It shows the target, the row count, and the
values that change between the two types.

The implementation that these exhibits produced is in the repository that holds this
skill. `src/arw/db/fast_wbi.py` holds the writer. `src/arw/db/constants.py` holds the
per-type values. `src/arw/db/external_links.py` holds the link-index formulas.
`test/api` and `test/sql` hold the two suites of step 5. They are the same test, one
line apart. Read them next to this file when you build your own. Copy what the capture
proves, not what the code happens to do.

`scripts/check-env.sh` says whether this machine can run the method.
`scripts/inventory.py` prints the schema facts of the wiki.
`scripts/db-structure.sh` prints the DDL of the tables that you name.
`scripts/binlog-diff.sh` reads a binlog window through `scripts/binlog-reader.py`.
`scripts/capture.sh` runs the whole capture loop. With these scripts, steps 0 to 2 need
no code of your own.

# wikibase-fast-insert

A skill for writing new Wikibase entities as SQL rows instead of one `wbeditentity`
call per entity. It captures one real API save from the binlog, reproduces its rows,
and proves the two agree.

Read [`SKILL.md`](SKILL.md). It is the method and the reference. The scripts are in
[`scripts/`](scripts/). The captures that the method came from are in
[`references/worked-example.md`](references/worked-example.md).

## Use

```bash
scripts/check-env.sh
scripts/inventory.py
scripts/db-structure.sh --allow-missing -t page,revision,text
scripts/capture.sh -- python write_entity.py
scripts/capture-compare.py api.json writer.json
```

`check-env.sh` prints the install command for each missing tool. It also reports the
four database grants. `inventory.py` asks the wiki for the schema facts: namespaces,
model ids, term tables, comment/actor/text/link storage, and page props. No version
number is passed to a script. The binlog decoder is `scripts/binlog-reader.py` by
default, through `mysql-replication`. It needs no local decoder binary and no Docker.
It reads the server version. If the package cannot decode rows, it stops and gives the
install command.

The proof is the capture pair, not a `SELECT` of the final rows. A final-row read
cannot see order, get-or-create rows, or a table that the save never touched.
`capture-compare.py` is the acceptance check.

## Scope

For new entities only, on a wiki you control with a restorable snapshot. It does not
reproduce the post-send block, `rc_ip`/`rc_patrolled`, hooks, extension notifications,
or edits. `SKILL.md` names every divergence.

## Schema changes

This method was re-derived on more than one MediaWiki/Wikibase schema. The API shapes
and the hash formulas are stable. The tables are not stable. Run `inventory.py` and
capture again when the wiki changes. No version is passed to a script.

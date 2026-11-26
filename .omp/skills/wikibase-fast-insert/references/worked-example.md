> **Exhibit, not a contract.** These captures come from one wiki on one day. The table
> names, namespace numbers, row counts, and hashes are evidence of what a save looked
> like there. They are not a list to copy. Run `scripts/inventory.py` on your wiki.
> Capture one save of your own. The tables decide, and this file does not.

# Three entities, from API call to database rows

This file shows three saves from start to end: an item, a property, and an item with
claims, a qualifier, and two references. For each save it gives the
`WikibaseIntegrator` call, the entity JSON, the binlog capture, and the DDL of each
touched table. `SKILL.md` holds the method. Examine the shape here. Then capture your
own save. Your wiki version, extensions, and configuration can differ.

Read this file before you reproduce a write. It shows the target: a correct capture,
the row count for one entity, the mandatory columns, and the values that change
between the two types. It also shows the values that change when an entity has
claims.

## Contents

- [The write](#the-write)
- [The entity JSON](#the-entity-json)
- [The binlog capture](#the-binlog-capture)
- [The same write, for a property](#the-same-write-for-a-property)
- [The same write, with claims](#the-same-write-with-claims)
- [The block the capture misses when you stop early](#the-block-the-capture-misses-when-you-stop-early)
- [The table structures](#the-table-structures)
- [The tables a claim adds](#the-tables-a-claim-adds)
- [The helper the capture uses](#the-helper-the-capture-uses)

The login helper that the snippets import is at the end of this file.
`scripts/binlog-diff.sh` makes the capture. It needs no Python.

## The write

```python
from wikibaseintegrator import WikibaseIntegrator

from authenticator import login_as_user

wbi = WikibaseIntegrator(login=login_as_user())

new_item = wbi.item.new()

new_item.labels.set("en", "New item")
new_item.labels.set("fr", "Nouvel élément")

new_item.aliases.set("en", "Item")
new_item.aliases.set("fr", "Élément")

new_item.descriptions.set("en", "A freshly created element")
new_item.descriptions.set("fr", "Un élément fraichement créé")

new_item.write()
```

## The entity JSON

This is the input for a fast writer, and the shape that the blob in `text` must have.
The command `print(json.dumps(new_item.get_json(), ensure_ascii=False, indent=2))`
produced this JSON, so the values here are unescaped. The stored blob escapes them
(`é` → `\u00e9`).

```json
{
  "labels": {
    "en": {
      "language": "en",
      "value": "New item"
    },
    "fr": {
      "language": "fr",
      "value": "Nouvel élément"
    }
  },
  "descriptions": {
    "en": {
      "language": "en",
      "value": "A freshly created element"
    },
    "fr": {
      "language": "fr",
      "value": "Un élément fraichement créé"
    }
  },
  "aliases": {
    "en": [
      {
        "language": "en",
        "value": "Item"
      }
    ],
    "fr": [
      {
        "language": "fr",
        "value": "Élément"
      }
    ]
  },
  "sitelinks": {},
  "type": "item",
  "claims": {}
}
```

Two properties are exact: `aliases` is a **list for each language**, but `labels` and
`descriptions` are **one term for each language**. Both empty maps here become `[]`, not
`{}`, in the stored blob.

## The binlog capture

The calls that follow produced the window. They use `scripts/binlog-diff.sh`, which
reads the `DB_*` values itself:

```bash
scripts/binlog-diff.sh pos                       # -> "mariadb-bin.000002 4122366"

# run the insertion script, once

scripts/binlog-diff.sh pos                       # -> "mariadb-bin.000002 4135500"
scripts/binlog-diff.sh diff 4122366 4135500
```

**This capture is truncated.** It stops after the `watchlist` inserts. Do not use it as
the complete row set. The note after it explains the missing rows.

The command printed:

```txt
### INSERT INTO `my_wiki`.`content_models`
### SET
###   @1=2
###   @2='wikibase-item'
### INSERT INTO `my_wiki`.`wb_id_counters`
### SET
###   @1='wikibase-item'
###   @2=1
### INSERT INTO `my_wiki`.`page`
### SET
###   @1=2
###   @2=120
###   @3='Q1'
###   @4=0
###   @5=1
###   @6=0.016623593171000001362
###   @7='20260923130554'
###   @8=NULL
###   @9=0
###   @10=0
###   @11=NULL
###   @12=NULL
### INSERT INTO `my_wiki`.`comment`
### SET
###   @1=4
###   @2=-1188182935 (3106784361)
###   @3='/* wbeditentity-create-item:0| */'
###   @4=NULL
### INSERT INTO `my_wiki`.`revision`
### SET
###   @1=2
###   @2=2
###   @3=4
###   @4=1
###   @5='20260923130554'
###   @6=0
###   @7=0
###   @8=616
###   @9=0
###   @10='euztccohwrv7uo3eeguvqamkw6k3p32'
### INSERT INTO `my_wiki`.`text`
### SET
###   @1=2
###   @2='{"type":"item","id":"Q1","labels":{"en":{"language":"en","value":"New item"},"fr":{"language":"fr","value":"Nouvel \u00e9l\u00e9ment"}},"descriptions":{"en":{"language":"en","value":"A freshly created element"}
,"fr":{"language":"fr","value":"Un \u00e9l\u00e9ment fraichement cr\u00e9\u00e9"}},"aliases":{"en":[{"language":"en","value":"Item"}],"fr":[{"language":"fr","value":"\u00c9l\u00e9ment"}]},"claims":[],"sitelinks":[]}'
###   @3='utf-8'
### INSERT INTO `my_wiki`.`content`
### SET
###   @1=2
###   @2=616
###   @3='euztccohwrv7uo3eeguvqamkw6k3p32'
###   @4=2
###   @5='tt:2'
### INSERT INTO `my_wiki`.`slots`
### SET
###   @1=2
###   @2=1
###   @3=2
###   @4=2
### UPDATE `my_wiki`.`page`
### WHERE
###   @1=2
###   @2=120
###   @3='Q1'
###   @4=0
###   @5=1
###   @6=0.016623593171000001362
###   @7='20260923130554'
###   @8=NULL
###   @9=0
###   @10=0
###   @11=NULL
###   @12=NULL
### SET
###   @1=2
###   @2=120
###   @3='Q1'
###   @4=0
###   @5=1
###   @6=0.016623593171000001362
###   @7='20260923130554'
###   @8=NULL
###   @9=2
###   @10=616
###   @11='wikibase-item'
###   @12=NULL
### INSERT INTO `my_wiki`.`logging`
### SET
###   @1=4
###   @2='create'
###   @3='create'
###   @4='20260923130554'
###   @5=1
###   @6=120
###   @7='Q1'
###   @8=2
###   @9=4
###   @10='a:1:{s:17:"associated_rev_id";i:2;}'
###   @11=0
### INSERT INTO `my_wiki`.`log_search`
### SET
###   @1='associated_rev_id'
###   @2='2'
###   @3=4
### INSERT INTO `my_wiki`.`watchlist`
### SET
###   @1=1
###   @2=1
###   @3=120
###   @4='Q1'
###   @5=NULL
### INSERT INTO `my_wiki`.`watchlist`
### SET
###   @1=2
###   @2=1
###   @3=121
###   @4='Q1'
###   @5=NULL
```

### What the capture is missing

A second capture of the same operation on the same instance showed more rows. All of
them come after the last line:

- four `page_props` inserts (`wb-claims`, `wb-identifiers`, `wb-sitelinks`,
  `unexpectedUnconnectedPage`)
- a second `page` update, for `page_links_updated`
- the term store: six inserts each across `wbt_text`, `wbt_text_in_lang`,
  `wbt_term_in_lang`, and `wbt_item_terms`, one family for each term of the item.

The complete sequence is in `SKILL.md`, step 4, and in the claims exhibit below, whose
capture is not truncated: it runs from the id counter to the last `wbt_item_terms`
insert, and then names the post-send block that follows it. Two lessons are important:

- A family of inserts that stops abruptly is the mark of a truncated capture. The two
  `watchlist` rows here look like a natural ending, but they are not.
- The capture cannot show `recentchanges` when its window closes at the response.
  MediaWiki writes that table afterwards, in the post-send block. Examine the tables for
  the real footprint, and insert that row yourself: the section further down gives its
  columns and their values.

## The same write, for a property

A property is not a second implementation. It is the same sequence with ten different
values, and one extra row. That is why one writer serves both types.

### The write

```python
from wikibaseintegrator import WikibaseIntegrator
from wikibaseintegrator.wbi_enums import WikibaseDatatype

from authenticator import login_as_user

wbi = WikibaseIntegrator(login=login_as_user())

new_property = wbi.property.new()

new_property.datatype = WikibaseDatatype.STRING

new_property.labels.set("en", "Capture property fbd17555")
new_property.labels.set("fr", "Propriété capturée fbd17555")

new_property.aliases.set("en", "Captured fbd17555")

new_property.descriptions.set("en", "A captured property fbd17555")
new_property.descriptions.set("fr", "Une propriété capturée fbd17555")

new_property.write()
```

### The entity JSON

The stored blob of this save, with the escapes written out. A property has no
`sitelinks`, and it names its datatype directly after the type:

```json
{
  "type": "property",
  "datatype": "string",
  "id": "P346",
  "labels": {
    "en": { "language": "en", "value": "Capture property fbd17555" },
    "fr": { "language": "fr", "value": "Propriété capturée fbd17555" }
  },
  "descriptions": {
    "en": { "language": "en", "value": "A captured property fbd17555" },
    "fr": { "language": "fr", "value": "Une propriété capturée fbd17555" }
  },
  "aliases": {
    "en": [{ "language": "en", "value": "Captured fbd17555" }]
  },
  "claims": []
}
```

### The capture

The window `mariadb-bin.000002 11715574..11723816`, complete. Unlike the item capture
above, this one is not truncated: it ends with the last of the five
`wbt_property_terms` inserts. It is also missing `content_models` and `comment`, and
that is not truncation either — both rows already existed from an earlier save, so the
get-or-create statements wrote nothing. **A fresh wiki shows them; a wiki that has
written a property before does not.**

```txt
### UPDATE `my_wiki`.`wb_id_counters`
### WHERE
###   @1='wikibase-property'
###   @2=345
### SET
###   @1='wikibase-property'
###   @2=346
### INSERT INTO `my_wiki`.`page`
### SET
###   @1=381
###   @2=122
###   @3='P346'
###   @4=0
###   @5=1
###   @6=0.54360477594800005186
###   @7='20260923162106'
###   @8=NULL
###   @9=0
###   @10=0
###   @11=NULL
###   @12=NULL
### INSERT INTO `my_wiki`.`revision`
### SET
###   @1=381
###   @2=381
###   @3=5
###   @4=1
###   @5='20260923162106'
###   @6=0
###   @7=0
###   @8=603
###   @9=0
###   @10='72h5aq78sily5avlte7bemm8qt84xh8'
### INSERT INTO `my_wiki`.`text`
### SET
###   @1=381
###   @2='{"type":"property","datatype":"string","id":"P346","labels":{"en":{"language":"en","value":"Capture property fbd17555"},"fr":{"language":"fr","value":"Propri\u00e9t\u00e9 captur\u00e9e fbd17555"}},"descriptions":{"en":{"language":"en","value":"A captured property fbd17555"},"fr":{"language":"fr","value":"Une propri\u00e9t\u00e9 captur\u00e9e fbd17555"}},"aliases":{"en":[{"language":"en","value":"Captured fbd17555"}]},"claims":[]}'
###   @3='utf-8'
### INSERT INTO `my_wiki`.`content`
### SET
###   @1=381
###   @2=603
###   @3='72h5aq78sily5avlte7bemm8qt84xh8'
###   @4=3
###   @5='tt:381'
### INSERT INTO `my_wiki`.`slots`
### SET
###   @1=381
###   @2=1
###   @3=381
###   @4=381
### UPDATE `my_wiki`.`page`
### WHERE
###   @1=381
###   @2=122
###   @3='P346'
###   @4=0
###   @5=1
###   @6=0.54360477594800005186
###   @7='20260923162106'
###   @8=NULL
###   @9=0
###   @10=0
###   @11=NULL
###   @12=NULL
### SET
###   @1=381
###   @2=122
###   @3='P346'
###   @4=0
###   @5=1
###   @6=0.54360477594800005186
###   @7='20260923162106'
###   @8=NULL
###   @9=381
###   @10=603
###   @11='wikibase-property'
###   @12=NULL
### INSERT INTO `my_wiki`.`logging`
### SET
###   @1=383
###   @2='create'
###   @3='create'
###   @4='20260923162106'
###   @5=1
###   @6=122
###   @7='P346'
###   @8=381
###   @9=5
###   @10='a:1:{s:17:"associated_rev_id";i:381;}'
###   @11=0
### INSERT INTO `my_wiki`.`log_search`
### SET
###   @1='associated_rev_id'
###   @2='381'
###   @3=383
### INSERT INTO `my_wiki`.`watchlist`
### SET
###   @1=759
###   @2=1
###   @3=122
###   @4='P346'
###   @5=NULL
### INSERT INTO `my_wiki`.`watchlist`
### SET
###   @1=760
###   @2=1
###   @3=123
###   @4='P346'
###   @5=NULL
### INSERT INTO `my_wiki`.`page_props`
### SET
###   @1=381
###   @2='wb-claims'
###   @3='0'
###   @4=0
### INSERT INTO `my_wiki`.`page_props`
### SET
###   @1=381
###   @2='unexpectedUnconnectedPage'
###   @3='-122'
###   @4=-122
### UPDATE `my_wiki`.`page`
### WHERE
###   @1=381
###   @2=122
###   @3='P346'
###   @4=0
###   @5=1
###   @6=0.54360477594800005186
###   @7='20260923162106'
###   @8=NULL
###   @9=381
###   @10=603
###   @11='wikibase-property'
###   @12=NULL
### SET
###   @1=381
###   @2=122
###   @3='P346'
###   @4=0
###   @5=1
###   @6=0.54360477594800005186
###   @7='20260923162106'
###   @8='20260923162106'
###   @9=381
###   @10=603
###   @11='wikibase-property'
###   @12=NULL
### INSERT INTO `my_wiki`.`wb_property_info`
### SET
###   @1=346
###   @2='string'
###   @3='{"type":"string"}'
### INSERT INTO `my_wiki`.`wbt_text`
### SET
###   @1=889
###   @2='Capture property fbd17555'
### INSERT INTO `my_wiki`.`wbt_text`
### SET
###   @1=890
###   @2='Propriété capturée fbd17555'
### INSERT INTO `my_wiki`.`wbt_text`
### SET
###   @1=891
###   @2='A captured property fbd17555'
### INSERT INTO `my_wiki`.`wbt_text`
### SET
###   @1=892
###   @2='Une propriété capturée fbd17555'
### INSERT INTO `my_wiki`.`wbt_text`
### SET
###   @1=893
###   @2='Captured fbd17555'
### INSERT INTO `my_wiki`.`wbt_text_in_lang`
### SET
###   @1=911
###   @2='en'
###   @3=893
### INSERT INTO `my_wiki`.`wbt_text_in_lang`
### SET
###   @1=912
###   @2='en'
###   @3=891
### INSERT INTO `my_wiki`.`wbt_text_in_lang`
### SET
###   @1=913
###   @2='en'
###   @3=889
### INSERT INTO `my_wiki`.`wbt_text_in_lang`
### SET
###   @1=914
###   @2='fr'
###   @3=892
### INSERT INTO `my_wiki`.`wbt_text_in_lang`
### SET
###   @1=915
###   @2='fr'
###   @3=890
### INSERT INTO `my_wiki`.`wbt_term_in_lang`
### SET
###   @1=912
###   @2=1
###   @3=913
### INSERT INTO `my_wiki`.`wbt_term_in_lang`
### SET
###   @1=913
###   @2=1
###   @3=915
### INSERT INTO `my_wiki`.`wbt_term_in_lang`
### SET
###   @1=914
###   @2=2
###   @3=912
### INSERT INTO `my_wiki`.`wbt_term_in_lang`
### SET
###   @1=915
###   @2=2
###   @3=914
### INSERT INTO `my_wiki`.`wbt_term_in_lang`
### SET
###   @1=916
###   @2=3
###   @3=911
### INSERT INTO `my_wiki`.`wbt_property_terms`
### SET
###   @1=430
###   @2=346
###   @3=912
### INSERT INTO `my_wiki`.`wbt_property_terms`
### SET
###   @1=431
###   @2=346
###   @3=913
### INSERT INTO `my_wiki`.`wbt_property_terms`
### SET
###   @1=432
###   @2=346
###   @3=914
### INSERT INTO `my_wiki`.`wbt_property_terms`
### SET
###   @1=433
###   @2=346
###   @3=915
### INSERT INTO `my_wiki`.`wbt_property_terms`
### SET
###   @1=434
###   @2=346
###   @3=916
```

### What the property rows say

The `@N` numbers are positions in the table, so they only mean something with the DDL
and a `SELECT` next to them. Read out, the rows of this save are:

| Table            | Rows | What they hold                                                              |
| ---------------- | ---- | --------------------------------------------------------------------------- |
| `wb_id_counters` | 1    | `id_type = 'wikibase-property'`, `id_value` from 345 to 346                  |
| `page`           | 1    | `page_namespace = 122`, `page_title = 'P346'`, `page_content_model` set to `wikibase-property` by the first update |
| `revision`       | 1    | `rev_comment_id = 5`, `rev_actor = 1`, `rev_len = 603`, `rev_parent_id = 0`  |
| `text`           | 1    | the blob above, `old_flags = 'utf-8'`                                        |
| `content`        | 1    | `content_size = 603`, `content_model = 3`, `content_address = 'tt:381'`      |
| `slots`          | 1    | the one slot of the revision, role 1 (`main`), origin = the revision         |
| `logging`        | 1    | `create`/`create`, `log_namespace = 122`, `log_title = 'P346'`               |
| `log_search`     | 1    | `associated_rev_id` = the revision id                                        |
| `watchlist`      | 2    | namespaces 122 and 123                                                        |
| `page_props`     | 2    | `wb-claims = 0`, `unexpectedUnconnectedPage = -122`                          |
| `wb_property_info` | 1  | `pi_type = 'string'`, `pi_info = '{"type":"string"}'`                        |
| `wbt_text`       | 5    | the five distinct texts, shared with every other entity                      |
| `wbt_text_in_lang` | 5  | the same five, each with its language                                         |
| `wbt_term_in_lang` | 5  | the same five, each with its type: 1 label, 2 description, 3 alias            |
| `wbt_property_terms` | 5 | the five terms of P346, in the property table                           |

One value in `text` is worth a second look: the size 603 is the PHP serialization of the
entity array, not the length of the blob beside it. The stored blob is 433 characters,
all ASCII because every non-ASCII character is escaped (`é` → `\u00e9`), and the PHP
serialization of the same array is 603 bytes. The `rev_sha1` and `content_sha1` of
`72h5aq78sily5avlte7bemm8qt84xh8` are the base-36 form of the sha1 of that blob. Both
are recomputable from the stored text alone, which is the cheapest check that a writer's
formulas are right: no second write, and nothing to agree with.

### What changes between the two types

Everything else in the sequence holds. These ten values are the difference:

| Value                       | Item                      | Property                    |
| --------------------------- | ------------------------- | --------------------------- |
| `page_namespace`            | 120                       | **122**                     |
| `watchlist` namespaces      | 120, 121                  | **122, 123**                |
| `page_content_model`        | `wikibase-item`           | `wikibase-property`         |
| `content_models.model_name` | `wikibase-item` (2)       | `wikibase-property` (3)     |
| `wb_id_counters.id_type`    | `wikibase-item`           | `wikibase-property`         |
| `logging.log_namespace`     | 120                       | 122                         |
| the create summary          | `/* wbeditentity-create-item:0\| */` | `/* wbeditentity-create-property:0\| */` |
| `page_props` rows           | four                      | two                         |
| the term table              | `wbt_item_terms`          | `wbt_property_terms`        |
| the blob                    | ends `claims, sitelinks`  | ends `claims`, and holds `datatype` |

The namespace pair is the trap of this list. Wikibase's property namespace is **122**;
121 is the Item talk namespace. A writer that names its constants `ITEM_NAMESPACE = 120`
and `PROPERTY_NAMESPACE = 121` — as the first version of the reference implementation
did — writes every property into the item talk namespace, and both the page insert and
the two watchlist rows carry the wrong number. The capture above is what caught it: the
page of a property is `page_namespace = 122`, and its watchlist rows are 122 and 123.

The two `page_props` rows were checked against seven property datatypes
(`commonsMedia`, `edtf`, `external-id`, `geo-shape`, `quantity`, `tabular-data`,
`wikibase-item`): the set does not change with the datatype. Only `wb-claims` and the
unconnected-page marker are written, where an item also gets `wb-identifiers` and
`wb-sitelinks`.

## The same write, with claims

This is the exhibit that decides whether a writer is right. It writes an item with four
claims: a string claim that carries one qualifier and two references, a time claim, a
claim whose value is another item, and a claim on an external-id property. The row
sequence is the one of the item above with six more rows, and those six rows are the
whole difference between an entity with claims and one without.

### The properties it claims

A claim names a property the wiki must already hold, so these five were written first,
each exactly as the property exhibit above writes one:

| Property | Datatype        | Label                                  |
| -------- | --------------- | -------------------------------------- |
| `P205`   | `string`        | `Capture main property f072246b`       |
| `P206`   | `string`        | `Capture qualifier property f072246b`  |
| `P207`   | `time`          | `Capture time property f072246b`       |
| `P208`   | `wikibase-item` | `Capture item property f072246b`       |
| `P209`   | `external-id`   | `Capture identifier property f072246b` |

`P206` carries the qualifier and both references. `P208` names `Q1`, an item that already
existed, so its datavalue is an entity id and not a string.

### The write

```python
from wikibaseintegrator import WikibaseIntegrator, datatypes
from wikibaseintegrator.models.qualifiers import Qualifiers
from wikibaseintegrator.models.references import Reference, References

from authenticator import login_as_user

wbi = WikibaseIntegrator(login=login_as_user())

new_item = wbi.item.new()

new_item.labels.set("en", "Captured claim item f072246b")
new_item.labels.set("fr", "Élément capturé f072246b")

new_item.aliases.set("en", "Captured f072246b")

new_item.descriptions.set("en", "A captured item with claims f072246b")
new_item.descriptions.set("fr", "Un élément capturé avec des déclarations f072246b")

qualifiers = Qualifiers()
qualifiers.add(datatypes.String(prop_nr="P206", value="the qualifier f072246b"))

references = References()
for value in ("first reference f072246b", "second reference f072246b"):
    reference = Reference()
    reference.add(datatypes.String(prop_nr="P206", value=value))
    references.add(reference)

new_item.claims.add(
    datatypes.String(
        prop_nr="P205",
        value="the value f072246b",
        qualifiers=qualifiers,
        references=references,
    )
)
new_item.claims.add(datatypes.Time(prop_nr="P207", time="now"))
new_item.claims.add(datatypes.Item(prop_nr="P208", value="Q1"))
new_item.claims.add(datatypes.ExternalID(prop_nr="P209", value="ID-f072246b"))

new_item.write()
```

A writer does not call `write()`. It takes `new_item.get_json()` **before** that call,
because the API adds an entity id, a statement id and a snak hash to what it is given,
and none of the three belongs in the input. `SKILL.md`, step 3, shows that input.

### The entity blob the wiki stored

The blob, read back out of `text.old_text`, with the escapes resolved. This is what a
writer must produce, and what the API then serves back claim by claim:

```json
{
  "type": "item",
  "id": "Q2709",
  "labels": {
    "en": {
      "language": "en",
      "value": "Captured claim item f072246b"
    },
    "fr": {
      "language": "fr",
      "value": "Élément capturé f072246b"
    }
  },
  "descriptions": {
    "en": {
      "language": "en",
      "value": "A captured item with claims f072246b"
    },
    "fr": {
      "language": "fr",
      "value": "Un élément capturé avec des déclarations f072246b"
    }
  },
  "aliases": {
    "en": [
      {
        "language": "en",
        "value": "Captured f072246b"
      }
    ]
  },
  "claims": {
    "P205": [
      {
        "mainsnak": {
          "snaktype": "value",
          "property": "P205",
          "hash": "af50c51a46df4e21ec068d3a6c4723e153053128",
          "datavalue": {
            "value": "the value f072246b",
            "type": "string"
          }
        },
        "type": "statement",
        "qualifiers": {
          "P206": [
            {
              "snaktype": "value",
              "property": "P206",
              "hash": "3b9083463083ddd5a332d7de59d7560e53b657e5",
              "datavalue": {
                "value": "the qualifier f072246b",
                "type": "string"
              }
            }
          ]
        },
        "qualifiers-order": [
          "P206"
        ],
        "id": "Q2709$A0257A82-E266-4456-BE94-7F4D67C22D9D",
        "rank": "normal",
        "references": [
          {
            "hash": "dd5e37863f5adc08db4082c577f9531e2ad9df2a",
            "snaks": {
              "P206": [
                {
                  "snaktype": "value",
                  "property": "P206",
                  "hash": "a13b59948b40685c3229291853b71a64f7b7422e",
                  "datavalue": {
                    "value": "first reference f072246b",
                    "type": "string"
                  }
                }
              ]
            },
            "snaks-order": [
              "P206"
            ]
          },
          {
            "hash": "5996fde8d126a9348fd95f398376d9d804050df8",
            "snaks": {
              "P206": [
                {
                  "snaktype": "value",
                  "property": "P206",
                  "hash": "4dd022a5c46ccb52724f517943ef4bca40dca433",
                  "datavalue": {
                    "value": "second reference f072246b",
                    "type": "string"
                  }
                }
              ]
            },
            "snaks-order": [
              "P206"
            ]
          }
        ]
      }
    ],
    "P207": [
      {
        "mainsnak": {
          "snaktype": "value",
          "property": "P207",
          "hash": "ad1f8c9d8d6d825ff790e657e205d141c2ba9490",
          "datavalue": {
            "value": {
              "time": "+2026-09-23T00:00:00Z",
              "timezone": 0,
              "before": 0,
              "after": 0,
              "precision": 11,
              "calendarmodel": "http://www.wikidata.org/entity/Q1985727"
            },
            "type": "time"
          }
        },
        "type": "statement",
        "id": "Q2709$CAE8992A-A2F0-438A-B7C7-1DE08FB79B8D",
        "rank": "normal"
      }
    ],
    "P208": [
      {
        "mainsnak": {
          "snaktype": "value",
          "property": "P208",
          "hash": "24b5145b36925a952fedcbf8ae122d23777a9547",
          "datavalue": {
            "value": {
              "entity-type": "item",
              "numeric-id": 1,
              "id": "Q1"
            },
            "type": "wikibase-entityid"
          }
        },
        "type": "statement",
        "id": "Q2709$09D418C2-211A-481C-91A9-7C825B7AA6A2",
        "rank": "normal"
      }
    ],
    "P209": [
      {
        "mainsnak": {
          "snaktype": "value",
          "property": "P209",
          "hash": "8b90243ff8affb3f653c8edd170e2b638231b8dc",
          "datavalue": {
            "value": "ID-f072246b",
            "type": "string"
          }
        },
        "type": "statement",
        "id": "Q2709$B8697309-82D0-4549-AA54-55C6500FC8D8",
        "rank": "normal"
      }
    ]
  },
  "sitelinks": []
}
```

### The capture

One window, `mariadb-bin.000002 20993148..21012212`, taken with:

```bash
scripts/binlog-diff.sh pos > /tmp/before     # the position before the write
.venv/bin/python capture_item.py f072246b    # the write, once, through the API
scripts/binlog-diff.sh pos > /tmp/after      # the position after it
scripts/binlog-diff.sh diff --file mariadb-bin.000002 20993148 21012212
```

```txt
### UPDATE `my_wiki`.`wb_id_counters`
### WHERE
###   @1='wikibase-item'
###   @2=2708
### SET
###   @1='wikibase-item'
###   @2=2709
### INSERT INTO `my_wiki`.`page`
### SET
###   @1=2881
###   @2=120
###   @3='Q2709'
###   @4=0
###   @5=1
###   @6=0.68365270788300003257
###   @7='20260923180730'
###   @8=NULL
###   @9=0
###   @10=0
###   @11=NULL
###   @12=NULL
### INSERT INTO `my_wiki`.`revision`
### SET
###   @1=2881
###   @2=2881
###   @3=5
###   @4=1
###   @5='20260923180730'
###   @6=0
###   @7=0
###   @8=3284
###   @9=0
###   @10='omtv9mlkg85h6kbc7kbrxnwuynpmkux'
### INSERT INTO `my_wiki`.`text`
### SET
###   @1=2881
###   @2='{"type":"item","id":"Q2709","labels":{"en":{"language":"en","value":"Captured claim item f072246b"},"fr":{"language":"fr","value":"\u00c9l\u00e9ment captur\u00e9 f072246b"}},"descriptions":{"en":{"language":"en","value":"A captured item with claims f072246b"},"fr":{"language":"fr","value":"Un \u00e9l\u00e9ment captur\u00e9 avec des d\u00e9clarations f072246b"}},"aliases":{"en":[{"language":"en","value":"Captured f072246b"}]},"claims":{"P205":[{"mainsnak":{"snaktype":"value","property":"P205","hash":"af50c51a46df4e21ec068d3a6c4723e153053128","datavalue":{"value":"the value f072246b","type":"string"}},"type":"statement","qualifiers":{"P206":[{"snaktype":"value","property":"P206","hash":"3b9083463083ddd5a332d7de59d7560e53b657e5","datavalue":{"value":"the qualifier f072246b","type":"string"}}]},"qualifiers-order":["P206"],"id":"Q2709$A0257A82-E266-4456-BE94-7F4D67C22D9D","rank":"normal","references":[{"hash":"dd5e37863f5adc08db4082c577f9531e2ad9df2a","snaks":{"P206":[{"snaktype":"value","property":"P206","hash":"a13b59948b40685c3229291853b71a64f7b7422e","datavalue":{"value":"first reference f072246b","type":"string"}}]},"snaks-order":["P206"]},{"hash":"5996fde8d126a9348fd95f398376d9d804050df8","snaks":{"P206":[{"snaktype":"value","property":"P206","hash":"4dd022a5c46ccb52724f517943ef4bca40dca433","datavalue":{"value":"second reference f072246b","type":"string"}}]},"snaks-order":["P206"]}]}],"P207":[{"mainsnak":{"snaktype":"value","property":"P207","hash":"ad1f8c9d8d6d825ff790e657e205d141c2ba9490","datavalue":{"value":{"time":"+2026-09-23T00:00:00Z","timezone":0,"before":0,"after":0,"precision":11,"calendarmodel":"http:\/\/www.wikidata.org\/entity\/Q1985727"},"type":"time"}},"type":"statement","id":"Q2709$CAE8992A-A2F0-438A-B7C7-1DE08FB79B8D","rank":"normal"}],"P208":[{"mainsnak":{"snaktype":"value","property":"P208","hash":"24b5145b36925a952fedcbf8ae122d23777a9547","datavalue":{"value":{"entity-type":"item","numeric-id":1,"id":"Q1"},"type":"wikibase-entityid"}},"type":"statement","id":"Q2709$09D418C2-211A-481C-91A9-7C825B7AA6A2","rank":"normal"}],"P209":[{"mainsnak":{"snaktype":"value","property":"P209","hash":"8b90243ff8affb3f653c8edd170e2b638231b8dc","datavalue":{"value":"ID-f072246b","type":"string"}},"type":"statement","id":"Q2709$B8697309-82D0-4549-AA54-55C6500FC8D8","rank":"normal"}]},"sitelinks":[]}'
###   @3='utf-8'
### INSERT INTO `my_wiki`.`content`
### SET
###   @1=2881
###   @2=3284
###   @3='omtv9mlkg85h6kbc7kbrxnwuynpmkux'
###   @4=3
###   @5='tt:2881'
### INSERT INTO `my_wiki`.`slots`
### SET
###   @1=2881
###   @2=1
###   @3=2881
###   @4=2881
### UPDATE `my_wiki`.`page`
### WHERE
###   @1=2881
###   @2=120
###   @3='Q2709'
###   @4=0
###   @5=1
###   @6=0.68365270788300003257
###   @7='20260923180730'
###   @8=NULL
###   @9=0
###   @10=0
###   @11=NULL
###   @12=NULL
### SET
###   @1=2881
###   @2=120
###   @3='Q2709'
###   @4=0
###   @5=1
###   @6=0.68365270788300003257
###   @7='20260923180730'
###   @8=NULL
###   @9=2881
###   @10=3284
###   @11='wikibase-item'
###   @12=NULL
### INSERT INTO `my_wiki`.`logging`
### SET
###   @1=2883
###   @2='create'
###   @3='create'
###   @4='20260923180730'
###   @5=1
###   @6=120
###   @7='Q2709'
###   @8=2881
###   @9=5
###   @10='a:1:{s:17:"associated_rev_id";i:2881;}'
###   @11=0
### INSERT INTO `my_wiki`.`log_search`
### SET
###   @1='associated_rev_id'
###   @2='2881'
###   @3=2883
### INSERT INTO `my_wiki`.`watchlist`
### SET
###   @1=7862
###   @2=1
###   @3=120
###   @4='Q2709'
###   @5=NULL
### INSERT INTO `my_wiki`.`watchlist`
### SET
###   @1=7863
###   @2=1
###   @3=121
###   @4='Q2709'
###   @5=NULL
### INSERT INTO `my_wiki`.`linktarget`
### SET
###   @1=58
###   @2=120
###   @3='Q1'
### INSERT INTO `my_wiki`.`linktarget`
### SET
###   @1=59
###   @2=122
###   @3='P205'
### INSERT INTO `my_wiki`.`linktarget`
### SET
###   @1=60
###   @2=122
###   @3='P206'
### INSERT INTO `my_wiki`.`linktarget`
### SET
###   @1=61
###   @2=122
###   @3='P207'
### INSERT INTO `my_wiki`.`linktarget`
### SET
###   @1=62
###   @2=122
###   @3='P208'
### INSERT INTO `my_wiki`.`linktarget`
### SET
###   @1=63
###   @2=122
###   @3='P209'
### INSERT INTO `my_wiki`.`pagelinks`
### SET
###   @1=2881
###   @2=58
###   @3=120
### INSERT INTO `my_wiki`.`pagelinks`
### SET
###   @1=2881
###   @2=59
###   @3=120
### INSERT INTO `my_wiki`.`pagelinks`
### SET
###   @1=2881
###   @2=60
###   @3=120
### INSERT INTO `my_wiki`.`pagelinks`
### SET
###   @1=2881
###   @2=61
###   @3=120
### INSERT INTO `my_wiki`.`pagelinks`
### SET
###   @1=2881
###   @2=62
###   @3=120
### INSERT INTO `my_wiki`.`pagelinks`
### SET
###   @1=2881
###   @2=63
###   @3=120
### INSERT INTO `my_wiki`.`page_props`
### SET
###   @1=2881
###   @2='wb-claims'
###   @3='4'
###   @4=4
### INSERT INTO `my_wiki`.`page_props`
### SET
###   @1=2881
###   @2='wb-sitelinks'
###   @3='0'
###   @4=0
### INSERT INTO `my_wiki`.`page_props`
### SET
###   @1=2881
###   @2='wb-identifiers'
###   @3='1'
###   @4=1
### INSERT INTO `my_wiki`.`page_props`
### SET
###   @1=2881
###   @2='unexpectedUnconnectedPage'
###   @3='-120'
###   @4=-120
### UPDATE `my_wiki`.`page`
### WHERE
###   @1=2881
###   @2=120
###   @3='Q2709'
###   @4=0
###   @5=1
###   @6=0.68365270788300003257
###   @7='20260923180730'
###   @8=NULL
###   @9=2881
###   @10=3284
###   @11='wikibase-item'
###   @12=NULL
### SET
###   @1=2881
###   @2=120
###   @3='Q2709'
###   @4=0
###   @5=1
###   @6=0.68365270788300003257
###   @7='20260923180730'
###   @8='20260923180730'
###   @9=2881
###   @10=3284
###   @11='wikibase-item'
###   @12=NULL
### INSERT INTO `my_wiki`.`wbt_text`
### SET
###   @1=15130
###   @2='Captured claim item f072246b'
### INSERT INTO `my_wiki`.`wbt_text`
### SET
###   @1=15131
###   @2='Élément capturé f072246b'
### INSERT INTO `my_wiki`.`wbt_text`
### SET
###   @1=15132
###   @2='A captured item with claims f072246b'
### INSERT INTO `my_wiki`.`wbt_text`
### SET
###   @1=15133
###   @2='Un élément capturé avec des déclarations f072246b'
### INSERT INTO `my_wiki`.`wbt_text`
### SET
###   @1=15134
###   @2='Captured f072246b'
### INSERT INTO `my_wiki`.`wbt_text_in_lang`
### SET
###   @1=15134
###   @2='en'
###   @3=15134
### INSERT INTO `my_wiki`.`wbt_text_in_lang`
### SET
###   @1=15135
###   @2='en'
###   @3=15132
### INSERT INTO `my_wiki`.`wbt_text_in_lang`
### SET
###   @1=15136
###   @2='en'
###   @3=15130
### INSERT INTO `my_wiki`.`wbt_text_in_lang`
### SET
###   @1=15137
###   @2='fr'
###   @3=15133
### INSERT INTO `my_wiki`.`wbt_text_in_lang`
### SET
###   @1=15138
###   @2='fr'
###   @3=15131
### INSERT INTO `my_wiki`.`wbt_term_in_lang`
### SET
###   @1=15134
###   @2=1
###   @3=15136
### INSERT INTO `my_wiki`.`wbt_term_in_lang`
### SET
###   @1=15135
###   @2=1
###   @3=15138
### INSERT INTO `my_wiki`.`wbt_term_in_lang`
### SET
###   @1=15136
###   @2=2
###   @3=15135
### INSERT INTO `my_wiki`.`wbt_term_in_lang`
### SET
###   @1=15137
###   @2=2
###   @3=15137
### INSERT INTO `my_wiki`.`wbt_term_in_lang`
### SET
###   @1=15138
###   @2=3
###   @3=15134
### INSERT INTO `my_wiki`.`wbt_item_terms`
### SET
###   @1=14655
###   @2=2709
###   @3=15134
### INSERT INTO `my_wiki`.`wbt_item_terms`
### SET
###   @1=14656
###   @2=2709
###   @3=15135
### INSERT INTO `my_wiki`.`wbt_item_terms`
### SET
###   @1=14657
###   @2=2709
###   @3=15136
### INSERT INTO `my_wiki`.`wbt_item_terms`
### SET
###   @1=14658
###   @2=2709
###   @3=15137
### INSERT INTO `my_wiki`.`wbt_item_terms`
### SET
###   @1=14659
###   @2=2709
###   @3=15138
### INSERT INTO `my_wiki`.`job`
### SET
###   @1=434
###   @2='cirrusSearchLinksUpdate'
###   @3=120
###   @4='Q2709'
###   @5='20260923180730'
###   @6='a:9:{s:10:"addedLinks";a:6:{i:0;s:7:"Item:Q1";i:1;s:13:"Property:P205";i:2;s:13:"Property:P206";i:3;s:13:"Property:P207";i:4;s:13:"Property:P208";i:5;s:13:"Property:P209";}s:12:"removedLinks";a:0:{}s:10:"prioritize";b:0;s:11:"update_kind";s:12:"page_refresh";s:15:"root_event_time";i:1790186850;s:7:"cluster";N;s:9:"namespace";i:120;s:5:"title";s:5:"Q2709";s:9:"requestId";s:24:"01a3bfd0642791a7bb9ab665";}'
###   @7=10762672
###   @8=0
###   @9=''
###   @10=NULL
###   @11='dhgnrz262s2k1hmcnpvmdk3nivjrcut'
### INSERT INTO `my_wiki`.`recentchanges`
### SET
###   @1=2881
###   @2='20260923180730'
###   @3=1
###   @4=120
###   @5='Q2709'
###   @6=5
###   @7=0
###   @8=0
###   @9=1
###   @10=2881
###   @11=2881
###   @12=0
###   @13=1
###   @14='mw.new'
###   @15=2
###   @16='172.18.0.4'
###   @17=0
###   @18=3284
###   @19=0
###   @20=0
###   @21=NULL
###   @22=''
###   @23=''
### UPDATE `my_wiki`.`user`
### WHERE
###   @1=1
###   @2='Admin'
###   @3=''
###   @4=':pbkdf2:sha512:30000:64:RS1ww/n6jbaw6hNOLqT4FQ==:w2BVvOz40YHTYBuRpOARAT9gzlbD5XfbIhHU0yuF9PZIBWM/MFlICr5fKFlLNUa9hEbXKwMKJzE/sDLCVOJfPw=='
###   @5=''
###   @6=NULL
###   @7='admin@wikibase.example'
###   @8='20260923174548'
###   @9='fcb1f48fdbc8f20467ac9da17f51903b'
###   @10='20260923174546'
###   @11=NULL
###   @12=NULL
###   @13='20260923174546'
###   @14=110
###   @15=NULL
###   @16=0
### SET
###   @1=1
###   @2='Admin'
###   @3=''
###   @4=':pbkdf2:sha512:30000:64:RS1ww/n6jbaw6hNOLqT4FQ==:w2BVvOz40YHTYBuRpOARAT9gzlbD5XfbIhHU0yuF9PZIBWM/MFlICr5fKFlLNUa9hEbXKwMKJzE/sDLCVOJfPw=='
###   @5=''
###   @6=NULL
###   @7='admin@wikibase.example'
###   @8='20260923174548'
###   @9='fcb1f48fdbc8f20467ac9da17f51903b'
###   @10='20260923174546'
###   @11=NULL
###   @12=NULL
###   @13='20260923174546'
###   @14=111
###   @15=NULL
###   @16=0
### INSERT INTO `my_wiki`.`job`
### SET
###   @1=435
###   @2='htmlCacheUpdate'
###   @3=120
###   @4='Q2709'
###   @5='20260923180730'
###   @6='a:10:{s:5:"table";s:9:"pagelinks";s:9:"recursive";b:1;s:13:"rootJobIsSelf";b:1;s:16:"rootJobSignature";s:40:"75dfd64cd807d50fc5f42ba3ab5f07b52c1ca282";s:16:"rootJobTimestamp";s:14:"20260923180730";s:11:"causeAction";s:10:"page-touch";s:9:"namespace";i:120;s:5:"title";s:5:"Q2709";s:9:"requestId";s:24:"01a3bfd0642791a7bb9ab665";s:10:"causeAgent";s:7:"unknown";}'
###   @7=201082511
###   @8=0
###   @9=''
###   @10=NULL
###   @11='3mure49r0rirosquc451m3752nk22qt'
### UPDATE `my_wiki`.`site_stats`
### WHERE
###   @1=1
###   @2=111
###   @3=0
###   @4=111
###   @5=1
###   @6=2
###   @7=0
### SET
###   @1=1
###   @2=112
###   @3=0
###   @4=112
###   @5=1
###   @6=2
###   @7=0
```

### What the capture says

Read out with the DDL and a `SELECT` beside it, the save is:

| Table                | Rows | What they hold                                                                        |
| -------------------- | ---- | ------------------------------------------------------------------------------------- |
| `wb_id_counters`     | 1    | the item counter, moved by one: this save is `Q2709`                                   |
| `page`               | 1    | `page_namespace = 120`, `page_title = 'Q2709'`                                         |
| `revision`           | 1    | `rev_len = 3284`, `rev_sha1 = omtv9mlkg85h6kbc7kbrxnwuynpmkux`                         |
| `text`               | 1    | the blob above: 2343 characters, every non-ASCII byte escaped                          |
| `content`            | 1    | `content_size = 3284`, `content_model = 2`, `content_address = 'tt:2881'`              |
| `slots`              | 1    | the one slot of the revision, role 1 (`main`), origin = the revision                    |
| `page` (2 updates)   | 2    | first the revision, the length and the content model, then `page_links_updated`          |
| `logging`            | 1    | `create`/`create`, `log_namespace = 120`, `log_params` names revision 2881               |
| `log_search`         | 1    | `associated_rev_id` = the revision id                                                   |
| `watchlist`          | 2    | namespaces 120 and 121                                                                 |
| `linktarget`         | 6    | the six target pages: `(120, 'Q1')` and `(122, 'P205')` … `(122, 'P209')`               |
| `pagelinks`          | 6    | one row per target, from page 2881                                                      |
| `page_props`         | 4    | `wb-claims = 4`, `wb-identifiers = 1`, `wb-sitelinks = 0`, `unconnected = -120`          |
| `wbt_text`           | 5    | the five terms: label and description in `en` and `fr`, the alias in `en`                |
| `wbt_text_in_lang`   | 5    | the same five, each with its language                                                   |
| `wbt_term_in_lang`   | 5    | the same five, each with its type: 1 label, 2 description, 3 alias                       |
| `wbt_item_terms`     | 5    | the five terms of Q2709                                                                 |
| post-send block      | 5    | two `job` rows, `recentchanges`, `user`, `site_stats` — see the section below            |

The last five rows of the capture are the post-send block, and they are not part of the
transaction: the `wbt_item_terms` insert is where an API save ends its own work, and
where a writer's row set ends too.

Four facts in that table are the ones a writer gets wrong:

- **No claim table is written.** The four claims are in the blob and nowhere else. On
  this version there is no `wb_claims` table to write, and `wbc_entity_usage`,
  `wb_changes` and `wb_items_per_site` hold no rows for the save either. A capture of an
  older or newer version may show the opposite; capture, do not assume.
- **Six link rows, not twelve.** Four claims name five properties and one item, and each
  distinct target page gets one `linktarget` row and one `pagelinks` row. A claim's
  qualifier and its references name properties of their own, so `P206` is in the list
  although no main snak uses it.
- **The claims do not touch the term store.** The five `wbt_*` families are exactly the
  labels, descriptions and aliases of the entity. A claim value is never a term, so
  `wbsearchentities` cannot find an entity by one.
- **`page_props` counts claims by property.** `wb-claims = 4` is the number of
  properties that carry a claim, and `wb-identifiers = 1` is the same count over the
  claims of external-id properties — the P209 claim, and not the string one beside it.

### The three hashes, against this capture

The blob carries the hash of every snak, the hash of every reference and the id of every
statement, so this capture proves all three formulas without a second write. Here are
the values to compare with, in the order the blob holds them:

| Claim                  | Value                                            | Snak hash                                  |
| ---------------------- | ------------------------------------------------ | ------------------------------------------ |
| `P205`, main snak      | `"the value f072246b"`                           | `af50c51a46df4e21ec068d3a6c4723e153053128` |
| `P205`, qualifier      | `"the qualifier f072246b"`                       | `3b9083463083ddd5a332d7de59d7560e53b657e5` |
| `P205`, reference 1    | `"first reference f072246b"`                     | `a13b59948b40685c3229291853b71a64f7b7422e` |
| `P205`, reference 2    | `"second reference f072246b"`                    | `4dd022a5c46ccb52724f517943ef4bca40dca433` |
| `P207`, main snak      | a time, `precision 11`, calendar `Q1985727`      | `ad1f8c9d8d6d825ff790e657e205d141c2ba9490` |
| `P208`, main snak      | an entity id, `item` `Q1`                        | `24b5145b36925a952fedcbf8ae122d23777a9547` |
| `P209`, main snak      | `"ID-f072246b"`, stored as a string              | `8b90243ff8affb3f653c8edd170e2b638231b8dc` |

| Reference             | Snaks                        | Reference hash                              |
| --------------------- | ---------------------------- | ------------------------------------------- |
| `P205`, the first     | the `a13b5994…` snak alone   | `dd5e37863f5adc08db4082c577f9531e2ad9df2a`  |
| `P205`, the second    | the `4dd022a5…` snak alone   | `5996fde8d126a9348fd95f398376d9d804050df8`  |

The statement ids are generated, not computed, and each one starts with the entity id:
`Q2709$A0257A82-E266-4456-BE94-7F4D67C22D9D` for the `P205` claim,
`Q2709$CAE8992A-A2F0-438A-B7C7-1DE08FB79B8D` for `P207`,
`Q2709$09D418C2-211A-481C-91A9-7C825B7AA6A2` for `P208`, and
`Q2709$B8697309-82D0-4549-AA54-55C6500FC8D8` for `P209`.

Two more numbers come from the same blob. Its size is `3284`, which is the PHP
serialization of the entity array and not the length of the 2343-character JSON beside
it, and its sha1 in base 36 is `omtv9mlkg85h6kbc7kbrxnwuynpmkux`. Recompute both from
the captured text before you compare anything else: a writer that gets those two right
has the blob right, and one that gets them wrong has a size and a hash that agree with
each other and with nothing else.

## The block the capture misses when you stop early

`recentchanges` is absent from a capture whose window closes at the response, because
MediaWiki writes that row afterwards. It is not optional for a writer:
Special:RecentChanges reads that table, so an entity without its row is invisible there.
Stop the window a second later and the row appears — with the three jobs and the two
counter updates beside it, all of them after the response:

```txt
INSERT INTO `my_wiki`.`job`   @2='cirrusSearchLinksUpdate'
INSERT INTO `my_wiki`.`recentchanges`
UPDATE `my_wiki`.`user`       user_editcount + 1
INSERT INTO `my_wiki`.`job`   @2='htmlCacheUpdate'      (table pagelinks, recursive)
INSERT INTO `my_wiki`.`job`   @2='recentChangesUpdate'  (the cached special page)
UPDATE `my_wiki`.`site_stats` ss_total_edits + 1, ss_total_pages + 1
```

Two facts about that block decide what a writer may claim:

- **The job rows are not reproducible.** Their parameters hold the request id, the root
  job timestamp and signature. MediaWiki also deduplicates them by `job_sha1`, so two
  identical saves queue a different number of them: three in one measured window, two in
  the next.
- **The two counters are reproducible**, with
  `UPDATE ... SET user_editcount = user_editcount + 1` and the same for `ss_total_edits`
  and `ss_total_pages`. The reference implementation leaves them to the wiki, and says so.

So a writer reproduces the `recentchanges` row and names the rest. That is also how to
read the sequence check in `SKILL.md`, step 5: compare the two captures with this block
removed, and expect the writer's own window to carry `recentchanges` where the API's
carries the block.

```sql
CREATE TABLE `recentchanges` (
  `rc_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `rc_timestamp` binary(14) NOT NULL,
  `rc_actor` bigint(20) unsigned NOT NULL,
  `rc_namespace` int(11) NOT NULL DEFAULT 0,
  `rc_title` varbinary(255) NOT NULL DEFAULT '',
  `rc_comment_id` bigint(20) unsigned NOT NULL,
  `rc_minor` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `rc_bot` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `rc_new` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `rc_cur_id` int(10) unsigned NOT NULL DEFAULT 0,
  `rc_this_oldid` int(10) unsigned NOT NULL DEFAULT 0,
  `rc_last_oldid` int(10) unsigned NOT NULL DEFAULT 0,
  `rc_type` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `rc_source` varbinary(16) NOT NULL DEFAULT '',
  `rc_patrolled` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `rc_ip` varbinary(40) NOT NULL DEFAULT '',
  `rc_old_len` int(11) DEFAULT NULL,
  `rc_new_len` int(11) DEFAULT NULL,
  `rc_deleted` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `rc_logid` int(10) unsigned NOT NULL DEFAULT 0,
  `rc_log_type` varbinary(255) DEFAULT NULL,
  `rc_log_action` varbinary(255) DEFAULT NULL,
  `rc_params` blob DEFAULT NULL,
  PRIMARY KEY (`rc_id`),
  KEY `rc_timestamp` (`rc_timestamp`),
  KEY `rc_namespace_title_timestamp` (`rc_namespace`,`rc_title`,`rc_timestamp`),
  KEY `rc_cur_id` (`rc_cur_id`),
  KEY `rc_new_name_timestamp` (`rc_new`,`rc_namespace`,`rc_timestamp`),
  KEY `rc_ip` (`rc_ip`),
  KEY `rc_ns_actor` (`rc_namespace`,`rc_actor`),
  KEY `rc_actor` (`rc_actor`,`rc_timestamp`),
  KEY `rc_name_type_patrolled_timestamp` (`rc_namespace`,`rc_type`,`rc_patrolled`,`rc_timestamp`),
  KEY `rc_this_oldid` (`rc_this_oldid`)
) ENGINE=InnoDB AUTO_INCREMENT=51 DEFAULT CHARSET=binary
```

Two real rows on this instance show the values. One comes from an API save of an item,
and the other from the wiki's `Main_Page`, which was written with no request. Only two
of the fixed columns differ:

| Column         | API save     | No request  |
| -------------- | ------------ | ----------- |
| `rc_ip`        | `172.18.0.3` | `127.0.0.1` |
| `rc_patrolled` | `2`          | `0`         |

Every other fixed column holds the same value in the two rows. `rc_timestamp` and
`rc_actor` come from the save. `rc_namespace` is the entity namespace: 120 for an item,
122 for a property, and `rc_title` is the entity id. `rc_comment_id` is the create
comment, and `rc_minor`, `rc_bot` and `rc_deleted` are 0. `rc_new` is 1, `rc_cur_id` is
the page id, `rc_this_oldid` is the revision id, and `rc_last_oldid` is 0. `rc_type` is
1, and `rc_source` is `mw.new`. `rc_old_len` is 0, and `rc_new_len` is the
PHP-serialize size. `rc_logid` is 0, `rc_log_type` is NULL, and `rc_log_action` and
`rc_params` are empty.

The insert itself is in `SKILL.md`, step 4.

## The table structures

The command that follows generated this report:

`scripts/db-structure.sh -t "content_models,wb_id_counters,page,comment,revision,text,content,slots,logging,log_search,watchlist"`

This skill includes the same tool. That `-t` list copies the truncated capture in this
file, so it also does not have `page_props` and the four `wbt_*` tables. Use the full
list in `SKILL.md`, step 2, when you generate your own report.

A snapshot like this shows one more fact: the `AUTO_INCREMENT=` value of each table is
the next id at capture time. It gives the number of rows that existed. `page` at 3 and
`watchlist` at 3 show that this snapshot came immediately after the first item. Thus
each id in the report is 1 or 2.

<!-- table: comment -->

### 1. `comment`

`BASE TABLE` · engine `InnoDB` · 4 columns

```sql
CREATE TABLE `comment` (
  `comment_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `comment_hash` int(11) NOT NULL,
  `comment_text` blob NOT NULL,
  `comment_data` blob DEFAULT NULL,
  PRIMARY KEY (`comment_id`),
  KEY `comment_hash` (`comment_hash`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=binary
```

<!-- table: content -->

### 2. `content`

`BASE TABLE` · engine `InnoDB` · 5 columns

```sql
CREATE TABLE `content` (
  `content_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `content_size` int(10) unsigned NOT NULL,
  `content_sha1` varbinary(32) NOT NULL,
  `content_model` smallint(5) unsigned NOT NULL,
  `content_address` varbinary(255) NOT NULL,
  PRIMARY KEY (`content_id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=binary
```

<!-- table: content_models -->

### 3. `content_models`

`BASE TABLE` · engine `InnoDB` · 2 columns

```sql
CREATE TABLE `content_models` (
  `model_id` int(11) NOT NULL AUTO_INCREMENT,
  `model_name` varbinary(64) NOT NULL,
  PRIMARY KEY (`model_id`),
  UNIQUE KEY `model_name` (`model_name`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=binary
```

<!-- table: logging -->

### 4. `logging`

`BASE TABLE` · engine `InnoDB` · 11 columns

```sql
CREATE TABLE `logging` (
  `log_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `log_type` varbinary(32) NOT NULL DEFAULT '',
  `log_action` varbinary(32) NOT NULL DEFAULT '',
  `log_timestamp` binary(14) NOT NULL DEFAULT '19700101000000',
  `log_actor` bigint(20) unsigned NOT NULL,
  `log_namespace` int(11) NOT NULL DEFAULT 0,
  `log_title` varbinary(255) NOT NULL DEFAULT '',
  `log_page` int(10) unsigned DEFAULT NULL,
  `log_comment_id` bigint(20) unsigned NOT NULL,
  `log_params` blob NOT NULL,
  `log_deleted` tinyint(3) unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY (`log_id`),
  KEY `log_type_time` (`log_type`,`log_timestamp`),
  KEY `log_actor_time` (`log_actor`,`log_timestamp`),
  KEY `log_page_time` (`log_namespace`,`log_title`,`log_timestamp`),
  KEY `log_times` (`log_timestamp`),
  KEY `log_actor_type_time` (`log_actor`,`log_type`,`log_timestamp`),
  KEY `log_page_id_time` (`log_page`,`log_timestamp`),
  KEY `log_type_action` (`log_type`,`log_action`,`log_timestamp`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=binary
```

<!-- table: log_search -->

### 5. `log_search`

`BASE TABLE` · engine `InnoDB` · 3 columns

```sql
CREATE TABLE `log_search` (
  `ls_field` varbinary(32) NOT NULL,
  `ls_value` varbinary(255) NOT NULL,
  `ls_log_id` int(10) unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY (`ls_field`,`ls_value`,`ls_log_id`),
  KEY `ls_log_id` (`ls_log_id`)
) ENGINE=InnoDB DEFAULT CHARSET=binary
```

<!-- table: page -->

### 6. `page`

`BASE TABLE` · engine `InnoDB` · 12 columns

```sql
CREATE TABLE `page` (
  `page_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `page_namespace` int(11) NOT NULL,
  `page_title` varbinary(255) NOT NULL,
  `page_is_redirect` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `page_is_new` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `page_random` double unsigned NOT NULL,
  `page_touched` binary(14) NOT NULL,
  `page_links_updated` binary(14) DEFAULT NULL,
  `page_latest` int(10) unsigned NOT NULL,
  `page_len` int(10) unsigned NOT NULL,
  `page_content_model` varbinary(32) DEFAULT NULL,
  `page_lang` varbinary(35) DEFAULT NULL,
  PRIMARY KEY (`page_id`),
  UNIQUE KEY `page_name_title` (`page_namespace`,`page_title`),
  KEY `page_random` (`page_random`),
  KEY `page_len` (`page_len`),
  KEY `page_redirect_namespace_len` (`page_is_redirect`,`page_namespace`,`page_len`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=binary
```

<!-- table: revision -->

### 7. `revision`

`BASE TABLE` · engine `InnoDB` · 10 columns

```sql
CREATE TABLE `revision` (
  `rev_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `rev_page` int(10) unsigned NOT NULL,
  `rev_comment_id` bigint(20) unsigned NOT NULL,
  `rev_actor` bigint(20) unsigned NOT NULL,
  `rev_timestamp` binary(14) NOT NULL,
  `rev_minor_edit` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `rev_deleted` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `rev_len` int(10) unsigned DEFAULT NULL,
  `rev_parent_id` bigint(20) unsigned DEFAULT NULL,
  `rev_sha1` varbinary(32) NOT NULL DEFAULT '',
  PRIMARY KEY (`rev_id`),
  KEY `rev_timestamp` (`rev_timestamp`),
  KEY `rev_page_timestamp` (`rev_page`,`rev_timestamp`),
  KEY `rev_actor_timestamp` (`rev_actor`,`rev_timestamp`,`rev_id`),
  KEY `rev_page_actor_timestamp` (`rev_page`,`rev_actor`,`rev_timestamp`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=binary
```

<!-- table: slots -->

### 8. `slots`

`BASE TABLE` · engine `InnoDB` · 4 columns

```sql
CREATE TABLE `slots` (
  `slot_revision_id` bigint(20) unsigned NOT NULL,
  `slot_role_id` smallint(5) unsigned NOT NULL,
  `slot_content_id` bigint(20) unsigned NOT NULL,
  `slot_origin` bigint(20) unsigned NOT NULL,
  PRIMARY KEY (`slot_revision_id`,`slot_role_id`),
  KEY `slot_revision_origin_role` (`slot_revision_id`,`slot_origin`,`slot_role_id`)
) ENGINE=InnoDB DEFAULT CHARSET=binary
```

<!-- table: text -->

### 9. `text`

`BASE TABLE` · engine `InnoDB` · 3 columns

```sql
CREATE TABLE `text` (
  `old_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `old_text` mediumblob NOT NULL,
  `old_flags` tinyblob NOT NULL,
  PRIMARY KEY (`old_id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=binary
```

<!-- table: watchlist -->

### 10. `watchlist`

`BASE TABLE` · engine `InnoDB` · 5 columns

```sql
CREATE TABLE `watchlist` (
  `wl_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `wl_user` int(10) unsigned NOT NULL,
  `wl_namespace` int(11) NOT NULL DEFAULT 0,
  `wl_title` varbinary(255) NOT NULL DEFAULT '',
  `wl_notificationtimestamp` binary(14) DEFAULT NULL,
  PRIMARY KEY (`wl_id`),
  UNIQUE KEY `wl_user` (`wl_user`,`wl_namespace`,`wl_title`),
  KEY `wl_namespace_title` (`wl_namespace`,`wl_title`),
  KEY `wl_user_notificationtimestamp` (`wl_user`,`wl_notificationtimestamp`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=binary
```

<!-- table: wb_id_counters -->

### 11. `wb_id_counters`

`BASE TABLE` · engine `InnoDB` · 2 columns

```sql
CREATE TABLE `wb_id_counters` (
  `id_type` varbinary(32) NOT NULL,
  `id_value` int(10) unsigned NOT NULL,
  PRIMARY KEY (`id_type`)
) ENGINE=InnoDB DEFAULT CHARSET=binary
```

### The tables a property adds

The report above copies the item capture, and the item capture stops before the term
store, so these are missing from it. They come from a later run of the same tool over
the property tables. The unique keys are the part that matters: they are what makes the
get-or-create idiom in `SKILL.md`, step 4, find an existing row instead of writing a
second one.

`scripts/db-structure.sh -t "page_props,wb_property_info,wbt_property_terms,wbt_text,wbt_text_in_lang,wbt_term_in_lang,wbt_item_terms"`

<!-- table: page_props -->

#### 1. `page_props`

`BASE TABLE` · engine `InnoDB` · 4 columns

```sql
CREATE TABLE `page_props` (
  `pp_page` int(10) unsigned NOT NULL,
  `pp_propname` varbinary(60) NOT NULL,
  `pp_value` blob NOT NULL,
  `pp_sortkey` float DEFAULT NULL,
  PRIMARY KEY (`pp_page`,`pp_propname`),
  UNIQUE KEY `pp_propname_page` (`pp_propname`,`pp_page`),
  UNIQUE KEY `pp_propname_sortkey_page` (`pp_propname`,`pp_sortkey`,`pp_page`)
) ENGINE=InnoDB DEFAULT CHARSET=binary
```

<!-- table: wb_property_info -->

#### 2. `wb_property_info`

`BASE TABLE` · engine `InnoDB` · 3 columns

```sql
CREATE TABLE `wb_property_info` (
  `pi_property_id` int(10) unsigned NOT NULL,
  `pi_type` varbinary(32) NOT NULL,
  `pi_info` blob NOT NULL,
  PRIMARY KEY (`pi_property_id`),
  KEY `pi_type` (`pi_type`)
) ENGINE=InnoDB DEFAULT CHARSET=binary
```

<!-- table: wbt_item_terms -->

#### 3. `wbt_item_terms`

`BASE TABLE` · engine `InnoDB` · 3 columns

```sql
CREATE TABLE `wbt_item_terms` (
  `wbit_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `wbit_item_id` int(10) unsigned NOT NULL,
  `wbit_term_in_lang_id` int(10) unsigned NOT NULL,
  PRIMARY KEY (`wbit_id`),
  UNIQUE KEY `wbt_item_terms_term_in_lang_id_item_id` (`wbit_term_in_lang_id`,`wbit_item_id`),
  KEY `wbt_item_terms_item_id` (`wbit_item_id`)
) ENGINE=InnoDB AUTO_INCREMENT=538 DEFAULT CHARSET=binary
```

<!-- table: wbt_property_terms -->

#### 4. `wbt_property_terms`

`BASE TABLE` · engine `InnoDB` · 3 columns

```sql
CREATE TABLE `wbt_property_terms` (
  `wbpt_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `wbpt_property_id` int(10) unsigned NOT NULL,
  `wbpt_term_in_lang_id` int(10) unsigned NOT NULL,
  PRIMARY KEY (`wbpt_id`),
  UNIQUE KEY `wbt_property_terms_term_in_lang_id_property_id` (`wbpt_term_in_lang_id`,`wbpt_property_id`),
  KEY `wbt_property_terms_property_id` (`wbpt_property_id`)
) ENGINE=InnoDB AUTO_INCREMENT=644 DEFAULT CHARSET=binary
```

<!-- table: wbt_text -->

#### 5. `wbt_text`

`BASE TABLE` · engine `InnoDB` · 2 columns

```sql
CREATE TABLE `wbt_text` (
  `wbx_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `wbx_text` varbinary(255) NOT NULL,
  PRIMARY KEY (`wbx_id`),
  UNIQUE KEY `wbt_text_text` (`wbx_text`)
) ENGINE=InnoDB AUTO_INCREMENT=1120 DEFAULT CHARSET=binary
```

<!-- table: wbt_text_in_lang -->

#### 6. `wbt_text_in_lang`

`BASE TABLE` · engine `InnoDB` · 3 columns

```sql
CREATE TABLE `wbt_text_in_lang` (
  `wbxl_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `wbxl_language` varbinary(20) NOT NULL,
  `wbxl_text_id` int(10) unsigned NOT NULL,
  PRIMARY KEY (`wbxl_id`),
  UNIQUE KEY `wbt_text_in_lang_text_id_text_id` (`wbxl_text_id`,`wbxl_language`),
  KEY `wbt_text_in_lang_language` (`wbxl_language`)
) ENGINE=InnoDB AUTO_INCREMENT=1144 DEFAULT CHARSET=binary
```

<!-- table: wbt_term_in_lang -->

#### 7. `wbt_term_in_lang`

`BASE TABLE` · engine `InnoDB` · 3 columns

```sql
CREATE TABLE `wbt_term_in_lang` (
  `wbtl_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `wbtl_type_id` int(10) unsigned NOT NULL,
  `wbtl_text_in_lang_id` int(10) unsigned NOT NULL,
  PRIMARY KEY (`wbtl_id`),
  UNIQUE KEY `wbt_term_in_lang_text_in_lang_id_lang_id` (`wbtl_text_in_lang_id`,`wbtl_type_id`),
  KEY `wbt_term_in_lang_type_id_text_in` (`wbtl_type_id`)
) ENGINE=InnoDB AUTO_INCREMENT=1145 DEFAULT CHARSET=binary
```

### The tables a claim adds

Two tables, and both hold one row per **distinct** target page of the entity's claims.
The unique key of `linktarget` is the part that matters: it is what finds a target that
already exists, so the writer writes no row for it and the capture shows no event.

`scripts/db-structure.sh -t "linktarget,pagelinks"`

<!-- table: linktarget -->

#### 1. `linktarget`

`BASE TABLE` · engine `InnoDB` · 3 columns

```sql
CREATE TABLE `linktarget` (
  `lt_id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
  `lt_namespace` int(11) NOT NULL,
  `lt_title` varbinary(255) NOT NULL,
  PRIMARY KEY (`lt_id`),
  UNIQUE KEY `lt_namespace_title` (`lt_namespace`,`lt_title`)
) ENGINE=InnoDB AUTO_INCREMENT=64 DEFAULT CHARSET=binary
```

<!-- table: pagelinks -->

#### 2. `pagelinks`

`BASE TABLE` · engine `InnoDB` · 3 columns

```sql
CREATE TABLE `pagelinks` (
  `pl_from` int(10) unsigned NOT NULL DEFAULT 0,
  `pl_target_id` bigint(20) unsigned NOT NULL,
  `pl_from_namespace` int(11) NOT NULL DEFAULT 0,
  PRIMARY KEY (`pl_from`,`pl_target_id`),
  KEY `pl_target_id` (`pl_target_id`,`pl_from`),
  KEY `pl_backlinks_namespace_target_id` (`pl_from_namespace`,`pl_target_id`,`pl_from`)
) ENGINE=InnoDB DEFAULT CHARSET=binary
```

`pl_from` is the page of the entity, `pl_target_id` is the `lt_id` of the target, and
`pl_from_namespace` is the entity's own namespace — 120 for the item of this capture. A
version that renames `linktarget` or folds it into `pagelinks` fails in step 2, on the
`-t` list, and not in the wiki.

## The helper the capture uses

The snippets above import one small module. It is in full here, so the worked example is
complete. Save it next to your script as `authenticator.py`, or read it as the recipe.
It takes its values from the environment: `MEDIAWIKI_API_URL`, `WIKIBASE_USERNAME`, and
`WIKIBASE_PASSWORD`. The capture itself needs no Python: `scripts/binlog-diff.sh` reads
`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME` and prints the row events.

### `authenticator.py` — the login

The write needs the user account, which has page edit rights. A development wiki usually
serves a self-signed certificate, and the login is the first request that fails on it.
Thus verification is off for each request of the process.

```python
# authenticator.py — the API login the reference write and the read-back both need.
#
# Values come from the environment: MEDIAWIKI_API_URL, WIKIBASE_USERNAME,
# WIKIBASE_PASSWORD. Export them, or run under a tool that loads .env.
import os

import requests
import urllib3
from wikibaseintegrator import wbi_login
from wikibaseintegrator.wbi_config import config

MEDIAWIKI_API_URL = os.environ.get(
    "MEDIAWIKI_API_URL", "https://wikibase.example/w/api.php"
)
WIKIBASE_USERNAME = os.environ.get("WIKIBASE_USERNAME", "admin")
WIKIBASE_PASSWORD = os.environ.get("WIKIBASE_PASSWORD", "")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_orig_send = requests.Session.send


def _insecure_send(self, request, **kwargs):
    kwargs["verify"] = False
    return _orig_send(self, request, **kwargs)


requests.Session.send = _insecure_send

config["MEDIAWIKI_API_URL"] = MEDIAWIKI_API_URL
config["USER_AGENT"] = (
    "WikibaseIntegratorBot/1.0 (mailto:you@example.org) WikibaseIntegrator/0.12"
)


def login_as_user():
    """Log in as the wiki user account, whose rights include page edits."""
    return wbi_login.Clientlogin(
        user=WIKIBASE_USERNAME,
        password=WIKIBASE_PASSWORD,
        mediawiki_api_url=MEDIAWIKI_API_URL,
        verify=False,
    )
```

A failed login raises an error here, and that is deliberate. With a wrong password there
is no capture to take. A `None` login fails later, further from the cause.

### The binlog reader is the shell script

**Both positions must come from the `pos` command.** If you calculate a position
yourself (for example, the current position minus 13000), it falls inside an event. The
decoder then reads the rest of that event as a length, and it stops with a packet or
truncation error. That error is not clear. `scripts/binlog-diff.sh` passes the positions
through unchanged, and `pos` prints the two numbers that the next `diff` needs.

The capture used to be a Python class in this file, with `get_binlog_pos()` and
`get_binlog_diff()` around `pymysql` and `mariadb-binlog`. It is gone: the shell script
does the same two things, it also finds the client and the decoder, it handles the
renamed position statement, and it trims the decoder's errors down to the
lines that name the failure. Keep one implementation of the capture, not two.

"""A qualifier on a claim, written through the API.

A qualifier is a snak of its own: it names a property, it holds a value, and the
wiki stores it inside the statement of the claim it qualifies. The same test as
``test/sql/test_item_qualifiers.py``, with the write going through the API instead of
FastWbi, so the two files have to produce the same results.

Every run creates new entities and never deletes them: Wikibase exposes no entity
deletion in its public API, so the instance accumulates one Q-id per write here.
"""

import re
from uuid import uuid4

import pytest
from wikibaseintegrator import datatypes
from wikibaseintegrator.models.qualifiers import Qualifiers
from wikibaseintegrator.wbi_exceptions import ModificationFailed

pytestmark = pytest.mark.integration

TOKEN = uuid4().hex[:8]

ITEM_ID = re.compile(r"^Q[1-9][0-9]*$")
SNAK_HASH = re.compile(r"^[0-9a-f]{40}$")

QUALIFIER = f"Item qualifier {TOKEN}"


def item_with_qualifier(wbi, string_property, value, qualifiers=None):
    """An unsaved item holding one string claim, with the qualifier it was given."""
    token = uuid4().hex[:8]
    new_item = wbi.item.new()
    new_item.labels.set("en", f"Qualifier item {token}")
    new_item.descriptions.set("en", f"A qualifier item {token}")
    new_item.claims.add(
        datatypes.String(prop_nr=string_property, value=value, qualifiers=qualifiers)
    )

    return new_item


@pytest.fixture(scope="module")
def written_item(wbi, string_property):
    qualifiers = Qualifiers()
    qualifiers.add(datatypes.String(prop_nr=string_property, value=QUALIFIER))

    return item_with_qualifier(
        wbi, string_property, f"A qualified value {TOKEN}", qualifiers
    ).write()


@pytest.fixture(scope="module")
def stored_item(wbi, written_item):
    """The item as the API serves it back, not as it was sent."""
    return wbi.item.get(written_item.id)


def test_write_assigns_a_new_item_id(written_item):
    assert ITEM_ID.match(written_item.id), written_item.id


def test_the_qualified_claim_round_trips(stored_item, string_property):
    claims = stored_item.claims.get(string_property)

    assert [claim.mainsnak.datavalue["value"] for claim in claims] == [
        f"A qualified value {TOKEN}"
    ]


def test_the_qualifier_round_trips(stored_item, string_property):
    """The qualifier keeps its property, its value, and the type the wiki serves."""
    claim = stored_item.claims.get(string_property)[0]
    qualifiers = claim.qualifiers.get(string_property)

    assert [snak.property_number for snak in qualifiers] == [string_property]
    assert [snak.datavalue["value"] for snak in qualifiers] == [QUALIFIER]
    assert [snak.datavalue["type"] for snak in qualifiers] == ["string"]


def test_the_qualifier_is_stored_inside_the_statement(stored_item, string_property):
    """A qualifier is not a claim of its own: the entity claims one property only."""
    assert list(stored_item.get_json()["claims"]) == [string_property]


def test_the_qualifier_hash_is_a_snak_hash(stored_item, string_property):
    """The wiki hashes every snak, and serves the hash back with the claim."""
    claim = stored_item.claims.get(string_property)[0]
    snak = claim.qualifiers.get(string_property)[0]

    assert SNAK_HASH.match(snak.hash), snak.hash


def test_a_qualifier_on_a_property_that_does_not_exist_is_refused(wbi, string_property):
    """The API names the property the wiki does not hold, and writes nothing."""
    qualifiers = Qualifiers()
    qualifiers.add(datatypes.String(prop_nr="P99999", value=QUALIFIER))

    with pytest.raises(ModificationFailed) as refusal:
        item_with_qualifier(
            wbi, string_property, f"A qualified value {TOKEN}", qualifiers
        ).write()

    assert refusal.value.code == "modification-failed"
    assert refusal.value.info == "Property [[Property:P99999|P99999]] not found"


def test_a_qualifier_of_the_wrong_type_is_refused(wbi, string_property, time_property):
    """A qualifier value must be of the type its property carries."""
    qualifiers = Qualifiers()
    qualifiers.add(datatypes.String(prop_nr=time_property, value=QUALIFIER))

    with pytest.raises(ModificationFailed) as refusal:
        item_with_qualifier(
            wbi, string_property, f"A qualified value {TOKEN}", qualifiers
        ).write()

    assert refusal.value.info == "Bad value type string, expected time"


def test_a_qualifier_naming_an_item_that_does_not_exist_is_refused(
    wbi, string_property, item_property
):
    """An entity-valued qualifier must name an entity the wiki holds."""
    qualifiers = Qualifiers()
    qualifiers.add(datatypes.Item(prop_nr=item_property, value="Q99999999"))

    with pytest.raises(ModificationFailed) as refusal:
        item_with_qualifier(
            wbi, string_property, f"A qualified value {TOKEN}", qualifiers
        ).write()

    assert refusal.value.info == "[[Item:Q99999999|Q99999999]] not found"

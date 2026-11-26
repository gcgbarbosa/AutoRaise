"""References on a claim, written through the API.

A reference is a list of snaks: it names properties of its own, it holds a hash of
its own, and the wiki stores it inside the statement of the claim it documents. The
same test as ``test/sql/test_item_references.py``, with the write going through the
API instead of FastWbi, so the two files have to produce the same results.

Every run creates new entities and never deletes them: Wikibase exposes no entity
deletion in its public API, so the instance accumulates one Q-id per write here.
"""

import re
from uuid import uuid4

import pytest
from wikibaseintegrator import datatypes
from wikibaseintegrator.models.references import Reference, References
from wikibaseintegrator.wbi_exceptions import ModificationFailed

pytestmark = pytest.mark.integration

TOKEN = uuid4().hex[:8]

ITEM_ID = re.compile(r"^Q[1-9][0-9]*$")
SNAK_HASH = re.compile(r"^[0-9a-f]{40}$")

TEXT_REFERENCE = f"Item string reference {TOKEN}"
TIME_REFERENCE = "+2020-01-01T00:00:00Z"


def reference_of(*snaks) -> Reference:
    """A reference holding the snaks that were given."""
    reference = Reference()
    for snak in snaks:
        reference.add(snak)

    return reference


def item_with_references(wbi, string_property, value, references=None):
    """An unsaved item holding one string claim, with the references it was given."""
    token = uuid4().hex[:8]
    new_item = wbi.item.new()
    new_item.labels.set("en", f"Reference item {token}")
    new_item.descriptions.set("en", f"A reference item {token}")
    new_item.claims.add(
        datatypes.String(prop_nr=string_property, value=value, references=references)
    )

    return new_item


@pytest.fixture(scope="module")
def written_item(wbi, string_property, time_property):
    references = References()
    references.add(
        reference_of(datatypes.String(prop_nr=string_property, value=TEXT_REFERENCE))
    )
    references.add(reference_of(datatypes.Time(prop_nr=time_property, time=TIME_REFERENCE)))

    return item_with_references(
        wbi, string_property, f"A documented value {TOKEN}", references
    ).write()


@pytest.fixture(scope="module")
def stored_item(wbi, written_item):
    """The item as the API serves it back, not as it was sent."""
    return wbi.item.get(written_item.id)


def test_write_assigns_a_new_item_id(written_item):
    assert ITEM_ID.match(written_item.id), written_item.id


def test_the_documented_claim_round_trips(stored_item, string_property):
    claims = stored_item.claims.get(string_property)

    assert [claim.mainsnak.datavalue["value"] for claim in claims] == [
        f"A documented value {TOKEN}"
    ]


def test_both_references_round_trip_in_order(stored_item, string_property):
    claim = stored_item.claims.get(string_property)[0]
    references = claim.references.references

    assert len(references) == 2
    assert [
        snak.datavalue["value"] for snak in references[0].snaks.get(string_property)
    ] == [TEXT_REFERENCE]


def test_a_reference_holds_the_property_of_its_own_snak(
    stored_item, string_property, time_property
):
    """The second reference documents the claim with another property."""
    claim = stored_item.claims.get(string_property)[0]
    reference = claim.references.references[1]
    snak = reference.snaks.get(time_property)[0]

    assert snak.property_number == time_property
    assert snak.datavalue["type"] == "time"


def test_every_reference_and_snak_carries_a_hash(stored_item, string_property):
    """The wiki hashes each snak and each reference, and serves both back."""
    claim = stored_item.claims.get(string_property)[0]
    references = claim.references.references
    hashes = {reference.hash for reference in references}

    assert len(hashes) == 2, "two references must not share a hash"
    for reference in references:
        assert SNAK_HASH.match(reference.hash), reference.hash
        for snaks in reference.snaks.snaks.values():
            for snak in snaks:
                assert SNAK_HASH.match(snak.hash), snak.hash


def test_a_reference_on_a_property_that_does_not_exist_is_refused(wbi, string_property):
    references = References()
    references.add(reference_of(datatypes.String(prop_nr="P99999", value=TEXT_REFERENCE)))

    with pytest.raises(ModificationFailed) as refusal:
        item_with_references(
            wbi, string_property, f"A documented value {TOKEN}", references
        ).write()

    assert refusal.value.info == "Property [[Property:P99999|P99999]] not found"


def test_a_reference_of_the_wrong_type_is_refused(wbi, string_property, time_property):
    """A reference value must be of the type its property carries."""
    references = References()
    references.add(
        reference_of(datatypes.String(prop_nr=time_property, value=TEXT_REFERENCE))
    )

    with pytest.raises(ModificationFailed) as refusal:
        item_with_references(
            wbi, string_property, f"A documented value {TOKEN}", references
        ).write()

    assert refusal.value.info == "Bad value type string, expected time"


def test_an_empty_reference_is_dropped(wbi, string_property):
    """A reference that holds no snak is stored nowhere, and the write succeeds."""
    references = References()
    references.add(Reference())
    references.add(
        reference_of(datatypes.String(prop_nr=string_property, value=TEXT_REFERENCE))
    )

    written = item_with_references(
        wbi, string_property, f"A documented value {TOKEN}", references
    ).write()
    claim = wbi.item.get(written.id).claims.get(string_property)[0]

    assert len(claim.references.references) == 1

"""A claim with a qualifier and two references, beside a second claim, over the API.

This is the shape a caller builds most often: one claim that says something, a
qualifier that says how, references that say on whose word, and a second claim on
another property. The same test as ``test/sql/test_item_claims.py``, with the write
going through the API instead of FastWbi, so the two files have to produce the same
results.

Every run creates a new item and never deletes it: Wikibase exposes no entity
deletion in its public API.
"""

import re
from uuid import uuid4

import pytest
from wikibaseintegrator import datatypes
from wikibaseintegrator.models.qualifiers import Qualifiers
from wikibaseintegrator.models.references import Reference, References
from wikibaseintegrator.wbi_enums import ActionIfExists, WikibaseDatatype

pytestmark = pytest.mark.integration

TOKEN = uuid4().hex[:8]

ITEM_ID = re.compile(r"^Q[1-9][0-9]*$")

CLAIM_VALUE = f"A String property {TOKEN}"
QUALIFIER = f"Item qualifier {TOKEN}"
REFERENCE_VALUES = (
    f"Item string reference {TOKEN}",
    f"Another item string reference {TOKEN}",
)


@pytest.fixture(scope="module")
def written_item(wbi, string_property, qualifier_property, time_property):
    """One claim with a qualifier and two references, and a time claim beside it."""
    qualifiers = Qualifiers()
    qualifiers.add(datatypes.String(prop_nr=qualifier_property, value=QUALIFIER))

    references = References()
    for value in REFERENCE_VALUES:
        reference = Reference()
        reference.add(datatypes.String(prop_nr=qualifier_property, value=value))
        references.add(reference)

    new_item = wbi.item.new()
    new_item.labels.set("en", f"Claimed item {TOKEN}")
    new_item.descriptions.set("en", f"A claimed item {TOKEN}")
    new_item.claims.add(
        datatypes.String(
            prop_nr=string_property,
            value=CLAIM_VALUE,
            qualifiers=qualifiers,
            references=references,
        )
    )
    new_item.claims.add(datatypes.Time(prop_nr=time_property, time="now"))

    return new_item.write()


@pytest.fixture(scope="module")
def stored_item(wbi, written_item):
    """The item as the API serves it back, not as it was sent."""
    return wbi.item.get(written_item.id)


def test_write_assigns_a_new_item_id(written_item):
    assert ITEM_ID.match(written_item.id), written_item.id


def test_the_item_holds_both_claims(stored_item, string_property, time_property):
    """The claims are keyed by property, in the order they were added."""
    assert list(stored_item.get_json()["claims"]) == [string_property, time_property]


def test_the_first_claim_round_trips(stored_item, string_property):
    claims = stored_item.claims.get(string_property)

    assert [claim.mainsnak.datavalue["value"] for claim in claims] == [CLAIM_VALUE]


def test_the_qualifier_round_trips(stored_item, string_property, qualifier_property):
    claim = stored_item.claims.get(string_property)[0]
    qualifiers = claim.qualifiers.get(qualifier_property)

    assert [snak.datavalue["value"] for snak in qualifiers] == [QUALIFIER]


def test_both_references_round_trip_in_order(
    stored_item, string_property, qualifier_property
):
    claim = stored_item.claims.get(string_property)[0]
    references = claim.references.references

    assert len(references) == 2
    assert [
        snak.datavalue["value"]
        for reference in references
        for snak in reference.snaks.get(qualifier_property)
    ] == list(REFERENCE_VALUES)


def test_the_time_claim_round_trips(stored_item, time_property):
    claim = stored_item.claims.get(time_property)[0]
    value = claim.mainsnak.datavalue

    assert value["type"] == "time"
    assert value["value"]["precision"] == 11


@pytest.fixture(scope="module")
def written_property(wbi, string_property):
    """A property of its own that carries a claim, as a property may."""
    new_property = wbi.property.new()
    new_property.datatype = WikibaseDatatype.STRING
    new_property.labels.set("en", f"Claimed property {TOKEN}")
    new_property.descriptions.set("en", f"A claimed property {TOKEN}")
    new_property.claims.add(
        datatypes.String(prop_nr=string_property, value=CLAIM_VALUE)
    )

    return new_property.write()


def test_a_property_can_hold_a_claim(wbi, written_property, string_property):
    """A claim is not an item-only shape: a property carries one the same way."""
    stored = wbi.property.get(written_property.id)
    claims = stored.claims.get(string_property)

    assert [claim.mainsnak.datavalue["value"] for claim in claims] == [CLAIM_VALUE]


def test_one_property_can_hold_two_claims(wbi, string_property):
    """Two statements on one property stay two claims, in the order they were added.

    ``Claims.add`` replaces a claim on the property it already holds unless the
    caller asks for an append, so the second claim has to ask.
    """
    token = uuid4().hex[:8]
    new_item = wbi.item.new()
    new_item.labels.set("en", f"Two claims item {token}")
    new_item.descriptions.set("en", f"A two claims item {token}")
    for position in ("first", "second"):
        new_item.claims.add(
            datatypes.String(prop_nr=string_property, value=f"{position} {token}"),
            action_if_exists=ActionIfExists.FORCE_APPEND,
        )

    stored = wbi.item.get(new_item.write().id)
    claims = stored.claims.get(string_property)

    assert [claim.mainsnak.datavalue["value"] for claim in claims] == [
        f"first {token}",
        f"second {token}",
    ]

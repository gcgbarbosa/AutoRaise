"""Claims on an item, one per datatype, written through the API.

A claim is a statement about an item: it names a property, it holds a value of the
type that property carries, and the wiki stores it in the entity blob under the
property. The same test as ``test/sql/test_item_properties.py``, with the write going
through the API instead of FastWbi, so the two files have to produce the same results.

The datatypes below are the ones a claim of this instance can hold and both write
paths reproduce. Every run creates one item per datatype and never deletes it:
Wikibase exposes no entity deletion in its public API.
"""

import re
from uuid import uuid4

import pytest
from wikibaseintegrator import datatypes
from wikibaseintegrator.wbi_enums import WikibaseDatatype
from wikibaseintegrator.wbi_exceptions import ModificationFailed

pytestmark = pytest.mark.integration

ITEM_ID = re.compile(r"^Q[1-9][0-9]*$")

# The datavalue type the wiki stores for a datatype's claim, which the API serves back.
DATAVALUE_TYPE = {
    WikibaseDatatype.STRING: "string",
    WikibaseDatatype.EXTERNALID: "string",
    WikibaseDatatype.EDTF: "string",
    WikibaseDatatype.URL: "string",
    WikibaseDatatype.TIME: "time",
    WikibaseDatatype.QUANTITY: "quantity",
    WikibaseDatatype.MONOLINGUALTEXT: "monolingualtext",
    WikibaseDatatype.GLOBECOORDINATE: "globecoordinate",
    WikibaseDatatype.ITEM: "wikibase-entityid",
    WikibaseDatatype.PROPERTY: "wikibase-entityid",
}

DATATYPES = tuple(DATAVALUE_TYPE)


def claim_of(datatype, prop_nr, token, *, value_item, value_property):
    """One claim of the datatype, holding a value that fits it."""
    if datatype is WikibaseDatatype.ITEM:
        return datatypes.Item(prop_nr=prop_nr, value=value_item)
    if datatype is WikibaseDatatype.PROPERTY:
        return datatypes.Property(prop_nr=prop_nr, value=value_property)

    return {
        WikibaseDatatype.STRING: datatypes.String(
            prop_nr=prop_nr, value=f"A string value {token}"
        ),
        WikibaseDatatype.EXTERNALID: datatypes.ExternalID(
            prop_nr=prop_nr, value=f"external-{token}"
        ),
        WikibaseDatatype.EDTF: datatypes.EDTF(prop_nr=prop_nr, value="2020-01-01"),
        WikibaseDatatype.URL: datatypes.URL(
            prop_nr=prop_nr, value=f"https://example.org/{token}"
        ),
        WikibaseDatatype.TIME: datatypes.Time(
            prop_nr=prop_nr, time="+2020-01-01T00:00:00Z"
        ),
        WikibaseDatatype.QUANTITY: datatypes.Quantity(
            prop_nr=prop_nr, amount=42, upper_bound=43, lower_bound=41, unit="1"
        ),
        WikibaseDatatype.MONOLINGUALTEXT: datatypes.MonolingualText(
            prop_nr=prop_nr, text=f"A text value {token}", language="en"
        ),
        WikibaseDatatype.GLOBECOORDINATE: datatypes.GlobeCoordinate(
            prop_nr=prop_nr,
            latitude=51.05,
            longitude=3.72,
            precision=0.01,
            globe="http://www.wikidata.org/entity/Q2",
        ),
    }[datatype]


def expected_value(datatype, token, *, value_item, value_property):
    """The datavalue the API serves back for the claim above."""
    if datatype in (WikibaseDatatype.ITEM, WikibaseDatatype.PROPERTY):
        return {"id": value_item if datatype is WikibaseDatatype.ITEM else value_property}

    return {
        WikibaseDatatype.STRING: f"A string value {token}",
        WikibaseDatatype.EXTERNALID: f"external-{token}",
        WikibaseDatatype.EDTF: "2020-01-01",
        WikibaseDatatype.URL: f"https://example.org/{token}",
        WikibaseDatatype.TIME: {
            "time": "+2020-01-01T00:00:00Z",
            "timezone": 0,
            "before": 0,
            "after": 0,
            "precision": 11,
            "calendarmodel": "http://www.wikidata.org/entity/Q1985727",
        },
        WikibaseDatatype.QUANTITY: {
            "amount": "+42",
            "unit": "1",
            "upperBound": "+43",
            "lowerBound": "+41",
        },
        WikibaseDatatype.MONOLINGUALTEXT: {
            "text": f"A text value {token}",
            "language": "en",
        },
        WikibaseDatatype.GLOBECOORDINATE: {
            "latitude": 51.05,
            "longitude": 3.72,
            "altitude": None,
            "precision": 0.01,
            "globe": "http://www.wikidata.org/entity/Q2",
        },
    }[datatype]


def item_with_claim(wbi, value):
    """An unsaved item holding one claim, with the value the claim was given."""
    token = uuid4().hex[:8]
    new_item = wbi.item.new()
    new_item.labels.set("en", f"Claim item {token}")
    new_item.descriptions.set("en", f"A claim item {token}")
    new_item.claims.add(value)

    return new_item


@pytest.mark.parametrize("datatype", DATATYPES, ids=lambda item: item.value)
def test_a_claim_of_each_datatype_round_trips(
    wbi, property_of, datatype, value_item, string_property
):
    """One item per datatype, with the claim the wiki stores and serves back."""
    token = uuid4().hex[:8]
    prop_nr = property_of(datatype)
    new_item = item_with_claim(
        wbi,
        claim_of(
            datatype,
            prop_nr,
            token,
            value_item=value_item,
            value_property=string_property,
        ),
    )

    written = new_item.write()
    stored = wbi.item.get(written.id)
    claims = stored.claims.get(prop_nr)

    assert ITEM_ID.match(written.id), written.id
    assert len(claims) == 1
    assert claims[0].mainsnak.property_number == prop_nr
    assert claims[0].mainsnak.datavalue["type"] == DATAVALUE_TYPE[datatype]

    value = claims[0].mainsnak.datavalue["value"]
    expected = expected_value(
        datatype, token, value_item=value_item, value_property=string_property
    )
    if datatype in (WikibaseDatatype.ITEM, WikibaseDatatype.PROPERTY):
        assert value["id"] == expected["id"]
        assert value["entity-type"] == datatype.value.removeprefix("wikibase-")
    else:
        assert value == expected


def test_a_claim_on_a_property_that_does_not_exist_is_refused(wbi):
    """The API names the property the wiki does not hold, and writes nothing."""
    new_item = item_with_claim(
        wbi, datatypes.String(prop_nr="P99999", value=f"A value {uuid4().hex[:8]}")
    )

    with pytest.raises(ModificationFailed) as refusal:
        new_item.write()

    assert refusal.value.info == "Property [[Property:P99999|P99999]] not found"


def test_a_claim_naming_an_item_that_does_not_exist_is_refused(wbi, item_property):
    """An entity-valued claim must name an entity the wiki holds."""
    new_item = item_with_claim(
        wbi, datatypes.Item(prop_nr=item_property, value="Q99999999")
    )

    with pytest.raises(ModificationFailed) as refusal:
        new_item.write()

    assert refusal.value.info == "[[Item:Q99999999|Q99999999]] not found"


def test_a_claim_of_the_wrong_type_is_refused(wbi, time_property):
    """A claim value must be of the type its property carries."""
    new_item = item_with_claim(
        wbi, datatypes.String(prop_nr=time_property, value=f"A value {uuid4().hex[:8]}")
    )

    with pytest.raises(ModificationFailed) as refusal:
        new_item.write()

    assert refusal.value.info == "Bad value type string, expected time"

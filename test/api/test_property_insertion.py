"""Round-trip test for new properties against a live Wikibase instance.

The test writes to the instance in ``arw.settings.settings.mediawiki_api_url``, so
it needs the stack to be up and the credentials to be valid.

Every run creates one property per datatype the instance accepts and never
deletes it: Wikibase exposes no entity deletion in its public API, so the
instance accumulates one P-id per run.

Two rules of this instance shape the test. A property label is unique across
properties in a language, description or not, so every label carries a per-run
token. And the datatype is fixed when the property is created, so each property
is written once, with the datatype it will keep.
"""

import re
from uuid import uuid4

import pytest
from wikibaseintegrator import WikibaseIntegrator
from wikibaseintegrator.wbi_enums import WikibaseDatatype
from wikibaseintegrator.wbi_exceptions import ModificationFailed, MWApiError

from arw.authenticator import WikibaseAuthenticator

pytestmark = pytest.mark.integration

TOKEN = uuid4().hex[:8]

PROPERTY_ID = re.compile(r"^P[1-9][0-9]*$")

# What this instance accepts: what its API took when each datatype was tried.
# ``edtf`` and ``localMedia`` come from the Wikibase EDTF and Wikibase Local
# Media extensions, which the siteinfo of this stack lists.
ACCEPTED_DATATYPES = (
    WikibaseDatatype.COMMONSMEDIA,
    WikibaseDatatype.EDTF,
    WikibaseDatatype.EXTERNALID,
    WikibaseDatatype.GEOSHAPE,
    WikibaseDatatype.GLOBECOORDINATE,
    WikibaseDatatype.ITEM,
    WikibaseDatatype.LOCALMEDIA,
    WikibaseDatatype.MONOLINGUALTEXT,
    WikibaseDatatype.PROPERTY,
    WikibaseDatatype.QUANTITY,
    WikibaseDatatype.STRING,
    WikibaseDatatype.TABULARDATA,
    WikibaseDatatype.TIME,
    WikibaseDatatype.URL,
)

# The rest of the enum, which the API answers ``param-illegal`` for. The
# WikibaseLexeme, Math and Score extensions behind the others are not loaded on
# this stack, and ``entity-schema`` is no property datatype at all. Both tuples
# are checked against the enum below, so a datatype the instance gains or loses
# fails a test here.
REFUSED_DATATYPES = (
    WikibaseDatatype.ENTITYSCHEMA,
    WikibaseDatatype.FORM,
    WikibaseDatatype.LEXEME,
    WikibaseDatatype.MATH,
    WikibaseDatatype.MUSICALNOTATION,
    WikibaseDatatype.SENSE,
)


@pytest.fixture(scope="module")
def wbi() -> WikibaseIntegrator:
    """Write paths need the user account, not the bot password."""
    login = WikibaseAuthenticator.login_as_user()
    assert login is not None, "login failed: check the API URL and the credentials"

    return WikibaseIntegrator(login=login)


def property_with(
    wbi: WikibaseIntegrator,
    datatype: WikibaseDatatype | None,
    label: str | None = None,
    description: str | None = None,
    language: str = "en",
):
    """An unsaved property, with the terms and the datatype that were given."""
    new_property = wbi.property.new()
    new_property.datatype = datatype

    if label is not None:
        new_property.labels.set(language, label)
    if description is not None:
        new_property.descriptions.set(language, description)

    return new_property


def written_id(written) -> str:
    """The id the API gave a property, checked against the shape of a P-id."""
    value = written.id
    assert value is not None, "the API returned a property without an id"
    assert PROPERTY_ID.match(value), value

    return value


def stored_property(wbi: WikibaseIntegrator, written):
    """The property as the API serves it back, not as it was sent."""
    return wbi.property.get(written_id(written))


def test_every_datatype_of_the_enum_is_covered():
    """A datatype the library adds must be placed in one of the two tuples."""
    assert set(ACCEPTED_DATATYPES) | set(REFUSED_DATATYPES) == set(WikibaseDatatype)
    assert not set(ACCEPTED_DATATYPES) & set(REFUSED_DATATYPES)


@pytest.mark.parametrize("datatype", ACCEPTED_DATATYPES, ids=lambda d: d.name)
def test_property_of_each_accepted_datatype_round_trips(wbi, datatype):
    """One property per datatype, with the datatype kept as it was written."""
    label = f"Property of datatype {datatype.value} {TOKEN}"
    description = f"A {datatype.value} property {TOKEN}"

    written = property_with(wbi, datatype, label, description).write()
    stored = stored_property(wbi, written)

    assert written_id(written) == stored.id
    assert stored.datatype == datatype
    assert stored.get_json()["datatype"] == datatype.value
    assert stored.labels.get("en") == label
    assert stored.descriptions.get("en") == description


@pytest.mark.parametrize("datatype", REFUSED_DATATYPES, ids=lambda d: d.name)
def test_refused_datatype_is_refused(wbi, datatype):
    """The API names the datatype it does not know, and writes nothing."""
    label = f"Property of datatype {datatype.value} {TOKEN}"

    with pytest.raises(MWApiError) as refusal:
        property_with(wbi, datatype, label, f"A {datatype.value} property {TOKEN}").write()

    assert refusal.value.code == "param-illegal"
    assert "wikibase-api-not-recognized-datatype" in refusal.value.messages_names


def test_missing_datatype_is_refused(wbi):
    """A property has no default datatype: the create fails without one."""
    with pytest.raises(MWApiError) as refusal:
        property_with(wbi, None, f"No datatype {TOKEN}", f"Without a datatype {TOKEN}").write()

    assert refusal.value.code == "param-illegal"
    assert "wikibase-api-not-recognized-datatype" in refusal.value.messages_names


def test_duplicate_label_is_refused(wbi):
    """A label repeats nowhere in a language, and the message names the holder."""
    label = f"Duplicate label {TOKEN}"

    first = property_with(
        wbi, WikibaseDatatype.STRING, label, f"First property {TOKEN}"
    ).write()

    with pytest.raises(MWApiError) as refusal:
        property_with(
            wbi, WikibaseDatatype.STRING, label, f"Another description {TOKEN}"
        ).write()

    assert refusal.value.code == "failed-save"
    assert "wikibase-validator-label-conflict" in refusal.value.messages_names
    assert refusal.value.get_conflicting_entity_ids == [first.id]
    assert set(refusal.value.get_languages) == {"en"}


def test_duplicate_label_and_description_in_another_language_is_allowed(wbi):
    """The uniqueness of a label reaches across properties, not across languages."""
    label = f"Other language {TOKEN}"
    description = f"Another language {TOKEN}"

    property_with(wbi, WikibaseDatatype.STRING, label, description, language="en").write()
    written = property_with(
        wbi, WikibaseDatatype.STRING, label, description, language="fr"
    ).write()
    stored = stored_property(wbi, written)

    assert stored.labels.get("fr") == label
    assert stored.descriptions.get("fr") == description


def test_label_equal_to_description_is_refused(wbi):
    """Wikibase refuses a language whose label and description are the same text."""
    text = f"Same text {TOKEN}"

    with pytest.raises(ModificationFailed) as refusal:
        property_with(wbi, WikibaseDatatype.STRING, text, text).write()

    assert refusal.value.code == "modification-failed"
    assert "wikibase-validator-label-equals-description" in refusal.value.messages_names
    assert "en" in refusal.value.info


@pytest.mark.parametrize(
    ("label", "description"),
    [
        pytest.param(None, None, id="no-terms"),
        pytest.param(f"Label only {TOKEN}", None, id="label-only"),
        pytest.param(None, f"Description only {TOKEN}", id="description-only"),
    ],
)
def test_terms_are_optional(wbi, label, description):
    """A property holds no label, no description, or either one on its own."""
    written = property_with(wbi, WikibaseDatatype.STRING, label, description).write()
    stored = stored_property(wbi, written)

    assert stored.labels.get("en") == label
    assert stored.descriptions.get("en") == description


def test_datatype_is_fixed_at_creation(wbi):
    """A second write carries another datatype and leaves the first one in place."""
    written = property_with(
        wbi, WikibaseDatatype.STRING, f"Fixed datatype {TOKEN}", f"Written once {TOKEN}"
    ).write()

    written.datatype = WikibaseDatatype.TIME
    rewritten = written.write()

    assert rewritten.datatype == WikibaseDatatype.STRING
    assert stored_property(wbi, written).datatype == WikibaseDatatype.STRING

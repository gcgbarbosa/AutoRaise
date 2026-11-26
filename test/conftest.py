"""The support entities the claim tests need, written once for a run.

A claim names a property, so every file below needs a property to claim on, and the
item-valued ones need a target item. The two suites share these fixtures, and both
write them through the API: only the entity under test differs between the two write
paths, which is what makes the two files comparable.
"""

import time
from uuid import uuid4

import pytest
from wikibaseintegrator import WikibaseIntegrator
from wikibaseintegrator.wbi_enums import WikibaseDatatype

from arw.authenticator import WikibaseAuthenticator

# A property label is unique across properties in a language, so every support
# property carries the token of the run.
TOKEN = uuid4().hex[:8]


def datatype_of(wbi, entity_id: str, timeout: float = 10.0):
    """The datatype the API serves for a property, once the wiki holds it.

    A capture of a property save put ``wb_property_info`` in a deferred update, 27 ms
    behind the response on this instance, and both write paths read that row to know
    the datatype of a claim's property. A claim written before the row lands is
    refused as a claim on a property that does not exist, so the fixture waits for
    the row the API serves the datatype from.
    """
    deadline = time.monotonic() + timeout
    while True:
        datatype = wbi.property.get(entity_id).datatype
        if datatype is not None:
            return datatype
        assert time.monotonic() < deadline, f"no datatype served for {entity_id}"
        time.sleep(0.01)


@pytest.fixture(scope="session")
def wbi() -> WikibaseIntegrator:
    """Write paths need the user account, not the bot password."""
    login = WikibaseAuthenticator.login_as_user()
    assert login is not None, "login failed: check the API URL and the credentials"

    return WikibaseIntegrator(login=login)


@pytest.fixture(scope="session")
def make_property(wbi):
    """A property of one datatype and one name, written once for the whole run.

    The datatype is fixed when a property is created, so one property serves every
    claim of that datatype. A test that needs a second property of the same datatype
    gives it a name of its own, which keeps its label apart from the first one.
    """
    written = {}

    def make(datatype: WikibaseDatatype, name: str) -> str:
        if (datatype, name) not in written:
            new_property = wbi.property.new()
            new_property.datatype = datatype
            new_property.labels.set(
                "en", f"Claim {name} property {datatype.value} {TOKEN}"
            )
            new_property.descriptions.set(
                "en", f"A claim {name} property of {datatype.value} {TOKEN}"
            )
            written[(datatype, name)] = new_property.write().id
            assert datatype_of(wbi, written[(datatype, name)]) == datatype

        return written[(datatype, name)]

    return make


@pytest.fixture(scope="session")
def property_of(make_property):
    """A property of one datatype, for the files that cover every datatype."""

    def make(datatype: WikibaseDatatype) -> str:
        return make_property(datatype, "main")

    return make


@pytest.fixture(scope="session")
def string_property(make_property) -> str:
    """The property the claim under test names, whose values are text."""
    return make_property(WikibaseDatatype.STRING, "main")


@pytest.fixture(scope="session")
def qualifier_property(make_property) -> str:
    """A second text property, for the qualifier and the references of a claim."""
    return make_property(WikibaseDatatype.STRING, "qualifier")


@pytest.fixture(scope="session")
def time_property(make_property) -> str:
    """The property whose claims hold a point in time."""
    return make_property(WikibaseDatatype.TIME, "main")


@pytest.fixture(scope="session")
def item_property(make_property) -> str:
    """The property whose claims name another item."""
    return make_property(WikibaseDatatype.ITEM, "main")


@pytest.fixture(scope="session")
def value_item(wbi) -> str:
    """The item an item-valued claim points at."""
    new_item = wbi.item.new()
    new_item.labels.set("en", f"Claim target item {TOKEN}")
    new_item.descriptions.set("en", f"A claim target item {TOKEN}")

    return new_item.write().id

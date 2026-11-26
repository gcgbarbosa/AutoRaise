"""Round-trip test for a new item against a live Wikibase instance.

The test writes to the instance in ``arw.settings.settings.mediawiki_api_url``,
so it needs the stack to be up and the credentials to be valid.

Every run creates a new item and never deletes it: Wikibase exposes no entity
deletion in its public API, so the instance accumulates one Q-id per run. The
values carry a per-run token because the instance rejects an item whose label
and description duplicate an existing one in the same language.
"""

import re
from uuid import uuid4

import pytest
from wikibaseintegrator import WikibaseIntegrator
from wikibaseintegrator.wbi_exceptions import ModificationFailed

from arw.authenticator import WikibaseAuthenticator

pytestmark = pytest.mark.integration

TOKEN = uuid4().hex[:8]

LABELS = {"en": f"New item {TOKEN}", "fr": f"Nouvel élément {TOKEN}"}
ALIASES = {"en": f"Item {TOKEN}", "fr": f"Élément {TOKEN}"}
DESCRIPTIONS = {
    "en": f"A freshly created element {TOKEN}",
    "fr": f"Un élément fraichement créé {TOKEN}",
}

ITEM_ID = re.compile(r"^Q[1-9][0-9]*$")


@pytest.fixture(scope="module")
def wbi() -> WikibaseIntegrator:
    """Write paths need the user account, not the bot password."""
    login = WikibaseAuthenticator.login_as_user()
    assert login is not None, "login failed: check the API URL and the credentials"

    return WikibaseIntegrator(login=login)


@pytest.fixture(scope="module")
def written_item(wbi):
    new_item = wbi.item.new()

    for language, value in LABELS.items():
        new_item.labels.set(language, value)
    for language, value in ALIASES.items():
        new_item.aliases.set(language, value)
    for language, value in DESCRIPTIONS.items():
        new_item.descriptions.set(language, value)

    return new_item.write()


@pytest.fixture(scope="module")
def stored_item(wbi, written_item):
    """The item as the API serves it back, not as it was sent."""
    return wbi.item.get(written_item.id)


def test_write_assigns_a_new_item_id(written_item):
    assert ITEM_ID.match(written_item.id), written_item.id


def test_labels_round_trip(stored_item):
    for language, value in LABELS.items():
        assert stored_item.labels.get(language) == value


def test_aliases_round_trip(stored_item):
    for language, value in ALIASES.items():
        stored_aliases = stored_item.aliases.get(language)

        assert [alias.value for alias in stored_aliases] == [value]


def test_descriptions_round_trip(stored_item):
    for language, value in DESCRIPTIONS.items():
        assert stored_item.descriptions.get(language) == value


def item_with(wbi: WikibaseIntegrator, label: str, description: str, language: str = "en"):
    """A new item with the two terms, written through the API."""
    new_item = wbi.item.new()
    new_item.labels.set(language, label)
    new_item.descriptions.set(language, description)

    return new_item.write()


def test_duplicate_label_and_description_is_refused(wbi):
    """A label and description pair is unique, and the message names the item."""
    token = uuid4().hex[:8]
    label = f"Duplicate pair {token}"
    description = f"A duplicate pair {token}"

    reference = item_with(wbi, label, description)

    with pytest.raises(ModificationFailed) as refusal:
        item_with(wbi, label, description)

    assert refusal.value.code == "modification-failed"
    conflict = next(
        message
        for message in refusal.value.messages
        if message["name"] == "wikibase-validator-label-with-description-conflict"
    )
    assert conflict["parameters"] == [
        label,
        "en",
        f"[[Item:{reference.id}|{reference.id}]]",
    ]


def test_duplicate_label_with_another_description_is_allowed(wbi):
    """Only the pair is unique: a label repeats while the description differs."""
    token = uuid4().hex[:8]
    label = f"Repeated label {token}"

    item_with(wbi, label, f"A first description {token}")
    second = item_with(wbi, label, f"A second description {token}")

    assert ITEM_ID.match(second.id), second.id


def test_label_equal_to_description_is_refused(wbi):
    """Wikibase refuses a language whose label and description are the same text."""
    text = f"Same text {uuid4().hex[:8]}"

    with pytest.raises(ModificationFailed) as refusal:
        item_with(wbi, text, text)

    assert refusal.value.code == "modification-failed"
    assert "wikibase-validator-label-equals-description" in refusal.value.messages_names

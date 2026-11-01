"""Tests for the get_user_level action that scripts call."""

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_ADDRESS_AS,
    CONF_ENTITIES,
    CONF_THIRD_PERSON_REFERENCE,
    CONF_TOOL_TYPE,
    CONF_USER_ID,
    DOMAIN,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_DEVICE,
    TOOL_TYPE_PERSON,
)

SERVICE = "get_user_level"


def _speaker(user, address_as="", third_person=""):
    return ConfigSubentryData(
        subentry_type=SUBENTRY_SPEAKER,
        title=user.name,
        unique_id=user.id,
        data={
            CONF_USER_ID: user.id,
            CONF_ADDRESS_AS: address_as,
            CONF_THIRD_PERSON_REFERENCE: third_person,
            CONF_ENTITIES: [],
        },
    )


@pytest.fixture
async def users(hass: HomeAssistant):
    admin = await hass.auth.async_create_user(
        "Alex Example", group_ids=["system-admin"]
    )
    member = await hass.auth.async_create_user(
        "Sam Sample", group_ids=["system-users"]
    )
    outsider = await hass.auth.async_create_user(
        "Robin Visitor", group_ids=["system-admin"]
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={},
        subentries_data=[
            _speaker(admin, "Boss", "The manager"),
            _speaker(member, "Mum"),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return {"admin": admin, "member": member, "outsider": outsider}


async def call(hass: HomeAssistant, data=None, user=None):
    return await hass.services.async_call(
        DOMAIN,
        SERVICE,
        data or {},
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id) if user else Context(),
    )


@pytest.mark.parametrize("who", ["Alex", "alex", "Boss", "The manager"])
async def test_person_found_by_name_address_form_or_third_person(
    hass, users, who
) -> None:
    result = await call(hass, {"person": who})
    assert result["found"] is True
    assert result["level"] == "Administrator"
    assert result["is_admin"] is True
    assert result["configured"] is True
    assert result["user_id"] == users["admin"].id
    assert result["name"] == "Alex"
    assert result["address_as"] == "Boss"


async def test_non_admin_person_is_a_user(hass, users) -> None:
    result = await call(hass, {"person": "Mum"})
    assert (result["level"], result["is_admin"]) == ("User", False)
    assert result["address_as"] == "Mum"


@pytest.mark.parametrize("who", ["Nobody", "The manager's cat", ""])
async def test_unknown_person_is_never_an_administrator(hass, users, who) -> None:
    result = await call(hass, {"person": who}) if who else await call(hass)
    assert result["found"] is False
    assert result["is_admin"] is False
    assert result["level"] is None
    assert result["address_as"] == "Unknown Person"


async def test_unknown_person_reason(hass, users) -> None:
    result = await call(hass, {"person": "Nobody"})
    assert result["reason"] == "unknown_person"


async def test_ambiguous_person_is_not_guessed(hass: HomeAssistant) -> None:
    first = await hass.auth.async_create_user("Pat One", group_ids=["system-admin"])
    second = await hass.auth.async_create_user("Pat Two", group_ids=["system-users"])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        subentries_data=[_speaker(first), _speaker(second)],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    result = await call(hass, {"person": "Pat"})
    assert result["found"] is False
    assert result["is_admin"] is False
    assert result["reason"] == "ambiguous_person"
    assert result["address_as"] == "Unknown Person"


async def test_person_and_user_id_together_is_an_error(hass, users) -> None:
    with pytest.raises(ServiceValidationError):
        await call(hass, {"person": "Alex", "user_id": users["admin"].id})


async def test_user_id_of_a_configured_person(hass, users) -> None:
    result = await call(hass, {"user_id": users["member"].id})
    assert result["found"] is True
    assert result["configured"] is True
    assert result["level"] == "User"
    assert result["address_as"] == "Mum"


async def test_user_id_of_an_account_that_is_not_a_configured_person(
    hass, users
) -> None:
    result = await call(hass, {"user_id": users["outsider"].id})
    assert result["found"] is True
    assert result["configured"] is False
    assert result["level"] == "Administrator"
    assert result["name"] == "Robin"
    assert result["address_as"] == "Unknown Person"


async def test_unknown_user_id(hass, users) -> None:
    result = await call(hass, {"user_id": "no-such-user"})
    assert result["found"] is False
    assert result["is_admin"] is False
    assert result["reason"] == "unknown_user"
    assert result["address_as"] == "Unknown Person"


async def test_defaults_to_the_user_who_started_the_script(hass, users) -> None:
    admin = await call(hass, user=users["admin"])
    member = await call(hass, user=users["member"])
    assert admin["is_admin"] is True and admin["name"] == "Alex"
    assert member["is_admin"] is False and member["name"] == "Sam"


async def test_no_user_in_context_is_not_found(hass, users) -> None:
    result = await call(hass)
    assert result["found"] is False
    assert result["reason"] == "no_user"
    assert result["is_admin"] is False
    assert result["address_as"] == "Unknown Person"


async def test_only_first_names_are_returned(hass, users) -> None:
    results = [
        await call(hass, {"person": "Alex"}),
        await call(hass, {"user_id": users["outsider"].id}),
    ]
    for result in results:
        text = str(result)
        assert "Example" not in text and "Visitor" not in text


async def test_responds_without_any_configured_people(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_TOOL_TYPE: TOOL_TYPE_DEVICE})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    result = await call(hass, {"person": "Alex"})
    assert result["found"] is False
    assert result["is_admin"] is False


async def _unknown_option_setup(hass: HomeAssistant, options: dict):
    member = await hass.auth.async_create_user("Sam Sample", group_ids=["system-users"])
    stranger = await hass.auth.async_create_user("Robin Visitor", group_ids=[])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options=options,
        subentries_data=[_speaker(member, "Mum")],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    return member, stranger


async def test_unknown_people_use_the_configured_unknown_address_form(
    hass: HomeAssistant,
) -> None:
    member, stranger = await _unknown_option_setup(
        hass, {"unknown_address_as": "Stranger"}
    )
    results = {
        "unknown_person": await call(hass, {"person": "Nobody"}),
        "unknown_user": await call(hass, {"user_id": "no-such-user"}),
        "no_user": await call(hass),
        "not_configured": await call(hass, {"user_id": stranger.id}),
    }
    for name, result in results.items():
        assert result["address_as"] == "Stranger", name
    assert results["not_configured"]["configured"] is False
    assert results["not_configured"]["name"] == "Robin"
    # A configured person keeps their own address form.
    assert (await call(hass, {"person": "Sam"}))["address_as"] == "Mum"


async def test_unknown_address_form_reads_the_legacy_option(
    hass: HomeAssistant,
) -> None:
    await _unknown_option_setup(hass, {"unknown_title": "Infiltrator"})
    result = await call(hass, {"person": "Nobody"})
    assert result["address_as"] == "Infiltrator"

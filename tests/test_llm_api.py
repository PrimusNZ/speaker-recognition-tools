"""End-to-end tests of the injected prompt through the registered LLM APIs."""

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_REFUSAL_LINES,
    CONF_TITLE,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_TITLE,
    CONF_USER_ID,
    DOMAIN,
    PERSON_API_ID,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
)
from homeassistant.config_entries import ConfigSubentryData


async def _setup(hass: HomeAssistant, deny: bool = False):
    james = await hass.auth.async_create_user("James", group_ids=["system-users"])
    sarah = await hass.auth.async_create_user("Sarah", group_ids=["system-users"])
    hass.states.async_set("calendar.james", "off", {"friendly_name": "James Calendar"})
    hass.states.async_set("calendar.sarah", "off", {"friendly_name": "Sarah Calendar"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={
            CONF_UNKNOWN_TITLE: "Infiltrator",
            CONF_DENY_UNKNOWN: deny,
            CONF_REFUSAL_LINES: "No.",
        },
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="James: Dad",
                unique_id=james.id,
                data={
                    CONF_USER_ID: james.id,
                    CONF_TITLE: "Dad",
                    CONF_ENTITIES: ["calendar.james"],
                },
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Sarah: Mum",
                unique_id=sarah.id,
                data={
                    CONF_USER_ID: sarah.id,
                    CONF_TITLE: "Mum",
                    CONF_ENTITIES: ["calendar.sarah", "calendar.gone"],
                },
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return james


async def _prompt(hass: HomeAssistant, user_id: str | None) -> str:
    context = llm.LLMContext(
        platform="test",
        context=Context(user_id=user_id),
        language="en",
        assistant="conversation",
        device_id=None,
    )
    instance = await llm.async_get_api(hass, PERSON_API_ID, context)
    return instance.api_prompt


async def test_prompt_assigns_entities_to_each_person(hass: HomeAssistant) -> None:
    james = await _setup(hass)
    text = await _prompt(hass, james.id)
    assert "You are Dad (James)." in text
    assert "## ENTITY MAPPINGS" in text
    assert "### James (Dad) [current speaker]\nCalendars:\n - calendar.james | James Calendar" in text
    assert (
        "### Sarah (Mum)\nCalendars:\n"
        " - calendar.sarah | Sarah Calendar\n"
        " - calendar.gone"
    ) in text


async def test_prompt_unknown_speaker_sees_people(hass: HomeAssistant) -> None:
    await _setup(hass)
    text = await _prompt(hass, None)
    assert "Address them as Infiltrator." in text
    assert "ENTITY MAPPINGS" not in text
    assert "calendar." not in text
    assert " - James (Dad)\n - Sarah (Mum)" in text


async def test_prompt_denied_speaker_sees_nothing(hass: HomeAssistant) -> None:
    await _setup(hass, deny=True)
    text = await _prompt(hass, None)
    assert "SECURITY LOCKDOWN" in text
    assert "calendar." not in text
    assert "Sarah" not in text


async def test_missing_title_falls_back_to_first_name(hass: HomeAssistant) -> None:
    tom = await hass.auth.async_create_user("Tom Jones", group_ids=["system-users"])
    ghost = await hass.auth.async_create_user("Ann", group_ids=["system-users"])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={CONF_UNKNOWN_TITLE: "Infiltrator", CONF_DENY_UNKNOWN: False},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Tom Jones",
                unique_id=tom.id,
                data={CONF_USER_ID: tom.id, CONF_TITLE: "", CONF_ENTITIES: []},
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Ann: Aunt",
                unique_id=ghost.id,
                data={CONF_USER_ID: ghost.id, CONF_TITLE: "Aunt"},
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    text = await _prompt(hass, tom.id)
    assert "Address them as Tom." in text
    assert 'answer "You are Tom."' in text
    assert "Jones" not in text
    assert "### Tom [current speaker]" in text
    assert "### Ann (Aunt)" in text
    unknown = await _prompt(hass, None)
    assert " - Ann (Aunt)\n - Tom" in unknown
    assert "Jones" not in unknown


async def test_only_first_names_reach_the_prompt(hass: HomeAssistant) -> None:
    james = await hass.auth.async_create_user("James Smith", group_ids=["system-users"])
    sarah = await hass.auth.async_create_user("Sarah Anne Jones", group_ids=["system-users"])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={CONF_UNKNOWN_TITLE: "Infiltrator", CONF_DENY_UNKNOWN: False},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="James Smith: Dad",
                unique_id=james.id,
                data={CONF_USER_ID: james.id, CONF_TITLE: "Dad", CONF_ENTITIES: []},
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Sarah Anne Jones: Mum",
                unique_id=sarah.id,
                data={CONF_USER_ID: sarah.id, CONF_TITLE: "Mum", CONF_ENTITIES: []},
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for user_id in (james.id, sarah.id, None):
        text = await _prompt(hass, user_id)
        assert "Smith" not in text and "Jones" not in text and "Anne" not in text
    assert 'answer "You are Dad (James)."' in await _prompt(hass, james.id)
    assert "### Sarah (Mum)" in await _prompt(hass, james.id)

"""End-to-end tests of the injected prompt through the registered LLM APIs."""

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_REFUSAL_LINES,
    CONF_TITLE,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_TITLE,
    CONF_USER_ID,
    DEVICE_API_ID,
    DEVICE_API_NAME,
    DOMAIN,
    PERSON_API_ID,
    PERSON_API_NAME,
    TOOL_TYPE_DEVICE,
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
            CONF_UNKNOWN_TITLE: "Unknown Person",
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


async def _instance(
    hass: HomeAssistant,
    user_id: str | None,
    api_id: str = PERSON_API_ID,
    device_id: str | None = None,
) -> llm.APIInstance:
    context = llm.LLMContext(
        platform="test",
        context=Context(user_id=user_id),
        language="en",
        assistant="conversation",
        device_id=device_id,
    )
    return await llm.async_get_api(hass, api_id, context)


async def _prompt(hass: HomeAssistant, user_id: str | None) -> str:
    return (await _instance(hass, user_id)).api_prompt


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
    assert "Address them as Unknown Person." in text
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
        options={CONF_UNKNOWN_TITLE: "Unknown Person", CONF_DENY_UNKNOWN: False},
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
        options={CONF_UNKNOWN_TITLE: "Unknown Person", CONF_DENY_UNKNOWN: False},
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


async def test_person_api_tools_only_for_recognised_speakers(hass: HomeAssistant) -> None:
    james = await _setup(hass)
    instance = await _instance(hass, james.id)
    assert [t.name for t in instance.tools] == [
        "get_calendar_events",
        "search_calendar_events",
        "check_calendar_availability",
        "create_calendar_event",
        "update_calendar_event",
        "delete_calendar_event",
        "get_person_location",
        "get_person_location_history",
    ]
    assert (await _instance(hass, None)).tools == []
    assert (await _instance(hass, "no-such-user")).tools == []
    assert instance.api.name == PERSON_API_NAME
    assert any(a.id == PERSON_API_ID for a in llm.async_get_apis(hass))


async def test_person_api_reads_options_live(hass: HomeAssistant) -> None:
    await _setup(hass)
    assert "SECURITY LOCKDOWN" not in await _prompt(hass, None)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_DENY_UNKNOWN: True, CONF_REFUSAL_LINES: "Nope."},
    )
    text = await _prompt(hass, None)
    assert "SECURITY LOCKDOWN" in text
    assert '- "Nope."' in text


async def test_denied_speaker_gets_no_tools(hass: HomeAssistant) -> None:
    await _setup(hass, deny=True)
    stranger = await hass.auth.async_create_user("Eve", group_ids=["system-users"])
    assert (await _instance(hass, None)).tools == []
    assert (await _instance(hass, stranger.id)).tools == []


async def test_person_api_denies_user_who_is_not_listed(hass: HomeAssistant) -> None:
    await _setup(hass, deny=True)
    stranger = await hass.auth.async_create_user("Eve", group_ids=["system-users"])
    text = await _prompt(hass, stranger.id)
    assert "SECURITY LOCKDOWN" in text
    assert "Eve" not in text


async def test_person_api_default_refusal_lines_when_blank(hass: HomeAssistant) -> None:
    await _setup(hass, deny=True)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_REFUSAL_LINES: " \n \n"}
    )
    assert "Authorisation required." in await _prompt(hass, None)


async def test_person_api_ignores_unknown_user_id(hass: HomeAssistant) -> None:
    await _setup(hass)
    text = await _prompt(hass, "no-such-user-id")
    assert "Address them as Unknown Person." in text


async def _setup_device(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_TOOL_TYPE: TOOL_TYPE_DEVICE})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_device_api_without_device(hass: HomeAssistant) -> None:
    await _setup_device(hass)
    instance = await _instance(hass, None, DEVICE_API_ID)
    assert instance.tools == []
    assert instance.api.name == DEVICE_API_NAME
    assert instance.api_prompt.startswith("## SPEAKING DEVICE")
    assert "is not known" in instance.api_prompt


async def test_device_api_with_unregistered_device_id(hass: HomeAssistant) -> None:
    await _setup_device(hass)
    instance = await _instance(hass, None, DEVICE_API_ID, device_id="abc123")
    assert "id abc123." in instance.api_prompt


async def test_device_api_with_registered_device(hass: HomeAssistant) -> None:
    other = MockConfigEntry(domain="test")
    other.add_to_hass(hass)
    await _setup_device(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("test", "kitchen")},
        name="Kitchen Satellite",
    )
    instance = await _instance(hass, None, DEVICE_API_ID, device_id=device.id)
    assert f"id {device.id} (Kitchen Satellite)" in instance.api_prompt


async def test_device_api_does_not_register_person_api(hass: HomeAssistant) -> None:
    await _setup_device(hass)
    ids = {a.id for a in llm.async_get_apis(hass)}
    assert DEVICE_API_ID in ids
    assert PERSON_API_ID not in ids



async def test_device_api_includes_the_devices_area(hass: HomeAssistant) -> None:
    other = MockConfigEntry(domain="test")
    other.add_to_hass(hass)
    await _setup_device(hass)
    area = ar.async_get(hass).async_create("Lounge")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("test", "sat")},
        name="Lounge Satellite",
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    text = (await _instance(hass, None, DEVICE_API_ID, device_id=device.id)).api_prompt
    assert f"id {device.id} (Lounge Satellite)" in text
    assert 'so "here" and "this room" mean the Lounge.' in text


async def test_device_api_without_an_area(hass: HomeAssistant) -> None:
    other = MockConfigEntry(domain="test")
    other.add_to_hass(hass)
    await _setup_device(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("test", "x")}, name="Box"
    )
    text = (await _instance(hass, None, DEVICE_API_ID, device_id=device.id)).api_prompt
    assert "area" not in text

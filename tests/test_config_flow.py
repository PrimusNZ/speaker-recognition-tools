"""Tests for the config, options and subentry flows."""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_DENY_UNKNOWN,
    CONF_REFUSAL_LINES,
    CONF_TITLE,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_TITLE,
    CONF_USER_ID,
    DEFAULT_REFUSAL_LINES,
    DEFAULT_UNKNOWN_TITLE,
    DOMAIN,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_DEVICE,
    TOOL_TYPE_PERSON,
)


async def _add(hass: HomeAssistant, option: str):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["speaking_person", "speaking_device"]
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": option}
    )


async def test_add_speaking_person(hass: HomeAssistant) -> None:
    result = await _add(hass, "speaking_person")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Speaking Person"
    assert result["data"] == {CONF_TOOL_TYPE: TOOL_TYPE_PERSON}
    assert result["options"] == {
        CONF_UNKNOWN_TITLE: DEFAULT_UNKNOWN_TITLE,
        CONF_DENY_UNKNOWN: False,
        CONF_REFUSAL_LINES: DEFAULT_REFUSAL_LINES,
    }


async def test_add_speaking_device(hass: HomeAssistant) -> None:
    result = await _add(hass, "speaking_device")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Speaking Device"
    assert result["data"] == {CONF_TOOL_TYPE: TOOL_TYPE_DEVICE}


async def test_each_tool_only_once(hass: HomeAssistant) -> None:
    for option in ("speaking_person", "speaking_device"):
        assert (await _add(hass, option))["type"] is FlowResultType.CREATE_ENTRY
        result = await _add(hass, option)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"


async def _person_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={
            CONF_UNKNOWN_TITLE: DEFAULT_UNKNOWN_TITLE,
            CONF_DENY_UNKNOWN: False,
            CONF_REFUSAL_LINES: DEFAULT_REFUSAL_LINES,
        },
        unique_id=f"{DOMAIN}_{TOOL_TYPE_PERSON}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DENY_UNKNOWN: True,
            CONF_UNKNOWN_TITLE: "Guest",
            CONF_REFUSAL_LINES: "No.\nStill no.",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DENY_UNKNOWN] is True
    assert entry.options[CONF_UNKNOWN_TITLE] == "Guest"
    assert entry.options[CONF_REFUSAL_LINES] == "No.\nStill no."


async def test_options_flow_not_available_for_device(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_TOOL_TYPE: TOOL_TYPE_DEVICE})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_options"


async def test_subentry_types(hass: HomeAssistant) -> None:
    from custom_components.speaker_recognition_tools.config_flow import (
        SpeakerRecognitionToolsFlow,
    )

    person = await _person_entry(hass)
    assert SUBENTRY_SPEAKER in SpeakerRecognitionToolsFlow.async_get_supported_subentry_types(person)
    device = MockConfigEntry(domain=DOMAIN, data={CONF_TOOL_TYPE: TOOL_TYPE_DEVICE})
    assert SpeakerRecognitionToolsFlow.async_get_supported_subentry_types(device) == {}


async def _user(hass: HomeAssistant, name: str):
    return await hass.auth.async_create_user(name, group_ids=["system-users"])


async def _add_person(hass, entry, user_id, title):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SPEAKER), context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_USER_ID: user_id, CONF_TITLE: title}
    )


async def test_add_person(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    result = await _add_person(hass, entry, user.id, "  Dad  ")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "James: Dad"
    sub = next(iter(entry.subentries.values()))
    assert dict(sub.data) == {CONF_USER_ID: user.id, CONF_TITLE: "Dad"}


async def test_add_person_duplicate_user_rejected(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad")
    result = await _add_person(hass, entry, user.id, "Father")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_USER_ID: "already_configured"}
    assert len(entry.subentries) == 1


async def test_reconfigure_person_changes_title_only(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad")
    sub_id = next(iter(entry.subentries))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SPEAKER),
        context={"source": "reconfigure", "subentry_id": sub_id},
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_TITLE: "Father"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    sub = entry.subentries[sub_id]
    assert dict(sub.data) == {CONF_USER_ID: user.id, CONF_TITLE: "Father"}
    assert sub.title == "James: Father"

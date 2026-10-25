"""Tests for the config, options and subentry flows."""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_PRIVATE_ENTITIES,
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
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
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


async def _add_person(hass, entry, user_id, title=None, entities=None, private=None):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SPEAKER), context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_USER_ID: user_id}
        | ({CONF_TITLE: title} if title is not None else {})
        | ({CONF_ENTITIES: entities} if entities else {})
        | ({CONF_PRIVATE_ENTITIES: private} if private else {}),
    )
    if result.get("errors", {}).get("base") == "entity_warnings_acknowledge":
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {CONF_USER_ID: user_id}
            | ({CONF_TITLE: title} if title is not None else {})
            | ({CONF_ENTITIES: entities} if entities else {})
            | ({CONF_PRIVATE_ENTITIES: private} if private else {}),
        )
    return result


async def test_add_person(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    result = await _add_person(hass, entry, user.id, "  Dad  ")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "James: Dad (no entities)"
    sub = next(iter(entry.subentries.values()))
    assert dict(sub.data) == {
        CONF_USER_ID: user.id,
        CONF_TITLE: "Dad",
        CONF_ENTITIES: [],
        CONF_PRIVATE_ENTITIES: [],
    }


async def test_add_person_duplicate_user_rejected(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad")
    result = await _add_person(hass, entry, user.id, "Father")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_USER_ID: "already_configured"}
    assert len(entry.subentries) == 1


async def test_add_person_with_entities(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    entities = ["calendar.james", "device_tracker.james_phone"]
    result = await _add_person(hass, entry, user.id, "Dad", entities)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = next(iter(entry.subentries.values()))
    assert sub.data[CONF_ENTITIES] == entities
    assert result["title"] == "James: Dad (2 entities)"


async def test_list_label_counts_one_entity(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    result = await _add_person(hass, entry, user.id, "Dad", ["calendar.james"])
    assert result["title"] == "James: Dad (1 entity)"


async def _reconfigure(hass, entry, sub_id, data):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SPEAKER),
        context={"source": "reconfigure", "subentry_id": sub_id},
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], data)
    if result.get("errors", {}).get("base") == "entity_warnings_acknowledge":
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], data)
    return result


async def test_add_person_warns_about_stale_entity_before_saving(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SPEAKER), context={"source": "user"}
    )
    data = {CONF_USER_ID: user.id, CONF_TITLE: "Dad", CONF_ENTITIES: ["calendar.missing"]}
    result = await hass.config_entries.subentries.async_configure(flow["flow_id"], data)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "entity_warnings_acknowledge"
    assert "calendar.missing" in result["description_placeholders"]["entity_warnings"]
    assert not entry.subentries
    result = await hass.config_entries.subentries.async_configure(flow["flow_id"], data)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_add_person_warns_about_entity_assigned_to_someone_else(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    james = await _user(hass, "James")
    sarah = await _user(hass, "Sarah")
    await _add_person(hass, entry, james.id, "Dad", ["light.shared"])
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SPEAKER), context={"source": "user"}
    )
    data = {CONF_USER_ID: sarah.id, CONF_TITLE: "Mum", CONF_ENTITIES: ["light.shared"]}
    result = await hass.config_entries.subentries.async_configure(flow["flow_id"], data)
    assert result["type"] is FlowResultType.FORM
    assert "Also assigned to another person: light.shared" in result["description_placeholders"]["entity_warnings"]
    assert len(entry.subentries) == 1
    result = await hass.config_entries.subentries.async_configure(flow["flow_id"], data)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_preview_shows_generated_person_prompt(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad")
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "preview"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_USER_ID: user.id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "preview_result"
    assert "Address them as Dad." in result["description_placeholders"]["prompt"]


async def test_preview_shows_unknown_speaker_prompt(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad")
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "preview"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_USER_ID: "__unknown_speaker__"}
    )
    assert result["type"] is FlowResultType.FORM
    prompt = result["description_placeholders"]["prompt"]
    assert "Unknown Person" in prompt
    assert "PEOPLE" in prompt
    assert "Address them as Dad." not in prompt


async def test_reconfigure_person_changes_title_and_entities(
    hass: HomeAssistant,
) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad", ["calendar.james"])
    sub_id = next(iter(entry.subentries))
    result = await _reconfigure(
        hass,
        entry,
        sub_id,
        {CONF_TITLE: "Father", CONF_ENTITIES: ["calendar.james", "calendar.work"]},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    sub = entry.subentries[sub_id]
    assert dict(sub.data) == {
        CONF_USER_ID: user.id,
        CONF_TITLE: "Father",
        CONF_ENTITIES: ["calendar.james", "calendar.work"],
        CONF_PRIVATE_ENTITIES: [],
    }
    assert sub.title == "James: Father (2 entities)"


async def test_reconfigure_can_clear_entities(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad", ["calendar.james"])
    sub_id = next(iter(entry.subentries))
    await _reconfigure(hass, entry, sub_id, {CONF_TITLE: "Dad", CONF_ENTITIES: []})
    assert entry.subentries[sub_id].data[CONF_ENTITIES] == []


async def test_add_person_without_title(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James Smith")
    result = await _add_person(hass, entry, user.id)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "James Smith (no entities)"
    sub = next(iter(entry.subentries.values()))
    assert sub.data[CONF_TITLE] == ""


async def test_reconfigure_can_clear_title(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad")
    sub_id = next(iter(entry.subentries))
    await _reconfigure(hass, entry, sub_id, {CONF_ENTITIES: []})
    sub = entry.subentries[sub_id]
    assert sub.data[CONF_TITLE] == ""
    assert sub.title == "James (no entities)"


async def test_add_person_with_private_entities(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    result = await _add_person(
        hass,
        entry,
        user.id,
        "Dad",
        ["calendar.james", "calendar.work"],
        ["calendar.work"],
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "James: Dad (2 entities, 1 private)"
    sub = next(iter(entry.subentries.values()))
    assert sub.data[CONF_PRIVATE_ENTITIES] == ["calendar.work"]


async def test_private_entity_must_be_assigned(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    result = await _add_person(
        hass, entry, user.id, "Dad", ["calendar.james"], ["calendar.other"]
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PRIVATE_ENTITIES: "private_not_assigned"}
    assert not entry.subentries


async def test_reconfigure_private_entities(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad", ["calendar.a", "calendar.b"])
    sub_id = next(iter(entry.subentries))
    result = await _reconfigure(
        hass,
        entry,
        sub_id,
        {
            CONF_TITLE: "Dad",
            CONF_ENTITIES: ["calendar.a", "calendar.b"],
            CONF_PRIVATE_ENTITIES: ["calendar.b"],
        },
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[sub_id].data[CONF_PRIVATE_ENTITIES] == ["calendar.b"]
    assert entry.subentries[sub_id].title == "James: Dad (2 entities, 1 private)"


async def test_reconfigure_rejects_unassigned_private(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad", ["calendar.a"])
    sub_id = next(iter(entry.subentries))
    result = await _reconfigure(
        hass,
        entry,
        sub_id,
        {CONF_ENTITIES: ["calendar.a"], CONF_PRIVATE_ENTITIES: ["calendar.z"]},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PRIVATE_ENTITIES: "private_not_assigned"}

"""Tests for the config, options and subentry flows."""

import json
from pathlib import Path

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.config_flow import _prompt_preview_box
from custom_components.speaker_recognition_tools.const import (
    CONF_DENY_UNKNOWN,
    CONF_ENTITY_ALIASES,
    CONF_ENTITIES,
    CONF_PRIVATE_ENTITIES,
    CONF_LINK_ACTION_ENTITY,
    CONF_LINK_NAME,
    CONF_LINK_PRIVATE,
    CONF_LINK_STATE_ENTITY,
    CONF_REFUSAL_LINES,
    CONF_ADDRESS_AS,
    CONF_LEGACY_ADDRESS_AS,
    CONF_LEGACY_UNKNOWN_ADDRESS_AS,
    CONF_THIRD_PERSON_REFERENCE,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_ADDRESS_AS,
    CONF_USER_ID,
    DEFAULT_REFUSAL_LINES,
    DEFAULT_UNKNOWN_ADDRESS_AS,
    DOMAIN,
    SUBENTRY_PREVIEW,
    SUBENTRY_ENTITY_LINK,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_DEVICE,
    TOOL_TYPE_PERSON,
)


async def _add(hass: HomeAssistant, option: str):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [
        "speaking_person",
        "speaking_device",
        "preview_full",
    ]
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": option}
    )


async def test_add_speaking_person(hass: HomeAssistant) -> None:
    result = await _add(hass, "speaking_person")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Speaking Person"
    assert result["data"] == {CONF_TOOL_TYPE: TOOL_TYPE_PERSON}
    assert result["options"] == {
        CONF_UNKNOWN_ADDRESS_AS: DEFAULT_UNKNOWN_ADDRESS_AS,
        CONF_DENY_UNKNOWN: False,
        CONF_REFUSAL_LINES: DEFAULT_REFUSAL_LINES,
    }


async def test_add_speaking_device(hass: HomeAssistant) -> None:
    result = await _add(hass, "speaking_device")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Speaking Device"
    assert result["data"] == {CONF_TOOL_TYPE: TOOL_TYPE_DEVICE}


async def test_full_preview_available_before_adding_either_api(
    hass: HomeAssistant,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "preview_full"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "preview_full_result"
    prompt = result["description_placeholders"]["prompt"]
    assert prompt == ""
    assert "adds no prompt sections" in result["description_placeholders"]["note"]
    assert result["description_placeholders"]["disclaimer"] == ""


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
            CONF_UNKNOWN_ADDRESS_AS: DEFAULT_UNKNOWN_ADDRESS_AS,
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
    assert result["menu_options"] == ["settings", "preview"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DENY_UNKNOWN: True,
            CONF_UNKNOWN_ADDRESS_AS: "Guest",
            CONF_REFUSAL_LINES: "No.\nStill no.",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DENY_UNKNOWN] is True
    assert entry.options[CONF_UNKNOWN_ADDRESS_AS] == "Guest"
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
    types = SpeakerRecognitionToolsFlow.async_get_supported_subentry_types(person)
    assert SUBENTRY_SPEAKER in types
    assert SUBENTRY_ENTITY_LINK in types
    assert SUBENTRY_PREVIEW in types
    device = MockConfigEntry(domain=DOMAIN, data={CONF_TOOL_TYPE: TOOL_TYPE_DEVICE})
    assert SpeakerRecognitionToolsFlow.async_get_supported_subentry_types(device) == {}


async def test_integration_page_preview_works_without_person_subentries(
    hass: HomeAssistant,
) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PREVIEW),
        context={"source": "user", "user_id": user.id},
    )
    assert flow["type"] is FlowResultType.FORM
    assert flow["step_id"] == "user"
    prompt = flow["description_placeholders"]["prompt"]
    assert "## SPEAKING PERSON" in prompt
    assert "Unknown Person" in prompt
    assert "## SPEAKING DEVICE" not in prompt
    assert flow["description_placeholders"]["disclaimer"] == ""
    assert len(entry.subentries) == 0
    result = await hass.config_entries.subentries.async_configure(flow["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "preview_complete"
    assert len(entry.subentries) == 0


async def test_full_preview_omits_unconfigured_person_api(hass: HomeAssistant) -> None:
    await _add(hass, "speaking_device")
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "device-only-preview")},
        name="Example water heater",
    )
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "preview_full"}
    )
    prompt = result["description_placeholders"]["prompt"]
    assert "## SPEAKING PERSON" not in prompt
    assert "## SPEAKING DEVICE" in prompt
    assert "The device the speaker is using is not known." in prompt
    assert "Example water heater" not in prompt
    assert "No registered Assist satellite was found" in (
        result["description_placeholders"]["note"]
    )
    disclaimer = result["description_placeholders"]["disclaimer"]
    assert "example rendering" in disclaimer
    assert "randomly selected registered device" in disclaimer
    assert "example rendering" not in result["description_placeholders"]["prompt"]


async def _user(hass: HomeAssistant, name: str):
    return await hass.auth.async_create_user(name, group_ids=["system-users"])


async def _add_person(hass, entry, user_id, address_as=None, entities=None, private=None, third_person_reference=None, entity_aliases=None):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SPEAKER), context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_USER_ID: user_id}
        | ({CONF_ADDRESS_AS: address_as} if address_as is not None else {})
        | ({CONF_ENTITIES: entities} if entities else {})
        | ({CONF_PRIVATE_ENTITIES: private} if private else {})
        | ({CONF_ENTITY_ALIASES: entity_aliases} if entity_aliases is not None else {})
        | ({CONF_THIRD_PERSON_REFERENCE: third_person_reference} if third_person_reference else {}),
    )
    if result.get("errors", {}).get("base") == "entity_warnings_acknowledge":
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {CONF_USER_ID: user_id}
            | ({CONF_ADDRESS_AS: address_as} if address_as is not None else {})
            | ({CONF_ENTITIES: entities} if entities else {})
            | ({CONF_PRIVATE_ENTITIES: private} if private else {})
            | ({CONF_ENTITY_ALIASES: entity_aliases} if entity_aliases is not None else {})
            | ({CONF_THIRD_PERSON_REFERENCE: third_person_reference} if third_person_reference else {}),
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
        CONF_ADDRESS_AS: "Dad",
        CONF_ENTITIES: [],
        CONF_PRIVATE_ENTITIES: [],
    }


async def test_add_person_with_third_person_reference(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    result = await _add_person(hass, entry, user.id, "Dad", third_person_reference="The father")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = next(iter(entry.subentries.values()))
    assert sub.data[CONF_THIRD_PERSON_REFERENCE] == "The father"


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


async def test_add_linked_device_with_status_and_action_entities(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad")
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ENTITY_LINK), context={"source": "user"}
    )
    assert flow["type"] is FlowResultType.FORM
    assert flow["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(
        flow["flow_id"],
        {
            CONF_USER_ID: user.id,
            CONF_LINK_NAME: "Demo unit",
            CONF_LINK_STATE_ENTITY: "binary_sensor.demo_unit_status",
            CONF_LINK_ACTION_ENTITY: "button.demo_unit_action",
            CONF_LINK_PRIVATE: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"].startswith("Demo unit")
    subentry = next(
        sub for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_ENTITY_LINK
    )
    assert subentry.data == {
        CONF_USER_ID: user.id,
        CONF_LINK_NAME: "Demo unit",
        CONF_LINK_STATE_ENTITY: "binary_sensor.demo_unit_status",
        CONF_LINK_ACTION_ENTITY: "button.demo_unit_action",
        CONF_LINK_PRIVATE: False,
    }


async def test_add_person_with_entity_aliases(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    result = await _add_person(
        hass,
        entry,
        user.id,
        "Dad",
        ["calendar.james"],
        entity_aliases="calendar.james: work, appointments",
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = next(iter(entry.subentries.values()))
    assert sub.data[CONF_ENTITY_ALIASES] == {
        "calendar.james": ["work", "appointments"]
    }


async def test_entity_aliases_must_reference_an_assigned_entity(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SPEAKER), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        flow["flow_id"],
        {
            CONF_USER_ID: user.id,
            CONF_ENTITIES: ["calendar.james"],
            CONF_ENTITY_ALIASES: "calendar.work: work",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_ENTITY_ALIASES] == "invalid_entity_aliases"


async def test_reconfigure_person_entity_aliases(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad", ["calendar.james"])
    sub_id = next(iter(entry.subentries))
    result = await _reconfigure(
        hass,
        entry,
        sub_id,
        {
            CONF_ENTITIES: ["calendar.james"],
            CONF_ENTITY_ALIASES: "calendar.james: work",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries[sub_id].data[CONF_ENTITY_ALIASES] == {
        "calendar.james": ["work"]
    }


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
    data = {CONF_USER_ID: user.id, CONF_ADDRESS_AS: "Dad", CONF_ENTITIES: ["calendar.missing"]}
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
    data = {CONF_USER_ID: sarah.id, CONF_ADDRESS_AS: "Mum", CONF_ENTITIES: ["light.shared"]}
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


async def test_prompt_preview_descriptions_use_shaded_wrapping_boxes() -> None:
    translation_path = (
        Path(__file__).parent.parent
        / "custom_components/speaker_recognition_tools/translations/en.json"
    )
    translations = json.loads(translation_path.read_text())
    person_fields = translations["config_subentries"]["speaker"]["step"]["user"]["data"]
    person_descriptions = translations["config_subentries"]["speaker"]["step"]["user"]["data_description"]
    unknown_settings = translations["options"]["step"]["settings"]["data"]
    assert person_fields[CONF_ADDRESS_AS] == "Address as"
    assert person_fields[CONF_ENTITY_ALIASES] == "Entity aliases"
    assert "one line per assigned entity" in person_descriptions[CONF_ENTITY_ALIASES]
    assert CONF_LEGACY_ADDRESS_AS not in person_fields
    assert unknown_settings[CONF_UNKNOWN_ADDRESS_AS] == "Address as for unknown speakers"
    assert CONF_LEGACY_UNKNOWN_ADDRESS_AS not in unknown_settings
    preview_template = "{disclaimer}\n\nPrompt Preview:\n\n{prompt_box}\n\n{note}"
    assert (
        translations["config"]["step"]["preview_full_result"]["description"]
        == preview_template
    )
    assert (
        translations["config_subentries"]["full_prompt_preview"]["step"]["user"]["description"]
        == preview_template
    )
    assert translations["options"]["step"]["preview_result"]["description"] == (
        "Prompt Preview:\n\n{prompt_box}"
    )
    assert _prompt_preview_box("first line\n\n## ENTITY MAPPINGS\n<second & line>") == (
        '<ha-alert alert-type="info">first line<br><br>## ENTITY MAPPINGS<br>'
        "&lt;second &amp; line&gt;</ha-alert>"
    )


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


async def test_full_prompt_preview_uses_logged_in_account_and_sample_device(
    hass: HomeAssistant,
) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad")
    device_entry = await _add(hass, "speaking_device")
    assert device_entry["type"] is FlowResultType.CREATE_ENTRY
    device_config_entry = next(
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data[CONF_TOOL_TYPE] == TOOL_TYPE_DEVICE
    )
    area = ar.async_get(hass).async_create("Kitchen")
    device_registry = dr.async_get(hass)
    water_heater = device_registry.async_get_or_create(
        config_entry_id=device_config_entry.entry_id,
        identifiers={(DOMAIN, "preview-water-heater")},
        name="Water heater",
    )
    device_registry.async_update_device(water_heater.id, area_id=area.id)
    device = device_registry.async_get_or_create(
        config_entry_id=device_config_entry.entry_id,
        identifiers={(DOMAIN, "preview-device")},
        name="Kitchen speaker",
    )
    device_registry.async_update_device(device.id, area_id=area.id)
    er.async_get(hass).async_get_or_create(
        "assist_satellite",
        "test",
        "preview-satellite",
        device_id=device.id,
        suggested_object_id="preview_speaker",
    )

    flow = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER, "user_id": user.id},
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "preview_full"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "preview_full_result"
    prompt = result["description_placeholders"]["prompt"]
    assert "## SPEAKING PERSON" in prompt
    assert "Address them as Dad." in prompt
    assert "## SPEAKING DEVICE" in prompt
    assert f"id {device.id} (Kitchen speaker)" in prompt
    assert "Water heater" not in prompt
    assert "the Kitchen area" in prompt
    disclaimer = result["description_placeholders"]["disclaimer"]
    note = result["description_placeholders"]["note"]
    assert disclaimer.startswith("Disclaimer: This is an example rendering.")
    assert "randomly selected registered device" in disclaimer
    assert "example rendering" not in note
    assert "order they were added" in note


async def test_reconfigure_person_changes_address_as_and_entities(
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
        {CONF_ADDRESS_AS: "Father", CONF_ENTITIES: ["calendar.james", "calendar.work"]},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    sub = entry.subentries[sub_id]
    assert dict(sub.data) == {
        CONF_USER_ID: user.id,
        CONF_ADDRESS_AS: "Father",
        CONF_ENTITIES: ["calendar.james", "calendar.work"],
        CONF_PRIVATE_ENTITIES: [],
    }
    assert sub.title == "James: Father (2 entities)"


async def test_reconfigure_person_third_person_reference(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad")
    sub_id = next(iter(entry.subentries))
    await _reconfigure(hass, entry, sub_id, {
        CONF_ADDRESS_AS: "Dad",
        CONF_THIRD_PERSON_REFERENCE: "The father",
        CONF_ENTITIES: [],
    })
    assert entry.subentries[sub_id].data[CONF_THIRD_PERSON_REFERENCE] == "The father"


async def test_reconfigure_can_clear_entities(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad", ["calendar.james"])
    sub_id = next(iter(entry.subentries))
    await _reconfigure(hass, entry, sub_id, {CONF_ADDRESS_AS: "Dad", CONF_ENTITIES: []})
    assert entry.subentries[sub_id].data[CONF_ENTITIES] == []


async def test_add_person_without_address_as(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James Smith")
    result = await _add_person(hass, entry, user.id)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "James Smith (no entities)"
    sub = next(iter(entry.subentries.values()))
    assert sub.data[CONF_ADDRESS_AS] == ""


async def test_reconfigure_can_clear_address_as(hass: HomeAssistant) -> None:
    entry = await _person_entry(hass)
    user = await _user(hass, "James")
    await _add_person(hass, entry, user.id, "Dad")
    sub_id = next(iter(entry.subentries))
    await _reconfigure(hass, entry, sub_id, {CONF_ENTITIES: []})
    sub = entry.subentries[sub_id]
    assert sub.data[CONF_ADDRESS_AS] == ""
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
            CONF_ADDRESS_AS: "Dad",
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

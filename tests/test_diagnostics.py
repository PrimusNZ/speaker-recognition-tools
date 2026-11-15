"""Tests for the diagnostics download."""

from __future__ import annotations

import json

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_ADDRESS_AS,
    CONF_ALARM_ENTITY,
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_ENTITY_ALIASES,
    CONF_PRIVATE_ENTITIES,
    CONF_THIRD_PERSON_REFERENCE,
    CONF_TOOL_TYPE,
    CONF_USER_ID,
    CONF_WRAPPED_AGENT,
    DOMAIN,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
    TOOL_TYPE_WRAPPER,
)
from custom_components.speaker_recognition_tools.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def _entry(hass: HomeAssistant, tool_type: str, subentries=()):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: tool_type},
        options={}
        if tool_type == TOOL_TYPE_PERSON
        else {
            CONF_WRAPPED_AGENT: "conversation.agent",
            CONF_DENY_UNKNOWN: True,
            CONF_ALARM_ENTITY: "alarm_control_panel.home",
        },
        subentries_data=list(subentries),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_person_diagnostics_leave_out_names(hass: HomeAssistant) -> None:
    await hass.auth.async_create_user("Owner Account")  # the first user is the owner
    user = await hass.auth.async_create_user(
        "Robin Example", group_ids=["system-users"]
    )
    hass.states.async_set("calendar.shared", "off")
    hass.states.async_set("device_tracker.phone", "home", {"address": "1 Sample St"})
    entry = await _entry(
        hass,
        TOOL_TYPE_PERSON,
        [
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Robin",
                unique_id=user.id,
                data={
                    CONF_USER_ID: user.id,
                    CONF_ADDRESS_AS: "Captain",
                    CONF_THIRD_PERSON_REFERENCE: "The captain",
                    CONF_ENTITIES: [
                        "calendar.shared",
                        "device_tracker.phone",
                        "sensor.removed",
                    ],
                    CONF_PRIVATE_ENTITIES: ["device_tracker.phone"],
                    CONF_ENTITY_ALIASES: {"calendar.shared": ["Bridge log"]},
                },
            )
        ],
    )

    data = await async_get_config_entry_diagnostics(hass, entry)

    assert data["api_registered"] is True
    assert data["options"] == {"min_confidence": 0}
    assert data["speaker_recognition_history_readable"] is False
    assert data["open_issues"] == ["missing_person", "no_wrapper", "stale_entities"]
    (person,) = data["people"]
    assert person == {
        "person": "person_1",
        "account_found": True,
        "account_has_first_name": True,
        "account_active": True,
        "is_admin": False,
        "address_as_set": True,
        "entity_domains": {"device_tracker": 1, "sensor": 1},
        "private_entities": 1,
        "entities_with_aliases": 1,
        "confirm_entities": 0,
        "admin_entities": 0,
        "message_action_set": False,
        "calendars": 1,
        "person_entity_set": False,
        "location_private": False,
        "todo_list_set": False,
        "todo_list_private": False,
        "missing_entities": ["sensor.removed"],
    }
    text = json.dumps(data)
    for secret in ("Robin", "Captain", "captain", "Bridge log", "Sample St", user.id):
        assert secret not in text


async def test_wrapper_diagnostics(hass: HomeAssistant) -> None:
    entry = await _entry(hass, TOOL_TYPE_WRAPPER)
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data == {
        "tool_type": TOOL_TYPE_WRAPPER,
        "options": {
            "deny_unknown": True,
            "custom_refusal_lines": False,
            "alarm_set": True,
            "alarm_unknown_disarmed": False,
        },
        "open_issues": ["wrapper_missing_person_entry"],
    }

"""Tests for loading configured people."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_ADMIN_ENTITIES,
    CONF_CONFIRM_ENTITIES,
    CONF_ENTITIES,
    CONF_LINK_ACTION_ENTITY,
    CONF_LINK_ADMIN_ONLY,
    CONF_LINK_CONFIRM,
    CONF_LINK_NAME,
    CONF_LINK_STATE_ENTITY,
    CONF_TOOL_TYPE,
    CONF_USER_ID,
    DOMAIN,
    SUBENTRY_ENTITY_LINK,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
)
from custom_components.speaker_recognition_tools.people import (
    async_configured_people,
)


def _link(user_id: str, name: str, action: str, **flags) -> ConfigSubentryData:
    return ConfigSubentryData(
        subentry_type=SUBENTRY_ENTITY_LINK,
        title=name,
        unique_id=None,
        data={
            CONF_USER_ID: user_id,
            CONF_LINK_NAME: name,
            CONF_LINK_STATE_ENTITY: f"binary_sensor.{name.lower()}",
            CONF_LINK_ACTION_ENTITY: action,
            **flags,
        },
    )


async def test_linked_device_flags_apply_to_its_action_entity(
    hass: HomeAssistant,
) -> None:
    user = await hass.auth.async_create_user("Sam Sample")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Sam",
                unique_id=user.id,
                data={
                    CONF_USER_ID: user.id,
                    CONF_ENTITIES: ["switch.heater", "lock.shed"],
                    CONF_CONFIRM_ENTITIES: ["switch.heater"],
                    CONF_ADMIN_ENTITIES: ["lock.shed"],
                },
            ),
            _link(user.id, "Gate", "button.gate", **{CONF_LINK_CONFIRM: True}),
            _link(user.id, "Pump", "button.pump", **{CONF_LINK_ADMIN_ONLY: True}),
            _link(user.id, "Lamp", "button.lamp"),
        ],
    )
    entry.add_to_hass(hass)

    (person,) = await async_configured_people(hass, entry)

    assert person.confirm == {"switch.heater", "button.gate"}
    assert person.admin_only == {"lock.shed", "button.pump"}


async def test_person_without_an_account_is_left_out(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Gone",
                unique_id="missing-user",
                data={CONF_USER_ID: "missing-user"},
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await async_configured_people(hass, entry) == []

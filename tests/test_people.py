"""Tests for loading configured people."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_ADMIN_ENTITIES,
    CONF_CALENDARS,
    CONF_CONFIRM_ENTITIES,
    CONF_ENTITIES,
    CONF_LINK_ACTION_ENTITY,
    CONF_LINK_ADMIN_ONLY,
    CONF_LINK_CONFIRM,
    CONF_LINK_NAME,
    CONF_LINK_STATE_ENTITY,
    CONF_LOCATION_PRIVATE,
    CONF_PERSON_ENTITY,
    CONF_PRIVATE_ENTITIES,
    CONF_TODO_LIST,
    CONF_TODO_PRIVATE,
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


async def _one_person(hass: HomeAssistant, data: dict):
    user = await hass.auth.async_create_user("Sam Sample")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Sam",
                unique_id=user.id,
                data={CONF_USER_ID: user.id, **data},
            )
        ],
    )
    entry.add_to_hass(hass)
    (person,) = await async_configured_people(hass, entry)
    return person


async def test_to_do_list_comes_from_its_own_setting(hass: HomeAssistant) -> None:
    person = await _one_person(
        hass,
        {
            CONF_ENTITIES: ["calendar.sam"],
            CONF_TODO_LIST: "todo.sam",
            CONF_TODO_PRIVATE: True,
        },
    )
    assert (person.todo_list, person.todo_private) == ("todo.sam", True)
    assert [e for e, _ in person.entities] == ["calendar.sam"]


async def test_older_setup_uses_its_first_assigned_to_do_list(
    hass: HomeAssistant,
) -> None:
    person = await _one_person(
        hass,
        {
            CONF_ENTITIES: ["todo.sam", "calendar.sam", "todo.spare"],
            CONF_PRIVATE_ENTITIES: ["todo.sam"],
        },
    )
    assert (person.todo_list, person.todo_private) == ("todo.sam", True)
    assert [e for e, _ in person.entities] == ["calendar.sam"]


async def test_person_without_a_to_do_list(hass: HomeAssistant) -> None:
    person = await _one_person(hass, {CONF_ENTITIES: ["calendar.sam"]})
    assert (person.todo_list, person.todo_private) == (None, False)


async def test_person_entity_comes_first_and_needs_no_assignment(
    hass: HomeAssistant,
) -> None:
    hass.states.async_set("person.sam", "home", {"friendly_name": "Sam"})
    person = await _one_person(
        hass,
        {
            CONF_PERSON_ENTITY: "person.sam",
            CONF_ENTITIES: ["calendar.sam", "person.other"],
        },
    )
    assert person.person_entity == "person.sam"
    assert [e for e, _ in person.entities] == ["person.sam", "calendar.sam"]
    assert "person.sam" not in person.private


async def test_private_location_makes_the_person_entity_private(
    hass: HomeAssistant,
) -> None:
    person = await _one_person(
        hass, {CONF_PERSON_ENTITY: "person.sam", CONF_LOCATION_PRIVATE: True}
    )
    assert "person.sam" in person.private


async def test_account_follows_the_person_entity(hass: HomeAssistant) -> None:
    other = await hass.auth.async_create_user("Robin Example")
    hass.states.async_set("person.sam", "home", {"user_id": other.id})
    person = await _one_person(hass, {CONF_PERSON_ENTITY: "person.sam"})
    assert (person.user_id, person.name) == (other.id, "Robin")


async def test_calendars_are_part_of_the_persons_entities(hass: HomeAssistant) -> None:
    person = await _one_person(
        hass,
        {
            CONF_CALENDARS: ["calendar.sam"],
            CONF_ENTITIES: ["sensor.fuel"],
            CONF_PRIVATE_ENTITIES: ["calendar.sam"],
        },
    )
    assert [e for e, _ in person.entities] == ["calendar.sam", "sensor.fuel"]
    assert "calendar.sam" in person.private


async def test_full_name_comes_from_the_person_entity(hass: HomeAssistant) -> None:
    hass.states.async_set("person.sam", "home", {"friendly_name": "Samantha Sample"})
    person = await _one_person(hass, {CONF_PERSON_ENTITY: "person.sam"})
    assert (person.name, person.full_name) == ("Sam", "Samantha Sample")

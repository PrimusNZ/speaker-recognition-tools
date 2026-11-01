"""Tests for moving older speaking people onto their person entities."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_CALENDARS,
    CONF_ENTITIES,
    CONF_ENTITY_ALIASES,
    CONF_LOCATION_PRIVATE,
    CONF_PERSON_ENTITY,
    CONF_PRIVATE_ENTITIES,
    CONF_TOOL_TYPE,
    CONF_USER_ID,
    DOMAIN,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
)


def _speaker(user_id: str, title: str, **data) -> ConfigSubentryData:
    return ConfigSubentryData(
        subentry_type=SUBENTRY_SPEAKER,
        title=title,
        unique_id=user_id,
        data={CONF_USER_ID: user_id, **data},
    )


async def _migrated(hass: HomeAssistant, *subentries) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        version=1,
        minor_version=1,
        subentries_data=list(subentries),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _data(entry, _name):
    """The one speaking person's settings."""
    return next(
        s.data for s in entry.subentries.values() if s.subentry_type == SUBENTRY_SPEAKER
    )


async def test_people_move_onto_the_person_entity_for_their_account(
    hass: HomeAssistant,
) -> None:
    sam = await hass.auth.async_create_user("Sam Sample")
    hass.states.async_set("person.sam", "home", {"user_id": sam.id})
    entry = await _migrated(
        hass,
        _speaker(
            sam.id,
            "Sam",
            **{
                CONF_ENTITIES: ["person.sam", "calendar.sam"],
                CONF_ENTITY_ALIASES: {"person.sam": ["Me"], "calendar.sam": ["Diary"]},
            },
        ),
    )
    data = _data(entry, "Sam")
    assert data[CONF_PERSON_ENTITY] == "person.sam"
    assert data[CONF_ENTITIES] == []
    assert data[CONF_ENTITY_ALIASES] == {"calendar.sam": ["Diary"]}
    assert CONF_LOCATION_PRIVATE not in data
    assert entry.minor_version == 3


async def test_a_private_person_entity_keeps_the_location_private(
    hass: HomeAssistant,
) -> None:
    sam = await hass.auth.async_create_user("Sam Sample")
    hass.states.async_set("person.sam", "home", {"user_id": sam.id})
    entry = await _migrated(
        hass,
        _speaker(
            sam.id,
            "Sam",
            **{
                CONF_ENTITIES: ["person.sam"],
                CONF_PRIVATE_ENTITIES: ["person.sam"],
            },
        ),
    )
    data = _data(entry, "Sam")
    assert data[CONF_LOCATION_PRIVATE] is True
    assert data[CONF_PRIVATE_ENTITIES] == []


async def test_someone_with_no_matching_person_is_left_as_they_are(
    hass: HomeAssistant,
) -> None:
    sam = await hass.auth.async_create_user("Sam Sample")
    entry = await _migrated(
        hass, _speaker(sam.id, "Sam", **{CONF_ENTITIES: ["person.elsewhere"]})
    )
    data = _data(entry, "Sam")
    assert CONF_PERSON_ENTITY not in data
    assert data[CONF_ENTITIES] == ["person.elsewhere"]


async def test_calendars_move_to_their_field_and_stay_private(
    hass: HomeAssistant,
) -> None:
    sam = await hass.auth.async_create_user("Sam Sample")
    entry = await _migrated(
        hass,
        _speaker(
            sam.id,
            "Sam",
            **{
                CONF_ENTITIES: ["calendar.home", "sensor.fuel", "calendar.diary"],
                CONF_PRIVATE_ENTITIES: ["calendar.diary"],
            },
        ),
    )
    data = _data(entry, "Sam")
    assert data[CONF_ENTITIES] == ["sensor.fuel"]
    assert data[CONF_CALENDARS] == ["calendar.home", "calendar.diary"]
    assert data[CONF_PRIVATE_ENTITIES] == ["calendar.diary"]


async def test_entries_already_on_person_entities_get_the_calendar_step(
    hass: HomeAssistant,
) -> None:
    sam = await hass.auth.async_create_user("Sam Sample")
    hass.states.async_set("person.sam", "home", {"user_id": sam.id})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        minor_version=2,
        subentries_data=[
            _speaker(
                sam.id,
                "Sam",
                **{CONF_PERSON_ENTITY: "person.sam", CONF_ENTITIES: ["calendar.sam"]},
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = _data(entry, "Sam")
    assert (data[CONF_ENTITIES], data[CONF_CALENDARS]) == ([], ["calendar.sam"])
    assert entry.minor_version == 3

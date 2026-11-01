"""Bring speaking people saved before 0.10.1 up to date."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_ADMIN_ENTITIES,
    CONF_CALENDARS,
    CONF_CONFIRM_ENTITIES,
    CONF_ENTITIES,
    CONF_ENTITY_ALIASES,
    CONF_LOCATION_PRIVATE,
    CONF_PERSON_ENTITY,
    CONF_PRIVATE_ENTITIES,
    CONF_USER_ID,
    SUBENTRY_SPEAKER,
)
from .people import is_calendar, is_person, person_user_id

_LISTS = (
    CONF_ENTITIES,
    CONF_PRIVATE_ENTITIES,
    CONF_CONFIRM_ENTITIES,
    CONF_ADMIN_ENTITIES,
)


@callback
def async_move_people_to_person_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Build each speaking person on the person entity linked to their account.

    Person entities assigned by hand are dropped, since every speaking person now
    has one; if one was private, their location stays private. Anyone with no
    matching person entity is left as they are, and a
    Repairs issue asks for one.
    """
    by_user = {
        user_id: state.entity_id
        for state in hass.states.async_all("person")
        if (user_id := person_user_id(hass, state.entity_id))
    }
    for sub in list(entry.subentries.values()):
        if sub.subentry_type != SUBENTRY_SPEAKER or sub.data.get(CONF_PERSON_ENTITY):
            continue
        person = by_user.get(sub.data[CONF_USER_ID])
        if person is None:
            continue
        data: dict[str, Any] = {CONF_PERSON_ENTITY: person, **sub.data}
        # A person entity someone had marked private keeps their location private.
        if any(is_person(e) for e in data.get(CONF_PRIVATE_ENTITIES, [])):
            data[CONF_LOCATION_PRIVATE] = True
        for key in _LISTS:
            if key in data:
                data[key] = [e for e in data[key] if not is_person(e)]
        if aliases := data.get(CONF_ENTITY_ALIASES):
            data[CONF_ENTITY_ALIASES] = {
                e: names for e, names in aliases.items() if not is_person(e)
            }
        hass.config_entries.async_update_subentry(entry, sub, data=data)


@callback
def async_move_calendars_to_their_field(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Move calendars from each person's entity list to their Calendars field.

    Private, confirmation and alias settings name entity ids, so they carry on
    applying to the moved calendars unchanged.
    """
    for sub in list(entry.subentries.values()):
        if sub.subentry_type != SUBENTRY_SPEAKER:
            continue
        entities = sub.data.get(CONF_ENTITIES, [])
        calendars = [e for e in entities if is_calendar(e)]
        if not calendars:
            continue
        data: dict[str, Any] = dict(sub.data)
        data[CONF_ENTITIES] = [e for e in entities if not is_calendar(e)]
        data[CONF_CALENDARS] = list(
            dict.fromkeys([*data.get(CONF_CALENDARS, []), *calendars])
        )
        hass.config_entries.async_update_subentry(entry, sub, data=data)

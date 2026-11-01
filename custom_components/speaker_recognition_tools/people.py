"""Load the configured people from a Speaking Person entry."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ADDRESS_AS,
    CONF_ADMIN_ENTITIES,
    CONF_CONFIRM_ENTITIES,
    CONF_ENTITIES,
    CONF_ENTITY_ALIASES,
    CONF_LEGACY_ADDRESS_AS,
    CONF_LINK_ACTION_ENTITY,
    CONF_LINK_ADMIN_ONLY,
    CONF_LINK_ALIASES,
    CONF_LINK_CONFIRM,
    CONF_LINK_NAME,
    CONF_LINK_PRIVATE,
    CONF_LINK_STATE_ENTITY,
    CONF_NOTIFY_SERVICE,
    CONF_PRIVATE_ENTITIES,
    CONF_THIRD_PERSON_REFERENCE,
    CONF_USER_ID,
    SUBENTRY_ENTITY_LINK,
    SUBENTRY_SPEAKER,
)
from .prompt import Person


def first_name(name: str | None) -> str | None:
    """Return the first word of an account name; only first names reach the prompt."""
    parts = (name or "").split()
    return parts[0] if parts else None


def address_as(data) -> str:
    """Return a person's configured address form, reading the legacy key too."""
    return data.get(CONF_ADDRESS_AS, data.get(CONF_LEGACY_ADDRESS_AS)) or ""


async def async_configured_people(
    hass: HomeAssistant, entry: ConfigEntry
) -> list[Person]:
    """Build each configured person, as used by the live prompt, tools and previews.

    A person whose account is missing or has no name is left out, so that
    speaker is treated as unknown.
    """
    links_by_user: dict[str, list[tuple[str, str, str, bool, tuple[str, ...]]]] = {}
    # A linked device's flags apply to its action entity.
    link_confirm: dict[str, set[str]] = {}
    link_admin_only: dict[str, set[str]] = {}
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_ENTITY_LINK:
            continue
        data = sub.data
        if data.get(CONF_LINK_CONFIRM):
            link_confirm.setdefault(data[CONF_USER_ID], set()).add(
                data[CONF_LINK_ACTION_ENTITY]
            )
        if data.get(CONF_LINK_ADMIN_ONLY):
            link_admin_only.setdefault(data[CONF_USER_ID], set()).add(
                data[CONF_LINK_ACTION_ENTITY]
            )
        links_by_user.setdefault(data[CONF_USER_ID], []).append(
            (
                data[CONF_LINK_NAME],
                data[CONF_LINK_STATE_ENTITY],
                data[CONF_LINK_ACTION_ENTITY],
                data.get(CONF_LINK_PRIVATE, False),
                tuple(data.get(CONF_LINK_ALIASES, [])),
            )
        )

    people = []
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_SPEAKER:
            continue
        account = await hass.auth.async_get_user(sub.data[CONF_USER_ID])
        name = first_name(account.name) if account else None
        if account is None or not name:
            continue
        entities = []
        for entity_id in sub.data.get(CONF_ENTITIES, []):
            state = hass.states.get(entity_id)
            entities.append((entity_id, state.name if state else entity_id))
        entity_aliases = tuple(
            (entity_id, tuple(names))
            for entity_id, names in sub.data.get(CONF_ENTITY_ALIASES, {}).items()
        )
        people.append(
            Person(
                sub.data[CONF_USER_ID],
                name,
                address_as(sub.data),
                tuple(entities),
                frozenset(sub.data.get(CONF_PRIVATE_ENTITIES, [])),
                sub.data.get(CONF_THIRD_PERSON_REFERENCE) or None,
                entity_aliases,
                tuple(links_by_user.get(sub.data[CONF_USER_ID], [])),
                account.is_admin,
                frozenset(sub.data.get(CONF_CONFIRM_ENTITIES, []))
                | link_confirm.get(sub.data[CONF_USER_ID], set()),
                frozenset(sub.data.get(CONF_ADMIN_ENTITIES, []))
                | link_admin_only.get(sub.data[CONF_USER_ID], set()),
                sub.data.get(CONF_NOTIFY_SERVICE) or None,
            )
        )
    return people

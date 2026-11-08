"""Load the configured people from a Speaking Person entry."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ADDRESS_AS,
    CONF_ADMIN_ENTITIES,
    CONF_CALENDARS,
    CONF_CONFIRM_ENTITIES,
    CONF_ENTITIES,
    CONF_ENTITY_ALIASES,
    CONF_HOUSEHOLD_ALIASES,
    CONF_HOUSEHOLD_DEVICES,
    CONF_LEGACY_ADDRESS_AS,
    CONF_LINK_ACTION_ENTITY,
    CONF_LINK_ADMIN_ONLY,
    CONF_LINK_ALIASES,
    CONF_LINK_CONFIRM,
    CONF_LINK_NAME,
    CONF_LINK_PRIVATE,
    CONF_LINK_STATE_ENTITY,
    CONF_LOCATION_PRIVATE,
    CONF_NOTIFY_SERVICE,
    CONF_PERSON_ENTITY,
    CONF_PRIVATE_ENTITIES,
    CONF_THIRD_PERSON_REFERENCE,
    CONF_TODO_LIST,
    CONF_TODO_PRIVATE,
    CONF_USER_ID,
    SUBENTRY_ENTITY_LINK,
    SUBENTRY_SPEAKER,
)
from .prompt import Person


def first_name(name: str | None) -> str | None:
    """Return the first word of an account name; only first names reach the prompt."""
    parts = (name or "").split()
    return parts[0] if parts else None


def is_calendar(entity_id: str) -> bool:
    return entity_id.startswith("calendar.")


def is_person(entity_id: str) -> bool:
    return entity_id.startswith("person.")


def person_user_id(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Return the user account linked to a person entity, or None."""
    state = hass.states.get(entity_id) if entity_id else None
    user_id = state.attributes.get("user_id") if state else None
    return user_id if isinstance(user_id, str) and user_id else None


def speaker_user_id(hass: HomeAssistant, data) -> str:
    """Return a speaking person's account: their person entity's, else the saved one."""
    return person_user_id(hass, data.get(CONF_PERSON_ENTITY)) or data[CONF_USER_ID]


def is_todo(entity_id: str) -> bool:
    return entity_id.startswith("todo.")


def todo_settings(data) -> tuple[str | None, bool]:
    """Return a person's to-do list and whether it is private.

    People saved before the To-do list field existed had their lists in the
    entity list; the first one becomes their to-do list, private if it was.
    """
    if CONF_TODO_LIST in data:
        todo = data.get(CONF_TODO_LIST) or None
        return todo, bool(todo and data.get(CONF_TODO_PRIVATE))
    todo = next((e for e in data.get(CONF_ENTITIES, []) if is_todo(e)), None)
    return todo, bool(todo and todo in data.get(CONF_PRIVATE_ENTITIES, []))


async def speaker_name(hass: HomeAssistant, data) -> str:
    """The name to show for a speaking person in settings, not in the prompt.

    Uses the person entity's name, or the account name for older entries.
    """
    state = hass.states.get(data.get(CONF_PERSON_ENTITY) or "")
    if state is not None:
        return state.name
    user = await hass.auth.async_get_user(data[CONF_USER_ID])
    return user.name if user and user.name else data[CONF_USER_ID]


async def link_title(hass: HomeAssistant, entry: ConfigEntry, data) -> str:
    """Return the label for a linked device: its spoken name, person and flags."""
    owner = next(
        (
            sub.data
            for sub in entry.subentries.values()
            if sub.subentry_type == SUBENTRY_SPEAKER
            and sub.data[CONF_USER_ID] == data[CONF_USER_ID]
        ),
        {CONF_USER_ID: data[CONF_USER_ID]},
    )
    notes = [
        note
        for key, note in (
            (CONF_LINK_PRIVATE, "private"),
            (CONF_LINK_CONFIRM, "needs confirmation"),
            (CONF_LINK_ADMIN_ONLY, "administrators only"),
        )
        if data.get(key)
    ]
    who = ", ".join([await speaker_name(hass, owner), *notes])
    return f"{data[CONF_LINK_NAME]} ({who})"


async def speaker_title(hass: HomeAssistant, data) -> str:
    """Return the label Home Assistant lists a speaking person under."""
    name = await speaker_name(hass, data)
    count = len(data.get(CONF_ENTITIES, [])) + len(data.get(CONF_CALENDARS, []))
    amount = (
        "no entities" if not count else f"{count} {'entity' if count == 1 else 'entities'}"
    )
    if private := data.get(CONF_PRIVATE_ENTITIES):
        amount += f", {len(private)} private"
    if data.get(CONF_LOCATION_PRIVATE):
        amount += ", location private"
    if todo_settings(data)[1]:
        amount += ", to-do list private"
    form = address_as(data)
    return f"{f'{name}: {form}' if form else name} ({amount})"


def address_as(data) -> str:
    """Return a person's configured address form, reading the legacy key too."""
    return data.get(CONF_ADDRESS_AS, data.get(CONF_LEGACY_ADDRESS_AS)) or ""


def household_entity_ids(entry: ConfigEntry) -> list[str]:
    """The household devices of an entry. Calendars are never shared."""
    return [
        entity_id
        for entity_id in entry.options.get(CONF_HOUSEHOLD_DEVICES, [])
        if not is_calendar(entity_id)
    ]


def household_aliases(entry: ConfigEntry) -> dict[str, tuple[str, ...]]:
    """The configured alternate names for each household device."""
    shared = set(household_entity_ids(entry))
    return {
        entity_id: tuple(names)
        for entity_id, names in entry.options.get(CONF_HOUSEHOLD_ALIASES, {}).items()
        if entity_id in shared and names
    }


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
        user_id = speaker_user_id(hass, sub.data)
        account = await hass.auth.async_get_user(user_id)
        name = first_name(account.name) if account else None
        if account is None or not name:
            continue
        entities = []
        private = set(sub.data.get(CONF_PRIVATE_ENTITIES, []))
        # The person entity always belongs to its person, ahead of their other
        # entities. A to-do list only comes from the To-do list setting.
        person_entity = sub.data.get(CONF_PERSON_ENTITY)
        if person_entity:
            state = hass.states.get(person_entity)
            entities.append((person_entity, state.name if state else person_entity))
        for entity_id in (
            *sub.data.get(CONF_CALENDARS, []),
            *sub.data.get(CONF_ENTITIES, []),
        ):
            if is_todo(entity_id) or (person_entity and is_person(entity_id)):
                continue
            state = hass.states.get(entity_id)
            entities.append((entity_id, state.name if state else entity_id))
        todo_list, todo_private = todo_settings(sub.data)
        entity_aliases = tuple(
            (entity_id, tuple(names))
            for entity_id, names in sub.data.get(CONF_ENTITY_ALIASES, {}).items()
        )
        people.append(
            Person(
                user_id,
                name,
                address_as(sub.data),
                tuple(entities),
                frozenset(private),
                sub.data.get(CONF_THIRD_PERSON_REFERENCE) or None,
                entity_aliases,
                tuple(links_by_user.get(sub.data[CONF_USER_ID], [])),
                account.is_admin,
                frozenset(sub.data.get(CONF_CONFIRM_ENTITIES, []))
                | link_confirm.get(sub.data[CONF_USER_ID], set()),
                frozenset(sub.data.get(CONF_ADMIN_ENTITIES, []))
                | link_admin_only.get(sub.data[CONF_USER_ID], set()),
                sub.data.get(CONF_NOTIFY_SERVICE) or None,
                todo_list,
                todo_private,
                person_entity,
                await speaker_name(hass, sub.data),
                bool(sub.data.get(CONF_LOCATION_PRIVATE)),
            )
        )
    return people

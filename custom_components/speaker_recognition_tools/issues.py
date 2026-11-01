"""Keep saved people in step with Home Assistant, and raise Repairs issues when they drift.

Entity renames are followed automatically. Entities that no longer exist, and
people whose user account was deleted, are reported as Repairs issues, because
those people or entities silently drop out of the prompt and tools.
"""

from __future__ import annotations

from typing import Any

from homeassistant.auth import EVENT_USER_REMOVED, EVENT_USER_UPDATED
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.start import async_at_started

from .const import (
    CONF_ADMIN_ENTITIES,
    CONF_CALENDARS,
    CONF_CONFIRM_ENTITIES,
    CONF_ENTITIES,
    CONF_ENTITY_ALIASES,
    CONF_LINK_ACTION_ENTITY,
    CONF_LINK_STATE_ENTITY,
    CONF_NOTIFY_SERVICE,
    CONF_PERSON_ENTITY,
    CONF_PRIVATE_ENTITIES,
    CONF_TODO_LIST,
    DOMAIN,
    SUBENTRY_ENTITY_LINK,
    SUBENTRY_SPEAKER,
)
from .people import first_name, link_title, speaker_title, speaker_user_id

ISSUE_STALE_ENTITIES = "stale_entities"
ISSUE_MISSING_ACCOUNT = "missing_account"
ISSUE_MISSING_PERSON = "missing_person"
_CHECK_DELAY = 2.0  # seconds; registry changes often arrive in bursts

# Settings keys that hold entity ids, per subentry type.
LIST_KEYS: dict[str, tuple[str, ...]] = {
    SUBENTRY_SPEAKER: (
        CONF_ENTITIES,
        CONF_CALENDARS,
        CONF_PRIVATE_ENTITIES,
        CONF_CONFIRM_ENTITIES,
        CONF_ADMIN_ENTITIES,
    ),
    SUBENTRY_ENTITY_LINK: (),
}
SINGLE_KEYS: dict[str, tuple[str, ...]] = {
    SUBENTRY_SPEAKER: (CONF_PERSON_ENTITY, CONF_TODO_LIST),
    SUBENTRY_ENTITY_LINK: (CONF_LINK_STATE_ENTITY, CONF_LINK_ACTION_ENTITY),
}


def subentry_entity_ids(sub: ConfigSubentry) -> set[str]:
    """Every entity id a person or linked device refers to."""
    data = sub.data
    ids: set[str] = set()
    for key in LIST_KEYS.get(sub.subentry_type, ()):
        ids.update(data.get(key, []))
    for key in SINGLE_KEYS.get(sub.subentry_type, ()):
        if data.get(key):
            ids.add(data[key])
    if sub.subentry_type == SUBENTRY_SPEAKER:
        ids.update(data.get(CONF_ENTITY_ALIASES, {}))
    return ids


def is_missing(hass: HomeAssistant, entity_id: str) -> bool:
    """An entity is gone when it has neither a registry entry nor a state.

    A registered entity that is merely unavailable is not reported.
    """
    return (
        er.async_get(hass).async_get(entity_id) is None
        and hass.states.get(entity_id) is None
    )


def renamed_data(
    sub: ConfigSubentry, old_id: str, new_id: str
) -> dict[str, Any] | None:
    """Return the subentry data with one entity id renamed, or None if unused."""
    data = dict(sub.data)
    changed = False
    for key in LIST_KEYS.get(sub.subentry_type, ()):
        values = list(data.get(key, []))
        if old_id in values:
            data[key] = [new_id if v == old_id else v for v in values]
            changed = True
    for key in SINGLE_KEYS.get(sub.subentry_type, ()):
        if data.get(key) == old_id:
            data[key] = new_id
            changed = True
    aliases = data.get(CONF_ENTITY_ALIASES)
    if sub.subentry_type == SUBENTRY_SPEAKER and aliases and old_id in aliases:
        data[CONF_ENTITY_ALIASES] = {
            (new_id if k == old_id else k): v for k, v in aliases.items()
        }
        changed = True
    return data if changed else None


def _issue_id(kind: str, entry: ConfigEntry, sub: ConfigSubentry) -> str:
    return f"{kind}_{entry.entry_id}_{sub.subentry_id}"


async def async_check_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create or clear this entry's Repairs issues to match its current settings."""
    wanted: dict[str, tuple[str, dict[str, str]]] = {}
    for sub in list(entry.subentries.values()):
        if sub.subentry_type == SUBENTRY_SPEAKER:
            # Keep the listed name in step with the person entity's name.
            if (title := await speaker_title(hass, sub.data)) != sub.title:
                hass.config_entries.async_update_subentry(entry, sub, title=title)
                sub = entry.subentries[sub.subentry_id]
            account = await hass.auth.async_get_user(speaker_user_id(hass, sub.data))
            if account is None or not first_name(account.name):
                wanted[_issue_id(ISSUE_MISSING_ACCOUNT, entry, sub)] = (
                    ISSUE_MISSING_ACCOUNT,
                    {"name": sub.title},
                )
            if not sub.data.get(CONF_PERSON_ENTITY):
                wanted[_issue_id(ISSUE_MISSING_PERSON, entry, sub)] = (
                    ISSUE_MISSING_PERSON,
                    {"name": sub.title},
                )
        if sub.subentry_type == SUBENTRY_ENTITY_LINK and (
            title := await link_title(hass, entry, sub.data)
        ) != sub.title:
            hass.config_entries.async_update_subentry(entry, sub, title=title)
            sub = entry.subentries[sub.subentry_id]
        missing = sorted(e for e in subentry_entity_ids(sub) if is_missing(hass, e))
        if (
            notify := sub.data.get(CONF_NOTIFY_SERVICE)
        ) and not hass.services.has_service(*notify.partition(".")[::2]):
            missing.append(f"{notify} (message action)")
        if missing:
            wanted[_issue_id(ISSUE_STALE_ENTITIES, entry, sub)] = (
                ISSUE_STALE_ENTITIES,
                {"name": sub.title, "entities": ", ".join(missing)},
            )

    registry = ir.async_get(hass)
    suffix_owner = f"_{entry.entry_id}_"
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN and suffix_owner in issue_id and issue_id not in wanted:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
    for issue_id, (kind, placeholders) in wanted.items():
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=kind,
            translation_placeholders=placeholders,
        )


def async_clear_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove every Repairs issue that belongs to this entry."""
    owner = f"_{entry.entry_id}_"
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN and owner in issue_id:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def async_setup_repairs(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Follow renames and re-check this entry whenever something relevant changes."""

    async def _check() -> None:
        await async_check_entry(hass, entry)

    debouncer = Debouncer(
        hass, None, cooldown=_CHECK_DELAY, immediate=False, function=_check
    )
    started = False

    @callback
    def _schedule(*_args: Any) -> None:
        if started:
            debouncer.async_schedule_call()

    async def _at_started(_hass: HomeAssistant) -> None:
        nonlocal started
        started = True
        await async_check_entry(hass, entry)

    @callback
    def _registry_updated(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        data = event.data
        old_id = data.get("old_entity_id")
        if data["action"] == "update" and old_id:
            for sub in list(entry.subentries.values()):
                if (new := renamed_data(sub, old_id, data["entity_id"])) is not None:
                    hass.config_entries.async_update_subentry(entry, sub, data=new)
        _schedule()

    entry.async_on_unload(async_at_started(hass, _at_started))
    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _registry_updated)
    )
    entry.async_on_unload(hass.bus.async_listen(EVENT_USER_REMOVED, _schedule))
    entry.async_on_unload(hass.bus.async_listen(EVENT_USER_UPDATED, _schedule))
    entry.async_on_unload(entry.add_update_listener(_on_entry_update(_schedule)))
    entry.async_on_unload(debouncer.async_shutdown)


def _on_entry_update(schedule):
    async def _listener(_hass: HomeAssistant, _entry: ConfigEntry) -> None:
        schedule()

    return _listener

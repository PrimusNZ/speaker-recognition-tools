"""Diagnostics download, with names and addresses left out."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import llm

from .const import (
    CONF_ADMIN_ENTITIES,
    CONF_CALENDARS,
    CONF_CONFIRM_ENTITIES,
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_ENTITY_ALIASES,
    CONF_LOCATION_PRIVATE,
    CONF_MIN_CONFIDENCE,
    CONF_NOTIFY_SERVICE,
    CONF_PERSON_ENTITY,
    CONF_PRIVATE_ENTITIES,
    CONF_REFUSAL_LINES,
    CONF_TOOL_TYPE,
    CONF_USER_ID,
    DEVICE_API_ID,
    DOMAIN,
    PERSON_API_ID,
    SUBENTRY_ENTITY_LINK,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
)
from .issues import is_missing, subentry_entity_ids
from .people import address_as, first_name, todo_settings
from .recognition import history_available


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Describe the entry's setup without names, aliases or addresses."""
    is_person = entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON
    api_id = PERSON_API_ID if is_person else DEVICE_API_ID
    result: dict[str, Any] = {
        "tool_type": entry.data.get(CONF_TOOL_TYPE),
        "api_registered": any(api.id == api_id for api in llm.async_get_apis(hass)),
        "open_issues": sorted(
            issue.translation_key or issue_id
            for (domain, issue_id), issue in ir.async_get(hass).issues.items()
            if domain == DOMAIN and f"_{entry.entry_id}_" in issue_id
        ),
    }
    if not is_person:
        return result

    options = entry.options
    result["options"] = {
        "deny_unknown": options.get(CONF_DENY_UNKNOWN, False),
        "custom_refusal_lines": CONF_REFUSAL_LINES in options,
        "min_confidence": options.get(CONF_MIN_CONFIDENCE, 0),
    }
    result["speaker_recognition_history_readable"] = history_available(hass)
    people = []
    labels: dict[str, str] = {}
    for index, sub in enumerate(
        (s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_SPEAKER),
        start=1,
    ):
        label = f"person_{index}"
        labels[sub.data[CONF_USER_ID]] = label
        account = await hass.auth.async_get_user(sub.data[CONF_USER_ID])
        entities = sub.data.get(CONF_ENTITIES, [])
        people.append(
            {
                "person": label,
                "account_found": account is not None,
                "account_has_first_name": bool(account and first_name(account.name)),
                "account_active": bool(account and account.is_active),
                "is_admin": bool(account and account.is_admin),
                "address_as_set": bool(address_as(sub.data)),
                "entity_domains": _domain_counts(entities),
                "private_entities": len(sub.data.get(CONF_PRIVATE_ENTITIES, [])),
                "entities_with_aliases": len(sub.data.get(CONF_ENTITY_ALIASES, {})),
                "confirm_entities": len(sub.data.get(CONF_CONFIRM_ENTITIES, [])),
                "admin_entities": len(sub.data.get(CONF_ADMIN_ENTITIES, [])),
                "message_action_set": bool(sub.data.get(CONF_NOTIFY_SERVICE)),
                "calendars": len(sub.data.get(CONF_CALENDARS, [])),
                "person_entity_set": bool(sub.data.get(CONF_PERSON_ENTITY)),
                "location_private": bool(sub.data.get(CONF_LOCATION_PRIVATE)),
                "todo_list_set": bool(todo_settings(sub.data)[0]),
                "todo_list_private": todo_settings(sub.data)[1],
                "missing_entities": sorted(
                    e for e in subentry_entity_ids(sub) if is_missing(hass, e)
                ),
            }
        )
    links = [
        {
            "person": labels.get(sub.data[CONF_USER_ID], "unknown_person"),
            "missing_entities": sorted(
                e for e in subentry_entity_ids(sub) if is_missing(hass, e)
            ),
        }
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_ENTITY_LINK
    ]
    result["people"] = people
    result["linked_devices"] = links
    return result


def _domain_counts(entity_ids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity_id in entity_ids:
        domain = entity_id.split(".", 1)[0]
        counts[domain] = counts.get(domain, 0) + 1
    return dict(sorted(counts.items()))

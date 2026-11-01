"""Home Assistant actions that scripts and automations can call."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError

from .config_flow import _configured_people
from .const import CONF_TOOL_TYPE, DOMAIN, TOOL_TYPE_PERSON
from .prompt import Person

SERVICE_GET_USER_LEVEL = "get_user_level"
ATTR_PERSON = "person"
ATTR_USER_ID = "user_id"

GET_USER_LEVEL_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_PERSON): str, vol.Optional(ATTR_USER_ID): str}
)


def _level(is_admin: bool) -> str:
    return "Administrator" if is_admin else "User"


def _answer(
    *,
    found: bool,
    is_admin: bool = False,
    user_id: str | None = None,
    name: str | None = None,
    address_as: str | None = None,
    configured: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build the response. An unknown person is never an administrator."""
    answer: dict[str, Any] = {
        "found": found,
        "configured": configured,
        "user_id": user_id,
        "name": name,
        "address_as": address_as,
        "level": _level(is_admin) if found else None,
        "is_admin": bool(found and is_admin),
    }
    if reason:
        answer["reason"] = reason
    return answer


def _match_person(people: list[Person], text: str) -> list[Person]:
    """People whose first name, address form or third-person reference matches."""
    key = text.strip().casefold()
    return [
        p
        for p in people
        if key
        in (
            (p.name or "").casefold(),
            p.direct_address.casefold(),
            p.third_person_form.casefold(),
        )
    ]


async def _get_user_level(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Return a person's Home Assistant user level for use in scripts."""
    person_text = (call.data.get(ATTR_PERSON) or "").strip()
    user_id = (call.data.get(ATTR_USER_ID) or "").strip()
    if person_text and user_id:
        raise ServiceValidationError("Give either person or user_id, not both.")

    people: list[Person] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON:
            people.extend(await _configured_people(hass, entry))

    if person_text:
        matches = _match_person(people, person_text)
        if len(matches) != 1:
            return _answer(
                found=False,
                reason="ambiguous_person" if matches else "unknown_person",
            )
        person = matches[0]
        return _answer(
            found=True,
            is_admin=person.is_admin,
            user_id=person.user_id,
            name=person.name,
            address_as=person.direct_address,
            configured=True,
        )

    # No person given: use the user ID, or the user who triggered the script.
    user_id = user_id or (call.context.user_id if call.context else None) or ""
    if not user_id:
        return _answer(found=False, reason="no_user")
    person = next((p for p in people if p.user_id == user_id), None)
    if person is not None:
        return _answer(
            found=True,
            is_admin=person.is_admin,
            user_id=person.user_id,
            name=person.name,
            address_as=person.direct_address,
            configured=True,
        )
    # Not a configured person: still report the account's level, first name only.
    account = await hass.auth.async_get_user(user_id)
    if account is None:
        return _answer(found=False, user_id=user_id, reason="unknown_user")
    parts = (account.name or "").split()
    return _answer(
        found=True,
        is_admin=account.is_admin,
        user_id=account.id,
        name=parts[0] if parts else None,
    )


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions once for the whole integration."""

    async def handle_get_user_level(call: ServiceCall) -> ServiceResponse:
        return await _get_user_level(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_USER_LEVEL,
        handle_get_user_level,
        schema=GET_USER_LEVEL_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

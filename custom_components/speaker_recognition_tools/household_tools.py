"""Tools for household devices: shared entities that anyone who is not denied may use.

A household device is not assigned to a person. The tools pick the unit that
matches the spoken name, preferring the one in the room the speaker is in, then
on the same floor. Unknown speakers can use them too, except locks, alarm
panels, door, gate and garage covers, which are refused in the tools.
"""

from __future__ import annotations

import re
from typing import Any

import probatio as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    floor_registry as fr,
)
from homeassistant.helpers import (
    llm,
)

from .const import DOMAIN
from .entity_tools import (
    check_service,
    is_restricted_entity,
    sensitive_action_needs_confirmation,
    state_after_call,
    validate_climate,
)
from .prompt import Person
from .tool_base import _READ_ONLY, _WRITE, _confirm_change, _result

_WORDS = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORDS.findall(text.casefold()))


def entity_area_id(hass: HomeAssistant, entity_id: str) -> str | None:
    """The area of an entity, from the entity itself or else its device."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return None
    if entry.area_id:
        return entry.area_id
    if entry.device_id and (device := dr.async_get(hass).async_get(entry.device_id)):
        return dr.async_get_effective_area_id(hass, device)
    return None


def area_names(
    hass: HomeAssistant, area_id: str | None
) -> tuple[str | None, str | None]:
    """Return an area's name and the name of its floor."""
    if not area_id or not (area := ar.async_get(hass).async_get_area(area_id)):
        return None, None
    floor = fr.async_get(hass).async_get_floor(area.floor_id) if area.floor_id else None
    return area.name, floor.name if floor else None


def device_area_id(hass: HomeAssistant, device_id: str | None) -> str | None:
    """The area of the device the speaker is using."""
    if device_id and (device := dr.async_get(hass).async_get(device_id)):
        return dr.async_get_effective_area_id(hass, device)
    return None


def device_aliases(
    hass: HomeAssistant,
    entity_id: str,
    configured: dict[str, tuple[str, ...]] | None,
) -> tuple[str, ...]:
    """The configured aliases, then the ones set on the entity in Home Assistant."""
    entry = er.async_get(hass).async_get(entity_id)
    # Home Assistant keeps a marker object in the alias set for "use the entity name".
    registry = [a for a in (entry.aliases if entry else ()) if isinstance(a, str)]
    names = [*(configured or {}).get(entity_id, ()), *sorted(registry)]
    seen: set[str] = set()
    unique = []
    for name in names:
        name = " ".join(str(name).split())
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            unique.append(name)
    return tuple(unique)


def household_devices(
    hass: HomeAssistant,
    entity_ids: list[str],
    configured: dict[str, tuple[str, ...]] | None = None,
) -> list[tuple[str, str, str | None, str | None, bool, tuple[str, ...]]]:
    """Describe devices as (entity_id, name, area, floor, restricted, other aliases).

    The first configured alias is the preferred name, as for assigned entities.
    """
    devices = []
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        name = " ".join((state.name if state else entity_id).split())
        aliases = device_aliases(hass, entity_id, configured)
        if configured and configured.get(entity_id):
            name, aliases = aliases[0], aliases[1:]
        area, floor = area_names(hass, entity_area_id(hass, entity_id))
        devices.append(
            (
                entity_id,
                name,
                area,
                floor,
                is_restricted_entity(hass, entity_id),
                aliases,
            )
        )
    return devices


def _same_floor(hass: HomeAssistant, area_id: str | None, floor_id: str | None) -> bool:
    if not area_id or not floor_id:
        return False
    area = ar.async_get(hass).async_get_area(area_id)
    return bool(area and area.floor_id == floor_id)


def _requested_places(hass: HomeAssistant, requested: str) -> tuple[set[str], set[str]]:
    """Return the area ids and floor ids whose name or alias matches the request."""
    key = " ".join(requested.casefold().split())
    areas = {
        area.id
        for area in ar.async_get(hass).async_list_areas()
        if key in {n.casefold() for n in (area.name, *area.aliases)}
    }
    floors = {
        floor.floor_id
        for floor in fr.async_get(hass).async_list_floors()
        if key in {n.casefold() for n in (floor.name, *floor.aliases)}
    }
    return areas, floors


class _HouseholdTool(llm.Tool):
    """Shared set-up for the household device tools."""

    integration = DOMAIN

    def __init__(
        self,
        entity_ids: list[str],
        people: list[Person],
        speaker: Person | None,
        *,
        uncertain: bool = False,
        aliases: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._aliases = aliases or {}
        self._entity_ids = entity_ids
        self._people = people
        self._speaker = speaker  # None for an unknown speaker
        self._uncertain = uncertain

    def _usable(self, hass: HomeAssistant) -> list[str]:
        """The household devices this speaker may use."""
        usable = []
        for entity_id in self._entity_ids:
            if self._speaker is None and is_restricted_entity(hass, entity_id):
                continue
            if any(
                entity_id in p.private
                and (self._speaker is None or p.user_id != self._speaker.user_id)
                for p in self._people
            ):
                continue
            usable.append(entity_id)
        return usable

    def _options(self, hass: HomeAssistant, entity_ids: list[str]) -> list[dict]:
        options = []
        for entity_id, name, area, floor, _, aliases in household_devices(
            hass, entity_ids, self._aliases
        ):
            option: dict[str, Any] = {"entity_id": entity_id, "name": name}
            if aliases:
                option["aliases"] = list(aliases)
            if area:
                option["area"] = area
            if floor:
                option["floor"] = floor
            options.append(option)
        return options

    def _resolve(
        self,
        hass: HomeAssistant,
        llm_context: llm.LLMContext,
        requested: str,
        place: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Pick one device: by name, then by the room named or the speaker's room."""
        usable = self._usable(hass)
        key = requested.strip().casefold()
        if not key:
            return None, {
                "problem": "device_required",
                "message": "Name the household device to use.",
            }
        exact = [e for e in usable if e.casefold() == key]
        if exact:
            return exact[0], None
        wanted = _tokens(key)
        matches = []
        for entity_id in usable:
            state = hass.states.get(entity_id)
            names = (
                state.name if state else "",
                entity_id,
                *device_aliases(hass, entity_id, self._aliases),
            )
            for text in names:
                have = _tokens(text)
                if wanted and all(
                    w in have or any(t.startswith(w) for t in have if len(w) >= 3)
                    for w in wanted
                ):
                    matches.append(entity_id)
                    break
        if not matches:
            return None, {
                "problem": "device_not_found",
                "message": (
                    f"No household device matches {requested!r}. Use the closest "
                    "name from options, or say that there is no such device."
                ),
                "options": self._options(hass, usable),
            }
        if len(matches) > 1:
            matches = self._narrow(hass, llm_context, matches, place)
            if isinstance(matches, dict):
                return None, matches
        if len(matches) == 1:
            return matches[0], None
        return None, {
            "problem": "choose_device",
            "message": (
                "More than one household device matches. Ask the speaker which "
                "one, then call again with its entity_id."
            ),
            "options": self._options(hass, matches),
        }

    def _narrow(
        self,
        hass: HomeAssistant,
        llm_context: llm.LLMContext,
        matches: list[str],
        place: str,
    ) -> list[str] | dict[str, Any]:
        """Keep the matches in the named room or floor, else the speaker's."""
        place = place.strip()
        if place:
            areas, floors = _requested_places(hass, place)
            if not areas and not floors:
                return {
                    "problem": "unknown_area",
                    "message": f"No area or floor is called {place!r}.",
                    "options": self._options(hass, matches),
                }
            in_place = [
                e
                for e in matches
                if (area_id := entity_area_id(hass, e)) in areas
                or _floor_of(hass, area_id) in floors
            ]
            return in_place or matches
        area_id = device_area_id(hass, llm_context.device_id)
        if area_id:
            here = [e for e in matches if entity_area_id(hass, e) == area_id]
            if here:
                return here
            area = ar.async_get(hass).async_get_area(area_id)
            floor_id = area.floor_id if area else None
            same_floor = [
                e
                for e in matches
                if _same_floor(hass, entity_area_id(hass, e), floor_id)
            ]
            if same_floor:
                return same_floor
        return matches


def _floor_of(hass: HomeAssistant, area_id: str | None) -> str | None:
    area = ar.async_get(hass).async_get_area(area_id) if area_id else None
    return area.floor_id if area else None


_NAME_GUIDANCE = (
    "device is the device's common name without its room, such as Air Conditioner, "
    "any of its aliases, or its exact entity_id; use the first alias as its "
    "preferred name in your reply. Leave area out to use the room the speaker is in, "
    "falling back to the same floor; set area only when the speaker names a room "
    "or floor, and then that room wins. If more than one device still matches, "
    "ask the speaker which one."
)


class GetHouseholdDeviceStateTool(_HouseholdTool):
    """Read the state of one household device."""

    name = "get_household_device_state"
    title = "Get household device state"
    description = (
        "Read the current state and attributes of one household device, a shared "
        "device such as an air conditioner that is not assigned to a person. "
        f"{_NAME_GUIDANCE} For a climate device the state is its mode, and the "
        "attributes show its target temperature, fan mode and the modes it supports."
    )
    annotations = _READ_ONLY
    parameters = vol.Schema({vol.Required("device"): str, vol.Optional("area"): str})

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        args = tool_input.tool_args
        entity_id, problem = self._resolve(
            hass,
            llm_context,
            str(args.get("device", "")),
            str(args.get("area", "")),
        )
        if problem:
            return _result(problem, error=True)
        state = hass.states.get(entity_id)
        if state is None:
            return _result(
                {"entity_id": entity_id, "problem": "entity_unavailable"}, error=True
            )
        area, floor = area_names(hass, entity_area_id(hass, entity_id))
        return _result(
            {
                "entity": " ".join(state.name.split()),
                "entity_id": entity_id,
                "state": state.state,
                "attributes": dict(state.attributes),
                **({"area": area} if area else {}),
                **({"floor": floor} if floor else {}),
            }
        )


class ControlHouseholdDeviceTool(_HouseholdTool):
    """Call one Home Assistant service on one household device."""

    name = "control_household_device"
    title = "Control household device"
    description = (
        "Perform a requested Home Assistant action on one household device, a "
        "shared device such as an air conditioner that is not assigned to a person. "
        f"{_NAME_GUIDANCE} service must be a Home Assistant service such as "
        "switch.turn_on or fan.turn_off. For a climate device use "
        "climate.set_hvac_mode with hvac_mode in service_data (for example cool, "
        "heat, off), climate.set_temperature with temperature, "
        "climate.set_fan_mode with fan_mode, climate.set_swing_mode with "
        "swing_mode, or climate.turn_on or turn_off. A value the device does not "
        "support is refused with the valid choices. Never include entity_id, "
        "device_id, area_id, floor_id, label_id or target in service_data. "
        "Calendars are not household devices. Some actions, such as unlocking or "
        "opening a garage door or gate, return a preview and confirmation_token "
        "first without changing anything. Ask the speaker, and only after an "
        "explicit yes call again with the same request, that confirmation_token "
        "and confirmed=true. Report the returned state accurately; a successful "
        "service call does not guarantee the device reached that state."
    )
    annotations = _WRITE
    parameters = vol.Schema(
        {
            vol.Required("device"): str,
            vol.Required("service"): str,
            vol.Optional("service_data"): dict,
            vol.Optional("area"): str,
            vol.Optional("confirmation_token"): str,
            vol.Optional("confirmed"): bool,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        args = tool_input.tool_args
        entity_id, problem = self._resolve(
            hass,
            llm_context,
            str(args.get("device", "")),
            str(args.get("area", "")),
        )
        if problem:
            return _result(problem, error=True)
        state = hass.states.get(entity_id)
        label = " ".join((state.name if state else entity_id).split())
        checked, problem = check_service(hass, entity_id, args)
        if problem:
            return _result(problem, error=True)
        service, service_domain, service_name, service_data = checked
        problem = validate_climate(hass, entity_id, service_name, service_data)
        if problem:
            return _result({"entity": label, **problem}, error=True)
        if (
            self._uncertain and self._speaker is not None
        ) or sensitive_action_needs_confirmation(
            hass, entity_id, service_domain, service_name
        ):
            note = None
            if self._uncertain and self._speaker is not None:
                note = (
                    "Speaker recognition was not confident that this is "
                    f"{self._speaker.direct_address}. Before asking whether to "
                    "go ahead, ask them to confirm who they are."
                )
            staged = _confirm_change(
                hass,
                args,
                llm_context,
                action=self.name,
                plan={
                    "entity_id": entity_id,
                    "service": service,
                    "service_data": service_data,
                },
                preview={
                    "entity": label,
                    "service": service,
                    **({"service_data": service_data} if service_data else {}),
                },
                extra_note=note,
            )
            if staged is not None:
                return staged
        before = hass.states.get(entity_id)
        try:
            await hass.services.async_call(
                service_domain,
                service_name,
                {**service_data, "entity_id": entity_id},
                context=llm_context.context,
                blocking=True,
            )
        except (HomeAssistantError, ValueError) as err:
            return _result(
                {
                    "entity": label,
                    "entity_id": entity_id,
                    "service": service,
                    "error": str(err),
                },
                error=True,
            )
        return _result(
            {
                "entity": label,
                "entity_id": entity_id,
                "service": service,
                "service_called": True,
                **await state_after_call(
                    hass, entity_id, before, service_name, service_data
                ),
            }
        )


def build_household_tools(
    entity_ids: list[str],
    people: list[Person],
    speaker: Person | None,
    *,
    uncertain: bool = False,
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> list[llm.Tool]:
    """Return the household device tools, or none when no devices are configured."""
    if not entity_ids:
        return []
    return [
        GetHouseholdDeviceStateTool(
            entity_ids, people, speaker, uncertain=uncertain, aliases=aliases
        ),
        ControlHouseholdDeviceTool(
            entity_ids, people, speaker, uncertain=uncertain, aliases=aliases
        ),
    ]

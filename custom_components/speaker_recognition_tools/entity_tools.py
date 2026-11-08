"""Tools that read and control one entity assigned to a person."""

from __future__ import annotations

import asyncio
from typing import Any

import probatio as vol
from homeassistant.core import Event, HomeAssistant, State, callback
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
    llm,
)
from homeassistant.helpers.event import async_track_state_change_event

from .tool_base import (
    _READ_ONLY,
    _WRITE,
    LOCATION_DOMAINS,
    _PersonTool,
    _result,
)

# Actions on these always need a spoken yes, except the ones that make things
# more secure. Covers count only when they are a door, gate or garage door.
_ALWAYS_CONFIRM_DOMAINS = ("lock", "alarm_control_panel", "cover")
_SECURING_SERVICES = {
    "lock": {"lock"},
    "alarm_control_panel": {
        "alarm_arm_away",
        "alarm_arm_custom_bypass",
        "alarm_arm_home",
        "alarm_arm_night",
        "alarm_arm_vacation",
    },
    "cover": {"close_cover", "close_cover_tilt", "stop_cover", "stop_cover_tilt"},
}
_SENSITIVE_COVER_CLASSES = ("door", "garage", "gate")


def _needs_confirmation(
    hass: HomeAssistant, person, entity_id: str, service_domain: str, service: str
) -> bool:
    """Whether this action must be previewed and confirmed before it runs."""
    if entity_id in person.confirm:
        return True
    return sensitive_action_needs_confirmation(hass, entity_id, service_domain, service)


def is_restricted_entity(hass: HomeAssistant, entity_id: str) -> bool:
    """Whether this entity is a lock, alarm panel, door, gate or garage door, or a calendar.

    An entity whose cover type cannot be read counts as restricted.
    """
    domain = entity_id.split(".", 1)[0]
    if domain in ("calendar", "lock", "alarm_control_panel"):
        return True
    if domain == "cover":
        state = hass.states.get(entity_id)
        device_class = state.attributes.get("device_class") if state else None
        return state is None or device_class in _SENSITIVE_COVER_CLASSES
    return False


def sensitive_action_needs_confirmation(
    hass: HomeAssistant, entity_id: str, service_domain: str, service: str
) -> bool:
    """Whether the built-in rules make this action need a spoken yes."""
    domain = entity_id.split(".", 1)[0]
    if domain not in _ALWAYS_CONFIRM_DOMAINS:
        return False
    if domain == "cover":
        state = hass.states.get(entity_id)
        device_class = state.attributes.get("device_class") if state else None
        if state is not None and device_class not in _SENSITIVE_COVER_CLASSES:
            return False
    return not (
        service_domain == domain and service in _SECURING_SERVICES.get(domain, ())
    )


_RESERVED_SERVICE_DATA = {
    "entity_id",
    "device_id",
    "area_id",
    "floor_id",
    "label_id",
    "target",
}


def check_service(
    hass: HomeAssistant, entity_id: str, args: dict[str, Any]
) -> tuple[tuple[str, str, str, dict] | None, dict[str, Any] | None]:
    """Check the requested service for one entity.

    Returns ((service, domain, name, service_data), None), or (None, problem).
    """
    entity_domain = entity_id.split(".", 1)[0]
    service = str(args.get("service", "")).strip().lower()
    parts = service.split(".")
    if len(parts) != 2 or not all(parts):
        return None, {
            "problem": "invalid_service",
            "message": "Use a domain.service name.",
        }
    service_domain, service_name = parts
    if entity_domain == "calendar":
        return None, {
            "problem": "use_calendar_tools",
            "message": "Use the calendar tools for calendar events.",
        }
    if service_domain == "homeassistant":
        if service_name not in {"turn_on", "turn_off", "toggle"}:
            return None, {
                "problem": "service_not_allowed",
                "message": (
                    "Only homeassistant.turn_on, turn_off, and toggle can "
                    "target an assigned entity."
                ),
            }
    elif service_domain != entity_domain:
        return None, {
            "problem": "service_domain_mismatch",
            "message": "The service must belong to the entity's domain.",
        }
    service_data = args.get("service_data") or {}
    if not isinstance(service_data, dict):
        return None, {
            "problem": "invalid_service_data",
            "message": "service_data must be an object.",
        }
    if _RESERVED_SERVICE_DATA.intersection(service_data):
        return None, {
            "problem": "target_override",
            "message": "service_data cannot select additional entities or targets.",
        }
    if not hass.services.has_service(service_domain, service_name):
        return None, {"problem": "unknown_service", "service": service}
    return (service, service_domain, service_name, service_data), None


def _normal(value: Any) -> str:
    return str(value).strip().casefold().replace(" ", "_").replace("-", "_")


# service -> (service_data field, state attribute listing the supported values)
_CLIMATE_CHOICES = {
    "set_hvac_mode": ("hvac_mode", "hvac_modes"),
    "set_fan_mode": ("fan_mode", "fan_modes"),
    "set_swing_mode": ("swing_mode", "swing_modes"),
    "set_swing_horizontal_mode": ("swing_horizontal_mode", "swing_horizontal_modes"),
    "set_preset_mode": ("preset_mode", "preset_modes"),
    "set_temperature": ("hvac_mode", "hvac_modes"),
}
_CLIMATE_TEMPERATURES = ("temperature", "target_temp_high", "target_temp_low")


def validate_climate(
    hass: HomeAssistant, entity_id: str, service_name: str, service_data: dict
) -> dict[str, Any] | None:
    """Check a climate request against what the unit supports.

    Matches modes without regard to case or spaces, fixing them in service_data.
    Returns a problem naming the valid choices, or None.
    """
    if not entity_id.startswith("climate."):
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    choice = _CLIMATE_CHOICES.get(service_name)
    if choice and choice[0] in service_data:
        field, attribute = choice
        supported = state.attributes.get(attribute)
        if isinstance(supported, list) and supported:
            wanted = _normal(service_data[field])
            match = next((v for v in supported if _normal(v) == wanted), None)
            if match is None:
                return {
                    "problem": "unsupported_value",
                    "field": field,
                    "value": service_data[field],
                    "supported": supported,
                    "message": (
                        f"{service_data[field]!r} is not a supported {field}. "
                        f"Choose one of: {', '.join(map(str, supported))}."
                    ),
                }
            service_data[field] = match
    if service_name == "set_temperature":
        low, high = state.attributes.get("min_temp"), state.attributes.get("max_temp")
        for field in _CLIMATE_TEMPERATURES:
            if field not in service_data:
                continue
            try:
                value = float(service_data[field])
            except (TypeError, ValueError):
                return {
                    "problem": "invalid_temperature",
                    "field": field,
                    "message": f"{field} must be a number.",
                }
            if (isinstance(low, (int, float)) and value < low) or (
                isinstance(high, (int, float)) and value > high
            ):
                return {
                    "problem": "temperature_out_of_range",
                    "field": field,
                    "value": service_data[field],
                    "min_temp": low,
                    "max_temp": high,
                    "message": (
                        f"{field} must be between {low} and {high} "
                        f"{state.attributes.get('temperature_unit', '')}".strip()
                        + "."
                    ),
                }
            service_data[field] = value
    return None


_CLIMATE_RESULT_ATTRIBUTES = (
    "temperature",
    "target_temp_high",
    "target_temp_low",
    "current_temperature",
    "hvac_action",
    "fan_mode",
    "swing_mode",
    "preset_mode",
)


def state_after(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """Report the entity's state after an action; climate also shows its settings."""
    state = hass.states.get(entity_id)
    if state is None:
        return {}
    result: dict[str, Any] = {"state_after": state.state}
    if entity_id.startswith("climate."):
        result["settings_after"] = {
            "hvac_mode": state.state,
            **{
                key: state.attributes[key]
                for key in _CLIMATE_RESULT_ATTRIBUTES
                if state.attributes.get(key) is not None
            },
        }
    return result


# How long to wait for a unit to report its new state after a service call. Cloud
# or network-backed units often answer the call before they report the change.
STATE_SETTLE_TIMEOUT = 5.0

_EXPECTED_STATES = {
    "turn_on": "on",
    "turn_off": "off",
    "lock": "locked",
    "unlock": "unlocked",
}
_CHECKED_ATTRIBUTES = (
    "temperature",
    "target_temp_high",
    "target_temp_low",
    "fan_mode",
    "swing_mode",
    "preset_mode",
)


def _expectations(
    service_name: str, service_data: dict[str, Any]
) -> tuple[str | None, dict[str, Any]]:
    """The state and attributes the call should lead to, where they can be known."""
    state = _EXPECTED_STATES.get(service_name)
    if service_name == "set_hvac_mode":
        state = service_data.get("hvac_mode")
    attributes = {
        key: service_data[key] for key in _CHECKED_ATTRIBUTES if key in service_data
    }
    return state, attributes


def _matches(
    state: State | None, expected_state: str | None, attributes: dict[str, Any]
) -> bool:
    if state is None:
        return False
    if expected_state is not None and state.state != expected_state:
        return False
    return all(state.attributes.get(key) == value for key, value in attributes.items())


async def wait_for_state(
    hass: HomeAssistant,
    entity_id: str,
    before: State | None,
    service_name: str,
    service_data: dict[str, Any],
) -> bool:
    """Wait for the entity to show the result of a call; False if it never does.

    When the expected result is known (turn_on, set_hvac_mode, set_temperature and so
    on) it returns at once if the unit already shows it, otherwise when it does.
    For any other call it returns once the entity changes from `before`.
    """
    expected_state, attributes = _expectations(service_name, service_data)
    known = expected_state is not None or bool(attributes)
    current = hass.states.get(entity_id)
    if known:
        if _matches(current, expected_state, attributes):
            return True
    elif current is not before:
        return True
    settled = asyncio.Event()

    @callback
    def _changed(event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if not known or _matches(new_state, expected_state, attributes):
            settled.set()

    unsubscribe = async_track_state_change_event(hass, [entity_id], _changed)
    try:
        async with asyncio.timeout(STATE_SETTLE_TIMEOUT):
            await settled.wait()
    except TimeoutError:
        return False
    finally:
        unsubscribe()
    return True


async def state_after_call(
    hass: HomeAssistant,
    entity_id: str,
    before: State | None,
    service_name: str,
    service_data: dict[str, Any],
) -> dict[str, Any]:
    """Report the state after a call, waiting briefly for a slow unit to report it."""
    confirmed = await wait_for_state(hass, entity_id, before, service_name, service_data)
    result = state_after(hass, entity_id)
    if not confirmed:
        result["state_confirmed"] = False
        result["note"] = (
            "The command was sent, but the unit has not reported a change yet; "
            "some units take a few seconds. Do not say the command failed. Say it "
            "was sent and is not confirmed yet, and offer to check again."
        )
    return result


class GetEntityStateTool(_PersonTool):
    """Read the state and attributes of one entity assigned to a person."""

    name = "get_entity_state"
    title = "Get assigned entity state"
    description = (
        "Read the current state and attributes of one assigned entity, such as a fuel "
        "sensor or device tracker. The required entity accepts its exact entity_id, "
        "configured name, or alias; the first alias is the preferred name to use in "
        "your reply. Optional person accepts a first name, configured form of address, "
        "or configured third-person reference and defaults to the current speaker. "
        "Only read entities "
        "assigned to that person; private entities can only be read by their owner. "
        "A person's person entity and trackers are not readable when their location is private. "
        "For a linked device, its spoken name or any alias resolves to the status entity here. "
        "The result may include its configured Home Assistant area and state attributes. "
        "Use get_person_location for a person's presence, zones and addresses, "
        "get_device_location for where a phone or tracked device is, and "
        "calendar tools for calendar events. Do not infer a room from a home state alone."
    )
    annotations = _READ_ONLY
    parameters = vol.Schema({vol.Required("entity"): str, vol.Optional("person"): str})

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        args = tool_input.tool_args
        person, problems = self._entity_person(args)
        if problems:
            return _result({"problems": problems}, error=True)
        target, problem = self._entity_for_operation(
            person, str(args.get("entity", "")), "read"
        )
        if problem:
            return _result(problem, error=True)
        entity_id, label, _ = target
        if entity_id.split(".", 1)[0] in LOCATION_DOMAINS and (
            self.household.location_hidden(person)
        ):
            return _result(self.household.location_denial(person), error=True)
        state = hass.states.get(entity_id)
        if state is None:
            return _result(
                {
                    "entity": label,
                    "entity_id": entity_id,
                    "problem": "entity_unavailable",
                },
                error=True,
            )

        attributes = dict(state.attributes)
        # Do not let the entity's HA name override its configured preferred alias.
        if "friendly_name" in attributes:
            attributes["friendly_name"] = label
        result: dict[str, Any] = {
            "person": self.household.reference(person),
            "entity": label,
            "entity_id": entity_id,
            "state": state.state,
            "attributes": attributes,
        }
        registry_entry = er.async_get(hass).async_get(entity_id)
        area_id = registry_entry.area_id if registry_entry else None
        if registry_entry and not area_id and registry_entry.device_id:
            device = dr.async_get(hass).async_get(registry_entry.device_id)
            if device:
                area_id = dr.async_get_effective_area_id(hass, device)
        if area_id and (area := ar.async_get(hass).async_get_area(area_id)):
            result["area"] = area.name
        return _result(result)


class ControlAssignedEntityTool(_PersonTool):
    """Call one Home Assistant service on one entity assigned to a person."""

    name = "control_assigned_entity"
    title = "Control assigned entity"
    description = (
        "Perform a requested Home Assistant action on one assigned entity. entity "
        "accepts its exact entity_id, configured name, or alias; use the first alias "
        "as its preferred name in your reply. service must be a Home Assistant "
        "service such as button.press, switch.turn_on, light.turn_off, or "
        "homeassistant.turn_on. For a climate entity use climate.set_hvac_mode with "
        "hvac_mode in service_data (for example cool, heat, off), "
        "climate.set_temperature with temperature, climate.set_fan_mode with fan_mode, "
        "climate.set_swing_mode with swing_mode, or climate.turn_on or turn_off; "
        "read its state first to see the hvac_modes, fan_modes and temperature "
        "range it supports. Supply service-specific fields in service_data. "
        "Only entities assigned to the selected person may be controlled. For a "
        "linked device, its spoken name or any alias resolves to the action entity here. The "
        "optional person parameter accepts a first name, configured form of address, or configured "
        "third-person reference and defaults to the current speaker. Private entities can only be "
        "controlled by their owner. The service is always targeted to that one entity; "
        "never include entity_id, device_id, area_id, floor_id, label_id, or target in "
        "service_data. Calendar changes must use the calendar tools and their preview "
        "and confirmation flow. Some actions, such as unlocking, disarming, opening a "
        "garage door or gate, or using an entity the household marked as needing "
        "confirmation, return a preview and confirmation_token first without "
        "changing anything. Ask the speaker, and only after an explicit yes call "
        "again with the same request, that confirmation_token and confirmed=true. "
        "Some entities can only be controlled by administrators. Report the "
        "returned state accurately; a successful service call does not guarantee "
        "the device reached that state."
    )
    annotations = _WRITE
    parameters = vol.Schema(
        {
            vol.Required("entity"): str,
            vol.Required("service"): str,
            vol.Optional("service_data"): dict,
            vol.Optional("person"): str,
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
        person, problems = self._entity_person(args)
        if problems:
            return _result({"problems": problems}, error=True)
        target, problem = self._entity_for_operation(
            person, str(args.get("entity", "")), "control"
        )
        if problem:
            return _result(problem, error=True)
        entity_id, label, _ = target
        if entity_id in person.admin_only and not self.household.speaker.is_admin:
            return _result(
                {
                    "entity": label,
                    "problem": "admin_only",
                    "message": f"Only an administrator can control {label}.",
                },
                error=True,
            )
        checked, problem = check_service(hass, entity_id, args)
        if problem:
            return _result(problem, error=True)
        service, service_domain, service_name, service_data = checked
        problem = validate_climate(hass, entity_id, service_name, service_data)
        if problem:
            return _result({"entity": label, **problem}, error=True)
        if self.household.uncertain or _needs_confirmation(
            hass, person, entity_id, service_domain, service_name
        ):
            staged = self._confirm(
                hass,
                args,
                llm_context,
                action=self.name,
                plan={
                    "person": person.user_id,
                    "entity_id": entity_id,
                    "service": service,
                    "service_data": service_data,
                },
                preview={
                    "person": self.household.reference(person),
                    "entity": label,
                    "service": service,
                    **({"service_data": service_data} if service_data else {}),
                },
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
                "person": self.household.reference(person),
                "entity": label,
                "entity_id": entity_id,
                "service": service,
                "service_called": True,
                **await state_after_call(
                    hass, entity_id, before, service_name, service_data
                ),
            }
        )

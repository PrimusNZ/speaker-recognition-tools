"""Tools that read and control one entity assigned to a person."""

from __future__ import annotations

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
    llm,
)

from .tool_base import _READ_ONLY, _WRITE, _PersonTool, _result

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
        "service such as button.press, switch.turn_on, light.turn_off, climate.set_temperature, "
        "or homeassistant.turn_on. Supply service-specific fields in service_data. "
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
        entity_domain = entity_id.split(".", 1)[0]
        service = str(args.get("service", "")).strip().lower()
        parts = service.split(".")
        if len(parts) != 2 or not all(parts):
            return _result(
                {"problem": "invalid_service", "message": "Use a domain.service name."},
                error=True,
            )
        service_domain, service_name = parts
        if entity_domain == "calendar":
            return _result(
                {
                    "problem": "use_calendar_tools",
                    "message": "Use the calendar tools for calendar events.",
                },
                error=True,
            )
        if service_domain == "homeassistant":
            if service_name not in {"turn_on", "turn_off", "toggle"}:
                return _result(
                    {
                        "problem": "service_not_allowed",
                        "message": (
                            "Only homeassistant.turn_on, turn_off, and toggle can "
                            "target an assigned entity."
                        ),
                    },
                    error=True,
                )
        elif service_domain != entity_domain:
            return _result(
                {
                    "problem": "service_domain_mismatch",
                    "message": "The service must belong to the entity's domain.",
                },
                error=True,
            )
        service_data = args.get("service_data") or {}
        if not isinstance(service_data, dict):
            return _result(
                {
                    "problem": "invalid_service_data",
                    "message": "service_data must be an object.",
                },
                error=True,
            )
        reserved = {
            "entity_id",
            "device_id",
            "area_id",
            "floor_id",
            "label_id",
            "target",
        }
        if reserved.intersection(service_data):
            return _result(
                {
                    "problem": "target_override",
                    "message": "service_data cannot select additional entities or targets.",
                },
                error=True,
            )
        if not hass.services.has_service(service_domain, service_name):
            return _result(
                {"problem": "unknown_service", "service": service}, error=True
            )
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
        state = hass.states.get(entity_id)
        return _result(
            {
                "person": self.household.reference(person),
                "entity": label,
                "entity_id": entity_id,
                "service": service,
                "service_called": True,
                **({"state_after": state.state} if state else {}),
            }
        )

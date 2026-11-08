"""Tests for reading and controlling assigned entities."""

from __future__ import annotations

import asyncio

from homeassistant.core import ServiceCall
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    llm,
)

from custom_components.speaker_recognition_tools import (
    entity_tools,
    tool_base,
)
from custom_components.speaker_recognition_tools.prompt import Person
from tests.tools.helpers import (
    instance,
)


def _assigned_entity_tools(user, *, private=(), aliases=("Demo unit",)):
    person = Person(
        user.id,
        "James",
        "Dad",
        (("switch.demo_device", "Demo device"),),
        frozenset(private),
        entity_aliases=(("switch.demo_device", tuple(aliases)),),
    )
    household = tool_base.Household([person], person)
    return person, household


async def _call_entity_tool(hass, user, tool, **args):
    api_instance = await instance(hass, user)
    result = await tool.async_call(
        hass,
        llm.ToolInput(tool_name=tool.name, tool_args=args),
        api_instance.llm_context,
    )
    return result.data, result.error


async def test_get_entity_state_resolves_alias_and_returns_area(hass, users) -> None:
    area = ar.async_get(hass).async_create("Office")
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "switch", "test", "demo-device", suggested_object_id="demo_device"
    )
    registry.async_update_entity("switch.demo_device", area_id=area.id)
    hass.states.async_set(
        "switch.demo_device", "off", {"friendly_name": "Demo device", "power": "off"}
    )
    _, household = _assigned_entity_tools(users["James"])
    tool = entity_tools.GetEntityStateTool(household)

    result, error = await _call_entity_tool(
        hass, users["James"], tool, entity="demo unit"
    )

    assert not error
    assert result["entity"] == "Demo unit"
    assert result["entity_id"] == "switch.demo_device"
    assert result["state"] == "off"
    assert result["attributes"] == {"friendly_name": "Demo unit", "power": "off"}
    assert result["area"] == "Office"


async def test_control_assigned_entity_calls_service_only_for_target(
    hass, users
) -> None:
    hass.states.async_set("switch.demo_device", "off")
    calls = []

    async def turn_on(call: ServiceCall) -> None:
        calls.append(dict(call.data))
        hass.states.async_set(call.data["entity_id"], "on")

    hass.services.async_register("switch", "turn_on", turn_on)
    _, household = _assigned_entity_tools(users["James"])
    tool = entity_tools.ControlAssignedEntityTool(household)

    result, error = await _call_entity_tool(
        hass, users["James"], tool, entity="Demo unit", service="switch.turn_on"
    )

    assert not error
    assert calls == [{"entity_id": "switch.demo_device"}]
    assert result["entity"] == "Demo unit"
    assert result["service_called"] is True
    assert result["state_after"] == "on"


async def test_control_assigned_entity_rejects_unassigned_target(hass, users) -> None:
    _, household = _assigned_entity_tools(users["James"])
    tool = entity_tools.ControlAssignedEntityTool(household)

    result, error = await _call_entity_tool(
        hass,
        users["James"],
        tool,
        entity="light.lamp",
        service="light.turn_on",
    )

    assert error
    assert result["problem"] == "entity_not_assigned"


async def test_control_assigned_entity_rejects_service_target_override(
    hass, users
) -> None:
    _, household = _assigned_entity_tools(users["James"])
    tool = entity_tools.ControlAssignedEntityTool(household)

    result, error = await _call_entity_tool(
        hass,
        users["James"],
        tool,
        entity="Demo unit",
        service="switch.turn_on",
        service_data={"entity_id": "switch.other"},
    )

    assert error
    assert result["problem"] == "target_override"


async def test_entity_tools_refuse_another_persons_private_entity(hass, users) -> None:
    speaker = Person(users["Sarah"].id, "Sarah", "Mum")
    owner = Person(
        users["James"].id,
        "James",
        "Dad",
        (("switch.demo_device", "Demo device"),),
        frozenset({"switch.demo_device"}),
        entity_aliases=(("switch.demo_device", ("Demo unit",)),),
    )
    household = tool_base.Household([speaker, owner], speaker)
    read_tool = entity_tools.GetEntityStateTool(household)
    control_tool = entity_tools.ControlAssignedEntityTool(household)

    read_result, read_error = await _call_entity_tool(
        hass, users["Sarah"], read_tool, person="Dad", entity="Demo unit"
    )
    write_result, write_error = await _call_entity_tool(
        hass,
        users["Sarah"],
        control_tool,
        person="Dad",
        entity="Demo unit",
        service="switch.turn_on",
    )

    assert read_error and read_result["problem"] == "private"
    assert write_error and write_result["problem"] == "private"


async def test_entity_control_cannot_bypass_calendar_confirmation(hass, users) -> None:
    person = Person(
        users["James"].id, "James", "Dad", (("calendar.james", "James Calendar"),)
    )
    household = tool_base.Household([person], person)
    tool = entity_tools.ControlAssignedEntityTool(household)

    result, error = await _call_entity_tool(
        hass,
        users["James"],
        tool,
        entity="calendar.james",
        service="calendar.create_event",
    )

    assert error
    assert result["problem"] == "use_calendar_tools"


async def test_linked_device_routes_same_name_to_status_and_action_entities(
    hass, users
) -> None:
    hass.states.async_set("binary_sensor.demo_unit_status", "off")
    hass.states.async_set("button.demo_unit_action", "unknown")
    calls = []

    async def press(call: ServiceCall) -> None:
        calls.append(dict(call.data))

    hass.services.async_register("button", "press", press)
    person = Person(
        users["James"].id,
        "James",
        "Dad",
        entity_links=(
            (
                "Demo unit",
                "binary_sensor.demo_unit_status",
                "button.demo_unit_action",
                False,
                ("Lab station", "Test console"),
            ),
        ),
    )
    household = tool_base.Household([person], person)
    read_tool = entity_tools.GetEntityStateTool(household)
    control_tool = entity_tools.ControlAssignedEntityTool(household)

    state_result, state_error = await _call_entity_tool(
        hass, users["James"], read_tool, entity="Lab station"
    )
    action_result, action_error = await _call_entity_tool(
        hass,
        users["James"],
        control_tool,
        entity="Test console",
        service="button.press",
    )

    assert not state_error
    assert state_result["entity_id"] == "binary_sensor.demo_unit_status"
    assert state_result["entity"] == "Demo unit"
    assert state_result["state"] == "off"
    assert not action_error
    assert calls == [{"entity_id": "button.demo_unit_action"}]
    assert action_result["entity_id"] == "button.demo_unit_action"


async def test_private_linked_device_is_only_available_to_its_owner(
    hass, users
) -> None:
    speaker = Person(users["Sarah"].id, "Sarah", "Mum")
    owner = Person(
        users["James"].id,
        "James",
        "Dad",
        entity_links=(
            (
                "Demo unit",
                "binary_sensor.demo_unit_status",
                "button.demo_unit_action",
                True,
                ("Lab station", "Test console"),
            ),
        ),
    )
    household = tool_base.Household([speaker, owner], speaker)
    tool = entity_tools.GetEntityStateTool(household)

    result, error = await _call_entity_tool(
        hass, users["Sarah"], tool, person="Dad", entity="Lab station"
    )

    assert error
    assert result["problem"] == "private"


def _guarded_tools(user, entity_id, *, confirm=(), admin_only=(), is_admin=False):
    person = Person(
        user.id,
        "James",
        "Dad",
        ((entity_id, "Front door"),),
        is_admin=is_admin,
        confirm=frozenset(confirm),
        admin_only=frozenset(admin_only),
    )
    household = tool_base.Household([person], person)
    return entity_tools.ControlAssignedEntityTool(household)


def _record_service(hass, domain: str, service: str) -> list[dict]:
    calls: list[dict] = []

    async def handler(call: ServiceCall) -> None:
        calls.append(dict(call.data))

    hass.services.async_register(domain, service, handler)
    return calls


async def test_unlocking_needs_confirmation_before_the_service_runs(
    hass, users
) -> None:
    hass.states.async_set("lock.front_door", "locked")
    calls = _record_service(hass, "lock", "unlock")
    tool = _guarded_tools(users["James"], "lock.front_door")
    args = {"entity": "Front door", "service": "lock.unlock"}

    preview, error = await _call_entity_tool(hass, users["James"], tool, **args)
    assert not error
    assert preview["confirmation_required"] is True
    assert preview["preview"] == {
        "person": "Dad",
        "entity": "Front door",
        "service": "lock.unlock",
    }
    assert calls == []

    result, error = await _call_entity_tool(
        hass,
        users["James"],
        tool,
        **args,
        confirmation_token=preview["confirmation_token"],
        confirmed=True,
    )
    assert not error
    assert result["service_called"] is True
    assert calls == [{"entity_id": "lock.front_door"}]


async def test_declined_confirmation_makes_no_change(hass, users) -> None:
    hass.states.async_set("lock.front_door", "locked")
    calls = _record_service(hass, "lock", "unlock")
    tool = _guarded_tools(users["James"], "lock.front_door")
    args = {"entity": "Front door", "service": "lock.unlock"}
    preview, _ = await _call_entity_tool(hass, users["James"], tool, **args)

    result, error = await _call_entity_tool(
        hass,
        users["James"],
        tool,
        **args,
        confirmation_token=preview["confirmation_token"],
        confirmed=False,
    )
    assert not error
    assert result["cancelled"] is True
    assert calls == []


async def test_confirmation_must_match_the_previewed_action(hass, users) -> None:
    hass.states.async_set("lock.front_door", "locked")
    calls = _record_service(hass, "lock", "open")
    _record_service(hass, "lock", "unlock")
    tool = _guarded_tools(users["James"], "lock.front_door")
    preview, _ = await _call_entity_tool(
        hass, users["James"], tool, entity="Front door", service="lock.unlock"
    )

    result, error = await _call_entity_tool(
        hass,
        users["James"],
        tool,
        entity="Front door",
        service="lock.open",
        confirmation_token=preview["confirmation_token"],
        confirmed=True,
    )
    assert error
    assert "differs from the preview" in result["error"]
    assert calls == []


async def test_another_speaker_cannot_use_the_confirmation(hass, users) -> None:
    hass.states.async_set("lock.front_door", "locked")
    calls = _record_service(hass, "lock", "unlock")
    tool = _guarded_tools(users["James"], "lock.front_door")
    args = {"entity": "Front door", "service": "lock.unlock"}
    preview, _ = await _call_entity_tool(hass, users["James"], tool, **args)

    result, error = await _call_entity_tool(
        hass,
        users["Sarah"],
        tool,
        **args,
        confirmation_token=preview["confirmation_token"],
        confirmed=True,
    )
    assert error
    assert "does not match this speaker" in result["error"]
    assert calls == []


async def test_securing_actions_run_without_confirmation(hass, users) -> None:
    hass.states.async_set("lock.front_door", "unlocked")
    calls = _record_service(hass, "lock", "lock")
    tool = _guarded_tools(users["James"], "lock.front_door")
    result, error = await _call_entity_tool(
        hass, users["James"], tool, entity="Front door", service="lock.lock"
    )
    assert not error
    assert result["service_called"] is True
    assert calls == [{"entity_id": "lock.front_door"}]


async def test_disarming_an_alarm_needs_confirmation(hass, users) -> None:
    hass.states.async_set("alarm_control_panel.house", "armed_away")
    _record_service(hass, "alarm_control_panel", "alarm_disarm")
    tool = _guarded_tools(users["James"], "alarm_control_panel.house")
    preview, error = await _call_entity_tool(
        hass,
        users["James"],
        tool,
        entity="Front door",
        service="alarm_control_panel.alarm_disarm",
        service_data={"code": "1234"},
    )
    assert not error
    assert preview["confirmation_required"] is True
    assert preview["preview"]["service_data"] == {"code": "1234"}


async def test_garage_door_needs_confirmation_but_blinds_do_not(hass, users) -> None:
    hass.states.async_set("cover.garage", "closed", {"device_class": "garage"})
    hass.states.async_set("cover.blind", "closed", {"device_class": "blind"})
    _record_service(hass, "cover", "open_cover")

    garage = _guarded_tools(users["James"], "cover.garage")
    preview, _ = await _call_entity_tool(
        hass, users["James"], garage, entity="Front door", service="cover.open_cover"
    )
    assert preview["confirmation_required"] is True

    blind = _guarded_tools(users["James"], "cover.blind")
    result, error = await _call_entity_tool(
        hass, users["James"], blind, entity="Front door", service="cover.open_cover"
    )
    assert not error
    assert result["service_called"] is True


async def test_marked_entity_needs_confirmation_for_any_action(hass, users) -> None:
    hass.states.async_set("switch.heater", "off")
    _record_service(hass, "switch", "turn_off")
    tool = _guarded_tools(users["James"], "switch.heater", confirm=["switch.heater"])
    preview, error = await _call_entity_tool(
        hass, users["James"], tool, entity="Front door", service="switch.turn_off"
    )
    assert not error
    assert preview["confirmation_required"] is True


async def test_admin_only_entity_refuses_other_speakers(hass, users) -> None:
    hass.states.async_set("switch.heater", "off")
    calls = _record_service(hass, "switch", "turn_on")
    tool = _guarded_tools(
        users["James"], "switch.heater", admin_only=["switch.heater"], is_admin=False
    )
    result, error = await _call_entity_tool(
        hass, users["James"], tool, entity="Front door", service="switch.turn_on"
    )
    assert error
    assert result["problem"] == "admin_only"
    assert calls == []


async def test_admin_only_entity_works_for_administrators(hass, users) -> None:
    hass.states.async_set("switch.heater", "off")
    calls = _record_service(hass, "switch", "turn_on")
    tool = _guarded_tools(
        users["James"], "switch.heater", admin_only=["switch.heater"], is_admin=True
    )
    result, error = await _call_entity_tool(
        hass, users["James"], tool, entity="Front door", service="switch.turn_on"
    )
    assert not error
    assert calls == [{"entity_id": "switch.heater"}]


async def test_admin_only_entity_can_still_be_read(hass, users) -> None:
    hass.states.async_set("switch.heater", "off")
    person = Person(
        users["James"].id,
        "James",
        "Dad",
        (("switch.heater", "Heater"),),
        admin_only=frozenset({"switch.heater"}),
    )
    tool = entity_tools.GetEntityStateTool(tool_base.Household([person], person))
    result, error = await _call_entity_tool(hass, users["James"], tool, entity="Heater")
    assert not error
    assert result["state"] == "off"


async def test_control_assigned_climate_refuses_unsupported_mode_with_choices(
    hass, users
) -> None:
    hass.states.async_set(
        "climate.demo_device",
        "off",
        {"hvac_modes": ["off", "cool"], "min_temp": 16, "max_temp": 30},
    )
    calls = []

    async def set_mode(call: ServiceCall) -> None:
        calls.append(dict(call.data))
        hass.states.async_set(call.data["entity_id"], call.data["hvac_mode"])

    hass.services.async_register("climate", "set_hvac_mode", set_mode)
    person = Person(
        users["James"].id, "James", "Dad", (("climate.demo_device", "Demo unit"),)
    )
    tool = entity_tools.ControlAssignedEntityTool(tool_base.Household([person], person))

    result, error = await _call_entity_tool(
        hass,
        users["James"],
        tool,
        entity="Demo unit",
        service="climate.set_hvac_mode",
        service_data={"hvac_mode": "heat"},
    )
    assert error and result["problem"] == "unsupported_value"
    assert result["supported"] == ["off", "cool"]
    assert not calls

    result, error = await _call_entity_tool(
        hass,
        users["James"],
        tool,
        entity="Demo unit",
        service="climate.set_hvac_mode",
        service_data={"hvac_mode": "Cool"},
    )
    assert not error
    assert calls == [{"entity_id": "climate.demo_device", "hvac_mode": "cool"}]
    assert result["settings_after"] == {"hvac_mode": "cool"}


async def test_state_after_call_waits_for_a_slow_unit_to_report(hass, monkeypatch):
    monkeypatch.setattr(entity_tools, "STATE_SETTLE_TIMEOUT", 2.0)
    hass.states.async_set("climate.unit", "cool", {"fan_mode": "high"})
    before = hass.states.get("climate.unit")

    async def report_late() -> None:
        await asyncio.sleep(0.05)
        hass.states.async_set("climate.unit", "off", {"fan_mode": "high"})

    task = hass.async_create_task(report_late())
    result = await entity_tools.state_after_call(
        hass, "climate.unit", before, "turn_off", {}
    )
    await task

    assert result["state_after"] == "off"
    assert result["settings_after"]["hvac_mode"] == "off"
    assert "state_confirmed" not in result


async def test_state_after_call_flags_a_unit_that_never_reports(hass, monkeypatch):
    monkeypatch.setattr(entity_tools, "STATE_SETTLE_TIMEOUT", 0.05)
    hass.states.async_set("climate.unit", "cool")
    before = hass.states.get("climate.unit")

    result = await entity_tools.state_after_call(
        hass, "climate.unit", before, "turn_off", {}
    )

    assert result["state_after"] == "cool"
    assert result["state_confirmed"] is False
    assert "Do not say the command failed" in result["note"]


async def test_state_after_call_does_not_wait_when_state_already_matches(
    hass, monkeypatch
):
    monkeypatch.setattr(entity_tools, "STATE_SETTLE_TIMEOUT", 0.05)
    hass.states.async_set("climate.unit", "off")
    before = hass.states.get("climate.unit")

    result = await entity_tools.state_after_call(
        hass, "climate.unit", before, "turn_off", {}
    )

    assert result["state_after"] == "off"
    assert "state_confirmed" not in result


async def test_state_after_call_waits_for_requested_attribute(hass, monkeypatch):
    monkeypatch.setattr(entity_tools, "STATE_SETTLE_TIMEOUT", 2.0)
    hass.states.async_set("climate.unit", "cool", {"temperature": 22})
    before = hass.states.get("climate.unit")

    async def report_late() -> None:
        await asyncio.sleep(0.05)
        hass.states.async_set("climate.unit", "cool", {"temperature": 18})

    task = hass.async_create_task(report_late())
    result = await entity_tools.state_after_call(
        hass, "climate.unit", before, "set_temperature", {"temperature": 18}
    )
    await task

    assert result["settings_after"]["temperature"] == 18
    assert "state_confirmed" not in result


async def test_state_after_call_accepts_any_change_for_other_services(
    hass, monkeypatch
):
    monkeypatch.setattr(entity_tools, "STATE_SETTLE_TIMEOUT", 0.05)
    hass.states.async_set("vacuum.robot", "docked")
    before = hass.states.get("vacuum.robot")
    hass.states.async_set("vacuum.robot", "cleaning")

    result = await entity_tools.state_after_call(
        hass, "vacuum.robot", before, "start", {}
    )

    assert result["state_after"] == "cleaning"
    assert "state_confirmed" not in result

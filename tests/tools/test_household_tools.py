"""Tests for household devices: shared entities resolved by room and floor."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import Context, HomeAssistant, ServiceCall
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
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_ADDRESS_AS,
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_HOUSEHOLD_ALIASES,
    CONF_HOUSEHOLD_DEVICES,
    CONF_PRIVATE_ENTITIES,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_ADDRESS_AS,
    CONF_USER_ID,
    DOMAIN,
    PERSON_API_ID,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
)

CLIMATE = {
    "hvac_modes": ["off", "fan_only", "heat_cool", "dry", "cool"],
    "fan_modes": ["auto", "low", "high"],
    "min_temp": 16,
    "max_temp": 30,
    "temperature_unit": "°C",
    "temperature": 22,
}


@pytest.fixture
async def home(hass: HomeAssistant):
    """Two air conditioners in two rooms, a lock, a calendar and a speaker device each."""
    floors = fr.async_get(hass)
    ground = floors.async_create("Ground")
    upper = floors.async_create("Upstairs")
    areas = ar.async_get(hass)
    container = areas.async_create("Container", floor_id=ground.floor_id)
    bus = areas.async_create("Bus", floor_id=upper.floor_id)
    areas.async_create("Hall", floor_id=upper.floor_id)

    entities = er.async_get(hass)
    for domain, object_id, area in (
        ("climate", "container_air_conditioner", container),
        ("climate", "bus_air_conditioner", bus),
        ("lock", "front_door", container),
    ):
        entities.async_get_or_create(
            domain, "test", object_id, suggested_object_id=object_id
        )
        entities.async_update_entity(f"{domain}.{object_id}", area_id=area.id)
    for object_id, name in (
        ("container_air_conditioner", "Container Air Conditioner"),
        ("bus_air_conditioner", "Bus Air Conditioner"),
    ):
        hass.states.async_set(
            f"climate.{object_id}", "off", {**CLIMATE, "friendly_name": name}
        )
    hass.states.async_set("lock.front_door", "locked", {"friendly_name": "Front Door"})
    hass.states.async_set("calendar.house", "off", {"friendly_name": "House"})

    config = MockConfigEntry(domain="test")
    config.add_to_hass(hass)
    devices = dr.async_get(hass)
    speaker_devices = {
        name: devices.async_get_or_create(
            config_entry_id=config.entry_id,
            identifiers={("test", name)},
            suggested_area=name,
        ).id
        for name in ("Container", "Bus", "Hall")
    }

    calls: list[ServiceCall] = []

    async def record(call: ServiceCall) -> None:
        calls.append(call)
        mode = call.data.get("hvac_mode")
        if mode:
            hass.states.async_set(
                call.data["entity_id"],
                mode,
                hass.states.get(call.data["entity_id"]).attributes,
            )

    for service in ("set_hvac_mode", "set_temperature", "set_fan_mode", "turn_off"):
        hass.services.async_register("climate", service, record)
    hass.services.async_register("lock", "unlock", record)
    hass.services.async_register("lock", "lock", record)
    return {"calls": calls, "devices": speaker_devices}


async def _setup(
    hass: HomeAssistant, *, deny=False, household=None, private=(), aliases=None
):
    james = await hass.auth.async_create_user("James", group_ids=["system-users"])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={
            CONF_UNKNOWN_ADDRESS_AS: "Unknown Person",
            CONF_DENY_UNKNOWN: deny,
            CONF_HOUSEHOLD_ALIASES: aliases or {},
            CONF_HOUSEHOLD_DEVICES: household
            if household is not None
            else [
                "climate.container_air_conditioner",
                "climate.bus_air_conditioner",
                "lock.front_door",
                "calendar.house",
            ],
        },
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="James",
                unique_id=james.id,
                data={
                    CONF_USER_ID: james.id,
                    CONF_ADDRESS_AS: "Dad",
                    CONF_ENTITIES: list(private),
                    CONF_PRIVATE_ENTITIES: list(private),
                },
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return james


async def _call(hass, user_id, device_id, tool, **args):
    context = llm.LLMContext(
        platform="test",
        context=Context(user_id=user_id),
        language="en",
        assistant="conversation",
        device_id=device_id,
    )
    instance = await llm.async_get_api(hass, PERSON_API_ID, context)
    chosen = next(t for t in instance.tools if t.name == tool)
    result = await chosen.async_call(
        hass, llm.ToolInput(tool_name=tool, tool_args=args), context
    )
    return result.data, result.error


async def _prompt(hass, user_id) -> str:
    context = llm.LLMContext(
        platform="test",
        context=Context(user_id=user_id),
        language="en",
        assistant="conversation",
        device_id=None,
    )
    return (await llm.async_get_api(hass, PERSON_API_ID, context)).api_prompt


async def _tool_names(hass, user_id) -> list[str]:
    context = llm.LLMContext(
        platform="test",
        context=Context(user_id=user_id),
        language="en",
        assistant="conversation",
        device_id=None,
    )
    return [
        t.name for t in (await llm.async_get_api(hass, PERSON_API_ID, context)).tools
    ]


async def test_same_words_use_the_unit_in_the_speakers_room(hass, home) -> None:
    james = await _setup(hass)
    for room, expected in (
        ("Container", "climate.container_air_conditioner"),
        ("Bus", "climate.bus_air_conditioner"),
    ):
        data, error = await _call(
            hass,
            james.id,
            home["devices"][room],
            "control_household_device",
            device="Air Conditioner",
            service="climate.set_hvac_mode",
            service_data={"hvac_mode": "cool"},
        )
        assert not error
        assert data["entity_id"] == expected
        assert data["state_after"] == "cool"
        assert data["settings_after"]["hvac_mode"] == "cool"
    assert [c.data["entity_id"] for c in home["calls"]] == [
        "climate.container_air_conditioner",
        "climate.bus_air_conditioner",
    ]


async def test_a_named_room_wins_over_the_speakers_room(hass, home) -> None:
    james = await _setup(hass)
    data, error = await _call(
        hass,
        james.id,
        home["devices"]["Container"],
        "control_household_device",
        device="aircon",
        area="bus",
        service="climate.set_hvac_mode",
        service_data={"hvac_mode": "cool"},
    )
    # "aircon" alone matches no name, so the model has to use the listed name.
    assert error and data["problem"] == "device_not_found"
    data, error = await _call(
        hass,
        james.id,
        home["devices"]["Container"],
        "control_household_device",
        device="air conditioner",
        area="Bus",
        service="climate.set_hvac_mode",
        service_data={"hvac_mode": "cool"},
    )
    assert not error and data["entity_id"] == "climate.bus_air_conditioner"


async def test_a_floor_name_selects_units_on_that_floor(hass, home) -> None:
    james = await _setup(hass)
    data, error = await _call(
        hass,
        james.id,
        None,
        "control_household_device",
        device="Air Conditioner",
        area="Upstairs",
        service="climate.turn_off",
    )
    assert not error and data["entity_id"] == "climate.bus_air_conditioner"


async def test_same_floor_is_used_when_the_speakers_room_has_no_unit(
    hass, home
) -> None:
    james = await _setup(hass, household=["climate.bus_air_conditioner"])
    data, error = await _call(
        hass,
        james.id,
        home["devices"]["Hall"],
        "get_household_device_state",
        device="Air Conditioner",
    )
    assert not error
    assert data["entity_id"] == "climate.bus_air_conditioner"
    assert data["area"] == "Bus" and data["floor"] == "Upstairs"


async def test_without_a_room_the_tool_asks_which_unit(hass, home) -> None:
    james = await _setup(hass)
    data, error = await _call(
        hass,
        james.id,
        None,
        "get_household_device_state",
        device="Air Conditioner",
    )
    assert error and data["problem"] == "choose_device"
    assert {o["entity_id"]: o["area"] for o in data["options"]} == {
        "climate.container_air_conditioner": "Container",
        "climate.bus_air_conditioner": "Bus",
    }


async def test_an_unknown_room_name_is_refused(hass, home) -> None:
    james = await _setup(hass)
    data, error = await _call(
        hass,
        james.id,
        None,
        "get_household_device_state",
        device="Air Conditioner",
        area="Garage",
    )
    assert error and data["problem"] == "unknown_area"


async def test_unsupported_mode_is_refused_with_the_valid_modes(hass, home) -> None:
    james = await _setup(hass)
    data, error = await _call(
        hass,
        james.id,
        home["devices"]["Bus"],
        "control_household_device",
        device="Air Conditioner",
        service="climate.set_hvac_mode",
        service_data={"hvac_mode": "heat"},
    )
    assert error and data["problem"] == "unsupported_value"
    assert data["supported"] == CLIMATE["hvac_modes"]
    assert not home["calls"]


async def test_mode_matches_ignoring_case_and_spaces(hass, home) -> None:
    james = await _setup(hass)
    data, error = await _call(
        hass,
        james.id,
        home["devices"]["Bus"],
        "control_household_device",
        device="Air Conditioner",
        service="climate.set_hvac_mode",
        service_data={"hvac_mode": "Heat Cool"},
    )
    assert not error
    assert home["calls"][0].data["hvac_mode"] == "heat_cool"


async def test_temperature_outside_the_units_range_is_refused(hass, home) -> None:
    james = await _setup(hass)
    data, error = await _call(
        hass,
        james.id,
        home["devices"]["Bus"],
        "control_household_device",
        device="Air Conditioner",
        service="climate.set_temperature",
        service_data={"temperature": 35},
    )
    assert error and data["problem"] == "temperature_out_of_range"
    assert (data["min_temp"], data["max_temp"]) == (16, 30)
    assert not home["calls"]


async def test_temperature_must_be_a_number(hass, home) -> None:
    james = await _setup(hass)
    data, error = await _call(
        hass,
        james.id,
        home["devices"]["Bus"],
        "control_household_device",
        device="Air Conditioner",
        service="climate.set_temperature",
        service_data={"temperature": "warm"},
    )
    assert error and data["problem"] == "invalid_temperature"


async def test_unknown_speakers_can_use_household_devices(hass, home) -> None:
    await _setup(hass)
    assert await _tool_names(hass, None) == [
        "get_household_device_state",
        "control_household_device",
    ]
    data, error = await _call(
        hass,
        None,
        home["devices"]["Container"],
        "control_household_device",
        device="Air Conditioner",
        service="climate.set_hvac_mode",
        service_data={"hvac_mode": "cool"},
    )
    assert not error and data["entity_id"] == "climate.container_air_conditioner"


async def test_unknown_speakers_can_never_use_locks(hass, home) -> None:
    await _setup(hass)
    for tool, args in (
        ("get_household_device_state", {"device": "lock.front_door"}),
        (
            "control_household_device",
            {"device": "Front Door", "service": "lock.unlock"},
        ),
    ):
        data, error = await _call(hass, None, None, tool, **args)
        assert error and data["problem"] == "device_not_found"
        assert all("lock" not in o["entity_id"] for o in data["options"])
    assert not home["calls"]


async def test_unknown_speakers_never_see_restricted_devices_in_the_prompt(
    hass, home
) -> None:
    james = await _setup(hass)
    unknown = await _prompt(hass, None)
    assert "## HOUSEHOLD DEVICES" in unknown
    assert "climate.bus_air_conditioner: Bus Air Conditioner (area: Bus" in unknown
    assert "lock.front_door" not in unknown
    assert "calendar.house" not in unknown
    assert "lock.front_door: Front Door (area: Container" in await _prompt(
        hass, james.id
    )
    assert "calendar.house" not in await _prompt(hass, james.id)


async def test_known_speakers_confirm_unlocking_but_not_locking(hass, home) -> None:
    james = await _setup(hass)
    data, error = await _call(
        hass,
        james.id,
        None,
        "control_household_device",
        device="lock.front_door",
        service="lock.unlock",
    )
    assert not error and data["confirmation_required"]
    assert not home["calls"]
    data, error = await _call(
        hass,
        james.id,
        None,
        "control_household_device",
        device="lock.front_door",
        service="lock.lock",
    )
    assert not error and data["service_called"]


async def test_deny_unknown_leaves_unknown_speakers_with_nothing(hass, home) -> None:
    await _setup(hass, deny=True)
    assert await _tool_names(hass, None) == []
    assert "HOUSEHOLD DEVICES" not in await _prompt(hass, None)


async def test_calendars_cannot_be_household_devices(hass, home) -> None:
    james = await _setup(hass, household=["calendar.house"])
    assert await _tool_names(hass, None) == []
    assert "get_household_device_state" not in await _tool_names(hass, james.id)


async def test_a_device_private_to_someone_else_is_not_shared(hass, home) -> None:
    james = await _setup(hass, private=["climate.bus_air_conditioner"])
    data, error = await _call(
        hass,
        None,
        home["devices"]["Bus"],
        "get_household_device_state",
        device="Air Conditioner",
    )
    assert not error and data["entity_id"] == "climate.container_air_conditioner"
    assert "climate.bus_air_conditioner" not in await _prompt(hass, None)
    data, error = await _call(
        hass,
        james.id,
        home["devices"]["Bus"],
        "get_household_device_state",
        device="Air Conditioner",
    )
    assert not error and data["entity_id"] == "climate.bus_air_conditioner"


async def test_no_household_tools_when_none_are_configured(hass, home) -> None:
    james = await _setup(hass, household=[])
    assert await _tool_names(hass, None) == []
    assert "get_household_device_state" not in await _tool_names(hass, james.id)
    assert "HOUSEHOLD DEVICES" not in await _prompt(hass, james.id)


AIRCON_ALIASES = {
    "climate.container_air_conditioner": ["Aircon", "Cooler"],
    "climate.bus_air_conditioner": ["Aircon"],
}


async def test_a_shared_alias_still_picks_the_unit_in_the_speakers_room(
    hass, home
) -> None:
    james = await _setup(hass, aliases=AIRCON_ALIASES)
    for room, expected in (
        ("Container", "climate.container_air_conditioner"),
        ("Bus", "climate.bus_air_conditioner"),
    ):
        data, error = await _call(
            hass,
            james.id,
            home["devices"][room],
            "control_household_device",
            device="aircon",
            service="climate.set_hvac_mode",
            service_data={"hvac_mode": "cool"},
        )
        assert not error and data["entity_id"] == expected
        assert data["entity"] == expected.split(".")[1].replace("_", " ").title()


async def test_an_alias_matches_one_unit_in_any_room(hass, home) -> None:
    james = await _setup(hass, aliases=AIRCON_ALIASES)
    data, error = await _call(
        hass,
        james.id,
        home["devices"]["Bus"],
        "get_household_device_state",
        device="cooler",
    )
    assert not error and data["entity_id"] == "climate.container_air_conditioner"


async def test_unknown_speakers_can_use_aliases(hass, home) -> None:
    await _setup(hass, aliases=AIRCON_ALIASES)
    data, error = await _call(
        hass,
        None,
        home["devices"]["Bus"],
        "get_household_device_state",
        device="aircon",
    )
    assert not error and data["entity_id"] == "climate.bus_air_conditioner"


async def test_aliases_set_in_home_assistant_count(hass, home) -> None:
    er.async_get(hass).async_update_entity(
        "climate.bus_air_conditioner", aliases={"Bus cooler"}
    )
    james = await _setup(hass)
    data, error = await _call(
        hass, james.id, None, "get_household_device_state", device="bus cooler"
    )
    assert not error and data["entity_id"] == "climate.bus_air_conditioner"
    assert "other aliases: Bus cooler" in await _prompt(hass, james.id)


async def test_prompt_shows_the_preferred_name_and_other_aliases(hass, home) -> None:
    await _setup(hass, aliases=AIRCON_ALIASES)
    prompt = await _prompt(hass, None)
    assert (
        "climate.container_air_conditioner: Aircon (area: Container, floor: Ground)"
        " (other aliases: Cooler)" in prompt
    )
    assert "other aliases: Bus" not in prompt


async def test_not_found_choices_include_aliases(hass, home) -> None:
    await _setup(hass, aliases=AIRCON_ALIASES)
    data, error = await _call(hass, None, None, "get_household_device_state", device="fan")
    assert error and data["problem"] == "device_not_found"
    assert next(
        o for o in data["options"] if o["entity_id"].endswith("container_air_conditioner")
    )["aliases"] == ["Cooler"]


async def test_household_control_reports_a_unit_that_answers_late(
    hass, home, monkeypatch
) -> None:
    from custom_components.speaker_recognition_tools import entity_tools

    monkeypatch.setattr(entity_tools, "STATE_SETTLE_TIMEOUT", 2.0)
    james = await _setup(hass)
    hass.states.async_set("climate.bus_air_conditioner", "cool", CLIMATE)

    async def slow_turn_off(call: ServiceCall) -> None:
        async def report() -> None:
            await asyncio.sleep(0.05)
            hass.states.async_set(call.data["entity_id"], "off", CLIMATE)

        hass.async_create_task(report())

    hass.services.async_register("climate", "turn_off", slow_turn_off)
    data, error = await _call(
        hass,
        james.id,
        home["devices"]["Bus"],
        "control_household_device",
        device="Bus Air Conditioner",
        service="climate.turn_off",
    )

    assert not error
    assert data["state_after"] == "off"
    assert "state_confirmed" not in data


async def test_household_control_says_unconfirmed_when_unit_stays_silent(
    hass, home, monkeypatch
) -> None:
    from custom_components.speaker_recognition_tools import entity_tools

    monkeypatch.setattr(entity_tools, "STATE_SETTLE_TIMEOUT", 0.05)
    james = await _setup(hass)
    hass.states.async_set("climate.bus_air_conditioner", "cool", CLIMATE)

    data, error = await _call(
        hass,
        james.id,
        home["devices"]["Bus"],
        "control_household_device",
        device="Bus Air Conditioner",
        service="climate.turn_off",
    )

    assert not error
    assert data["service_called"] is True
    assert data["state_confirmed"] is False

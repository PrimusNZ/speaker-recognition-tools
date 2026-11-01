"""Tests for the speaker event, the Last speaker sensor and recognition confidence."""

from __future__ import annotations

import datetime

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import llm
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.speaker_recognition_tools.const import (
    CONF_ADDRESS_AS,
    CONF_ENTITIES,
    CONF_MIN_CONFIDENCE,
    CONF_TOOL_TYPE,
    CONF_USER_ID,
    DOMAIN,
    EVENT_SPEAKER,
    PERSON_API_ID,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
)
from custom_components.speaker_recognition_tools.recognition import (
    latest_confidence,
)


class FakeHistory:
    """Stands in for Speaker Recognition's decision history."""

    def __init__(self, records=None, fail=False) -> None:
        self.records = records or []
        self.fail = fail

    def recent(self, limit: int = 25):
        if self.fail:
            raise RuntimeError("changed upstream")
        return list(reversed(self.records))[:limit]


def _record(user_id, confidence, *, satellite=None, age_seconds=0, eligible=True):
    return {
        "created_at": (
            dt_util.utcnow() - datetime.timedelta(seconds=age_seconds)
        ).isoformat(),
        "user_id": user_id,
        "identity_eligible": eligible,
        "confidence": confidence,
        "satellite_id": satellite,
    }


def _install_history(hass: HomeAssistant, history: FakeHistory) -> None:
    hass.data.setdefault("speaker_recognition", {})["decision_history"] = history


@pytest.fixture
async def household(hass: HomeAssistant):
    await hass.auth.async_create_user("Owner Account")
    james = await hass.auth.async_create_user(
        "James Example", group_ids=["system-users"]
    )
    hass.states.async_set("switch.fan", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={CONF_MIN_CONFIDENCE: 0.8},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="James",
                unique_id=james.id,
                data={
                    CONF_USER_ID: james.id,
                    CONF_ADDRESS_AS: "Dad",
                    CONF_ENTITIES: ["switch.fan"],
                },
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, james


def _sensor_id(hass: HomeAssistant, entry) -> str:
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_last_speaker"
    )


async def _instance(hass, user_id, device_id=None) -> llm.APIInstance:
    context = llm.LLMContext(
        platform="test",
        context=Context(user_id=user_id),
        language="en",
        assistant="conversation",
        device_id=device_id,
    )
    return await llm.async_get_api(hass, PERSON_API_ID, context)


async def _turn_on_fan(hass, api_instance, **extra):
    tool = next(t for t in api_instance.tools if t.name == "control_assigned_entity")
    result = await tool.async_call(
        hass,
        llm.ToolInput(
            tool_name=tool.name,
            tool_args={"entity": "switch.fan", "service": "switch.turn_on", **extra},
        ),
        api_instance.llm_context,
    )
    return result.data, result.error


def _record_fan(hass) -> list[dict]:
    calls: list[dict] = []

    async def handler(call: ServiceCall) -> None:
        calls.append(dict(call.data))

    hass.services.async_register("switch", "turn_on", handler)
    return calls


async def test_recognised_turn_fires_event_and_updates_sensor(
    hass: HomeAssistant, household
) -> None:
    entry, james = household
    area = ar.async_get(hass).async_create("Kitchen")
    config = MockConfigEntry(domain="test")
    config.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config.entry_id,
        identifiers={("test", "satellite")},
        name="Kitchen satellite",
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    events = async_capture_events(hass, EVENT_SPEAKER)

    await _instance(hass, james.id, device.id)
    await hass.async_block_till_done()

    (event,) = events
    assert event.data["recognised"] is True
    assert event.data["name"] == "James"
    assert event.data["address_as"] == "Dad"
    assert event.data["device"] == "Kitchen satellite"
    assert event.data["area"] == "Kitchen"
    assert event.data["confidence"] is None
    assert event.context.user_id == james.id
    state = hass.states.get(_sensor_id(hass, entry))
    assert state.state == "James"
    assert state.attributes["area"] == "Kitchen"
    assert state.attributes["user_id"] == james.id


async def test_unknown_turn_is_reported_as_unknown(
    hass: HomeAssistant, household
) -> None:
    entry, _ = household
    events = async_capture_events(hass, EVENT_SPEAKER)
    api_instance = await _instance(hass, None)
    await hass.async_block_till_done()
    assert api_instance.tools == []
    assert events[0].data["recognised"] is False
    assert events[0].data["name"] is None
    assert hass.states.get(_sensor_id(hass, entry)).state == "unknown_speaker"


async def test_confidence_comes_from_the_matching_recent_decision(
    hass: HomeAssistant,
) -> None:
    _install_history(
        hass,
        FakeHistory(
            [
                _record("u1", 0.95, age_seconds=600),  # too old
                _record("u1", 0.71),
                _record("u2", 0.99),  # someone else
            ]
        ),
    )
    assert latest_confidence(hass, "u1", None) == pytest.approx(0.71)
    assert latest_confidence(hass, "u3", None) is None
    assert latest_confidence(hass, None, None) is None


async def test_decision_from_another_satellite_is_skipped(
    hass: HomeAssistant,
) -> None:
    config = MockConfigEntry(domain="test")
    config.add_to_hass(hass)
    registry = dr.async_get(hass)
    lounge = registry.async_get_or_create(
        config_entry_id=config.entry_id, identifiers={("test", "lounge")}
    )
    kitchen = registry.async_get_or_create(
        config_entry_id=config.entry_id, identifiers={("test", "kitchen")}
    )
    satellite = er.async_get(hass).async_get_or_create(
        "assist_satellite", "test", "lounge", device_id=lounge.id
    )
    _install_history(
        hass, FakeHistory([_record("u1", 0.6, satellite=satellite.entity_id)])
    )
    assert latest_confidence(hass, "u1", lounge.id) == pytest.approx(0.6)
    assert latest_confidence(hass, "u1", kitchen.id) is None


@pytest.mark.parametrize(
    "history",
    [
        FakeHistory(fail=True),
        FakeHistory([_record("u1", "high")]),
        FakeHistory([_record("u1", 1.5)]),
        FakeHistory([_record("u1", 0.9, eligible=False)]),
        object(),
    ],
)
async def test_unreadable_confidence_is_unknown(hass: HomeAssistant, history) -> None:
    _install_history(hass, history)
    assert latest_confidence(hass, "u1", None) is None


async def test_low_confidence_needs_confirmation_and_identity_check(
    hass: HomeAssistant, household
) -> None:
    _, james = household
    calls = _record_fan(hass)
    _install_history(hass, FakeHistory([_record(james.id, 0.55)]))
    api_instance = await _instance(hass, james.id)

    preview, error = await _turn_on_fan(hass, api_instance)
    assert not error
    assert preview["confirmation_required"] is True
    assert "not confident that this is Dad" in preview["note"]
    assert calls == []

    result, error = await _turn_on_fan(
        hass,
        api_instance,
        confirmation_token=preview["confirmation_token"],
        confirmed=True,
    )
    assert not error
    assert calls == [{"entity_id": "switch.fan"}]


async def test_confident_turn_acts_straight_away(
    hass: HomeAssistant, household
) -> None:
    _, james = household
    calls = _record_fan(hass)
    _install_history(hass, FakeHistory([_record(james.id, 0.93)]))
    result, error = await _turn_on_fan(hass, await _instance(hass, james.id))
    assert not error
    assert result["service_called"] is True
    assert calls == [{"entity_id": "switch.fan"}]


async def test_missing_history_changes_nothing(hass: HomeAssistant, household) -> None:
    _, james = household
    calls = _record_fan(hass)
    result, error = await _turn_on_fan(hass, await _instance(hass, james.id))
    assert not error
    assert result["service_called"] is True
    assert calls == [{"entity_id": "switch.fan"}]

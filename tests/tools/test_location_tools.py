"""Tests for the location tools, addresses and spoken times."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import llm
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools import entity_tools, location_tools
from custom_components.speaker_recognition_tools.location_tools import (
    _device_room,
    _since_phrase,
    _spoken_clock,
)
from custom_components.speaker_recognition_tools.prompt import Person
from custom_components.speaker_recognition_tools.tool_base import Household
from tests.tools.helpers import (
    _problems,
    call,
    instance,
    local,
    now,
)


async def test_location_history_returns_recorded_transitions(
    hass, users, monkeypatch
) -> None:
    hass.states.async_set("person.james", "home")
    state = hass.states.get("person.james")
    seen = {}

    async def history(_hass, entity_ids, _start, _end):
        seen["entity_ids"] = entity_ids
        return {"person.james": [state]}

    monkeypatch.setattr(location_tools, "_location_history", history)
    data, error = await call(
        hass,
        users["James"],
        "get_person_location_history",
        start="2026-10-29",
        end="2026-10-30",
    )
    assert not error
    assert seen["entity_ids"] == ["person.james", "device_tracker.james_phone"]
    assert data["people"][0]["history"][0]["location"] == "home"
    assert "at_spoken" in data["people"][0]["history"][0]


async def test_location_history_rejects_ranges_over_31_days(hass, users) -> None:
    data, error = await call(
        hass,
        users["James"],
        "get_person_location_history",
        start="2026-09-01",
        end="2026-10-03",
    )
    assert error
    assert "31-day" in data["error"]


# ------------------------------------------------------------------------- location


async def test_location_of_self(hass, users) -> None:
    hass.states.async_set("person.james", "home")
    hass.states.async_set("device_tracker.james_phone", "not_home")
    data, error = await call(hass, users["James"], "get_person_location", people=["me"])
    assert not error
    person = data["people"][0]
    assert person["person"] == "Dad"
    assert person["location"] == "home"  # the person entity wins
    assert {e["entity_id"]: e["state"] for e in person["entities"]} == {
        "person.james": "home",
        "device_tracker.james_phone": "outside known zones",
    }


async def test_location_zone_and_unavailable(hass, users) -> None:
    hass.states.async_set("person.james", "Work")
    data, _ = await call(hass, users["Sarah"], "get_person_location", people=["Dad"])
    assert data["people"][0]["location"] == "Work"
    hass.states.async_set("person.james", "unknown")
    hass.states.async_set("device_tracker.james_phone", "unavailable")
    data, _ = await call(hass, users["Sarah"], "get_person_location", people=["Dad"])
    assert data["people"][0]["location"] == "unavailable"


async def test_location_for_everyone_respects_privacy(hass, users) -> None:
    hass.states.async_set("person.james", "home")
    hass.states.async_set("device_tracker.ann_phone", "home")
    hass.states.async_set("device_tracker.tom_phone", "home")
    data, error = await call(hass, users["James"], "get_person_location")
    assert not error
    by_person = {p["person"]: p for p in data["people"]}
    assert set(by_person) == {"Dad", "Mum", "Aunt", "Cousin", "Grandad"}
    assert by_person["Dad"]["location"] == "home"
    assert by_person["Mum"]["reason"] == "no location entity assigned"
    assert by_person["Aunt"] == {
        "person": "Aunt",
        "location": None,
        "reason": "private",
    }
    assert by_person["Grandad"]["reason"] == "private"
    assert "device_tracker.ann_phone" not in str(data)


async def test_owner_can_see_their_private_tracker(hass, users) -> None:
    hass.states.async_set("device_tracker.ann_phone", "not_home")
    data, _ = await call(hass, users["Ann"], "get_person_location", people=["me"])
    assert data["people"][0]["location"] == "outside known zones"


async def test_location_unknown_person(hass, users) -> None:
    data, error = await call(
        hass, users["James"], "get_person_location", people=["Bob"]
    )
    assert error
    assert _problems(data)["unknown_person"]


# ------------------------------------------------------------------ geocoded address


def _companion_phone(
    hass: HomeAssistant, name: str, *, geocoded: str | None = None, **tracker_attrs
) -> None:
    """Register a Companion App style device: a tracker plus a geocoded location sensor."""
    config = MockConfigEntry(domain="mobile_app")
    config.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config.entry_id,
        identifiers={("mobile_app", name)},
        name=f"{name} phone",
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "device_tracker",
        "mobile_app",
        f"{name}-tracker",
        device_id=device.id,
        config_entry=config,
        suggested_object_id=f"{name}_phone",
    )
    hass.states.async_set(f"device_tracker.{name}_phone", "not_home", tracker_attrs)
    if geocoded is not None:
        registry.async_get_or_create(
            "sensor",
            "mobile_app",
            f"{name}-hook_geocoded_location",
            device_id=device.id,
            config_entry=config,
            suggested_object_id=f"{name}_phone_geocoded_location",
        )
        hass.states.async_set(f"sensor.{name}_phone_geocoded_location", geocoded)


async def _where(hass, user, who="Dad"):
    data, error = await call(hass, user, "get_person_location", people=[who])
    assert not error
    return data["people"][0]


async def test_outside_zones_uses_the_companion_apps_geocoded_address(
    hass, users
) -> None:
    _companion_phone(
        hass, "james", geocoded="42 Example Road\nSampleton\n0000\nTestland"
    )
    hass.states.async_set(
        "person.james", "not_home", {"source": "device_tracker.james_phone"}
    )
    result = await _where(hass, users["Sarah"])
    assert result["location"] == "Example Road, Sampleton"
    assert result["address"] == "Example Road, Sampleton"
    assert "away" not in str(result)


@pytest.mark.parametrize("zone", ["home", "Work"])
async def test_no_address_while_inside_a_zone(hass, users, zone) -> None:
    _companion_phone(hass, "james", geocoded="42 Example Road\nSampleton")
    hass.states.async_set(
        "person.james", zone, {"source": "device_tracker.james_phone"}
    )
    result = await _where(hass, users["Sarah"])
    assert result["location"] == zone
    assert "address" not in result and "address_note" not in result


async def test_address_from_the_tracker_itself(hass, users) -> None:
    hass.states.async_set(
        "device_tracker.james_phone", "not_home", {"address": "17 Fixture Lane"}
    )
    result = await _where(hass, users["Sarah"])
    assert result["address"] == "Fixture Lane"


async def test_address_found_without_a_person_source(hass, users) -> None:
    _companion_phone(hass, "james", geocoded="8 Sample Crescent")
    hass.states.async_set("person.james", "not_home")
    assert (await _where(hass, users["Sarah"]))["address"] == "Sample Crescent"


@pytest.mark.parametrize("state", ["unknown", "unavailable", ""])
async def test_unusable_geocoded_sensor_gives_no_address(hass, users, state) -> None:
    _companion_phone(hass, "james", geocoded=state)
    result = await _where(hass, users["Sarah"])
    assert result["location"] == "outside known zones"
    assert "address" not in result
    assert (
        'Reply with exactly: "Sorry Mum, An exact address for Dad is unknown."'
        in result["address_note"]
    )
    assert "do not guess where" in result["address_note"]


async def test_no_address_when_the_device_reports_none(hass, users) -> None:
    hass.states.async_set("device_tracker.james_phone", "not_home")
    result = await _where(hass, users["Sarah"])
    assert result["location"] == "outside known zones"
    assert "away" not in str(result)
    assert "address" not in result
    assert result["address_note"] == (
        'Reply with exactly: "Sorry Mum, An exact address for Dad is unknown." '
        "Add nothing else and do not guess where they are."
    )


async def test_geocoding_is_per_phone(hass, users) -> None:
    """One person's phone has geocoding on and another's has it off."""
    _companion_phone(hass, "james", geocoded="42 Example Road\nSampleton")
    hass.states.async_set(
        "person.james", "not_home", {"source": "device_tracker.james_phone"}
    )
    hass.states.async_set("device_tracker.kim_phone", "not_home")
    with_geo = await _where(hass, users["Sarah"], "Dad")
    without = await _where(hass, users["Sarah"], "Cousin")
    assert with_geo["address"] == "Example Road, Sampleton"
    assert "address_note" not in with_geo
    assert "address" not in without
    assert (
        '"Sorry Mum, An exact address for Cousin is unknown."'
        in without["address_note"]
    )


async def test_companion_attributes_give_street_and_town(hass, users) -> None:
    _companion_phone(hass, "james", geocoded="ignored\nlines")
    hass.states.async_set(
        "sensor.james_phone_geocoded_location",
        "17 Fixture Lane\nSampleton\n00000\nTestland",
        {
            "Thoroughfare": "Fixture Lane",
            "Sub Thoroughfare": "17",
            "Locality": "Sampleton",
            "Postal Code": "00000",
            "Country": "Testland",
        },
    )
    assert (await _where(hass, users["Sarah"]))["address"] == "Fixture Lane, Sampleton"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("17 Fixture Lane, Sampleton, 00000, Testland", "Fixture Lane, Sampleton"),
        ("17 Fixture Lane\nSampleton\n00000\nTestland", "Fixture Lane, Sampleton"),
        ("4/17 Fixture Lane, Sampleton", "Fixture Lane, Sampleton"),
        ("Fixture Lane", "Fixture Lane"),
        ("42 Fixture Lane", "Fixture Lane"),
        ("Fixture Lane, 00000", "Fixture Lane"),
    ],
)
async def test_street_and_town_from_plain_text(hass, users, text, expected) -> None:
    hass.states.async_set("device_tracker.james_phone", "not_home", {"address": text})
    assert (await _where(hass, users["Sarah"]))["address"] == expected


async def test_town_only_attribute(hass, users) -> None:
    hass.states.async_set(
        "device_tracker.james_phone",
        "not_home",
        {"Locality": "Sampleton", "address": "x"},
    )
    assert (await _where(hass, users["Sarah"]))["address"] == "Sampleton"


async def test_address_never_includes_number_postcode_or_country(hass, users) -> None:
    _companion_phone(
        hass, "james", geocoded="42 Example Road\nSampleton\n0000\nTestland"
    )
    hass.states.async_set(
        "person.james", "not_home", {"source": "device_tracker.james_phone"}
    )
    text = str(await _where(hass, users["Sarah"]))
    assert "0000" not in text and "Testland" not in text and "42 Example" not in text


async def test_asking_about_yourself_says_you(hass, users) -> None:
    hass.states.async_set("device_tracker.james_phone", "not_home")
    result = await _where(hass, users["James"], "me")
    assert '"Sorry Dad, An exact address for you is unknown."' in result["address_note"]


async def test_reply_names_the_speaker_and_the_target(hass, users) -> None:
    hass.states.async_set("device_tracker.james_phone", "not_home")
    asked_by_aunt = await _where(hass, users["Ann"], "Dad")
    assert (
        '"Sorry Aunt, An exact address for Dad is unknown."'
        in asked_by_aunt["address_note"]
    )


async def test_disabled_geocoded_sensor_is_treated_as_off(hass, users) -> None:
    _companion_phone(hass, "james", geocoded="42 Example Road")
    er.async_get(hass).async_update_entity(
        "sensor.james_phone_geocoded_location",
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    hass.states.async_remove("sensor.james_phone_geocoded_location")
    result = await _where(hass, users["Sarah"])
    assert result["location"] == "outside known zones"
    assert "address" not in result and "address_note" in result


async def test_private_geocoded_sensor_is_not_used_for_others(hass, users) -> None:
    _companion_phone(hass, "kim", geocoded="9 Private Lane")
    other = await _where(hass, users["James"], "Cousin")
    assert other["location"] == "outside known zones"
    assert "address" not in other
    assert "9 Private Lane" not in str(other)
    assert "address_note" in other
    owner = await _where(hass, users["Kim"], "me")
    assert owner["address"] == "Private Lane"


async def test_address_does_not_leak_through_a_private_tracker(hass, users) -> None:
    _companion_phone(hass, "ann", geocoded="3 Example Crescent")
    result = await _where(hass, users["James"], "Aunt")
    assert result == {"person": "Aunt", "location": None, "reason": "private"}


# ----------------------------------------------------------------- how long (since)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (0, 0, "midnight"),
        (12, 0, "midday"),
        (15, 0, "three o'clock"),
        (3, 0, "three o'clock"),
        (12, 15, "quarter past twelve"),
        (15, 30, "half past three"),
        (15, 45, "quarter to four"),
        (11, 45, "quarter to twelve"),
        (23, 45, "quarter to twelve"),
        (15, 47, "3:47"),
        (0, 5, "12:05"),
    ],
)
def test_spoken_clock(hour, minute, expected) -> None:
    assert _spoken_clock(local(26, hour, minute)) == expected


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        ((26, 16, 59), "just now"),
        ((26, 15, 0), "three o'clock"),  # two hours ago
        ((26, 11, 30), "half past eleven"),  # under six hours
        ((26, 8, 0), "eight o'clock this morning"),
        ((26, 1, 0), "one o'clock early this morning"),
        ((26, 0, 0), "midnight"),
        ((25, 20, 0), "eight o'clock yesterday evening"),
        ((25, 14, 15), "quarter past two yesterday afternoon"),
        ((25, 7, 0), "seven o'clock yesterday morning"),
        ((25, 22, 30), "half past ten last night"),
        ((25, 3, 0), "three o'clock early yesterday morning"),
        ((25, 12, 0), "midday yesterday"),
        ((23, 18, 0), "six o'clock on Friday"),
        ((20, 9, 0), "nine o'clock on Tuesday"),  # six days ago
        ((19, 9, 0), "the 19th of October"),  # seven days ago
        ((16, 9, 0), "the 16th of October"),
        ((1, 9, 0), "the 1st of October"),
        ((22, 9, 0, 9), "the 22nd of September"),
        ((3, 9, 0, 9), "the 3rd of September"),
        ((12, 9, 0, 9), "the 12th of September"),
    ],
)
def test_since_phrase(when, expected) -> None:
    assert _since_phrase(local(*when), now()) == expected


def test_this_evening_and_tonight() -> None:
    late = local(26, 23, 30)
    assert _since_phrase(local(26, 17, 30), late) == "half past five this evening"
    assert _since_phrase(local(26, 9, 0), late) == "nine o'clock this morning"
    assert _since_phrase(local(26, 13, 0), late) == "one o'clock this afternoon"
    assert _since_phrase(local(26, 21, 15), local(26, 23, 59)) == "quarter past nine"
    assert (
        _since_phrase(local(26, 21, 15), local(27, 4, 0))
        == "quarter past nine last night"
    )
    assert _since_phrase(local(26, 22, 0), local(27, 4, 0)) == "ten o'clock last night"


async def _set_at(hass, freezer, when, entity_id, state, attrs=None):
    freezer.move_to(dt_util.as_utc(when))
    hass.states.async_set(entity_id, state, attrs or {})


async def test_location_says_how_long_they_have_been_home(hass, users, freezer) -> None:
    await _set_at(hass, freezer, local(26, 15, 0), "person.james", "home")
    freezer.move_to(dt_util.as_utc(now()))
    result = await _where(hass, users["Sarah"])
    assert result["since_spoken"] == "home since three o'clock"
    assert result["since"] == local(26, 15, 0).isoformat()


async def test_location_says_how_long_they_have_been_at_the_reported_address(
    hass, users, freezer
) -> None:
    await _set_at(hass, freezer, local(26, 8, 0), "person.james", "not_home")
    hass.states.async_set(
        "device_tracker.james_phone", "not_home", {"address": "Example Road"}
    )
    freezer.move_to(dt_util.as_utc(now()))
    result = await _where(hass, users["Sarah"])
    assert result["since_spoken"] == "Example Road since eight o'clock this morning"
    assert "away" not in str(result)


async def test_location_since_for_a_named_zone(hass, users, freezer) -> None:
    await _set_at(hass, freezer, local(25, 9, 0), "person.james", "Work")
    freezer.move_to(dt_util.as_utc(now()))
    result = await _where(hass, users["Sarah"])
    assert result["since_spoken"] == "Work since nine o'clock yesterday morning"


async def test_location_since_just_now(hass, users, freezer) -> None:
    await _set_at(hass, freezer, now(), "person.james", "home")
    result = await _where(hass, users["Sarah"])
    assert result["since_spoken"] == "home, as of just now"


async def test_location_since_uses_the_entity_that_gave_the_location(
    hass, users, freezer
) -> None:
    await _set_at(hass, freezer, local(26, 9, 0), "person.james", "not_home")
    await _set_at(
        hass,
        freezer,
        local(26, 15, 0),
        "device_tracker.james_phone",
        "not_home",
        {"address": "Example Road"},
    )
    freezer.move_to(dt_util.as_utc(now()))
    result = await _where(hass, users["Sarah"])
    assert result["since_spoken"] == "Example Road since nine o'clock this morning"


async def test_no_since_when_unavailable_private_or_unassigned(
    hass, users, freezer
) -> None:
    hass.states.async_set("person.james", "unavailable")
    hass.states.async_set("device_tracker.james_phone", "unknown")
    unavailable = await _where(hass, users["Sarah"])
    assert unavailable["location"] == "unavailable"
    assert "since" not in unavailable and "since_spoken" not in unavailable
    private = await _where(hass, users["James"], "Aunt")
    assert "since" not in private
    unassigned = await _where(hass, users["James"], "Mum")
    assert "since" not in unassigned


async def test_unknown_address_note_is_not_supplemented_with_a_location_guess(
    hass, users, freezer
) -> None:
    await _set_at(
        hass, freezer, local(26, 15, 0), "device_tracker.james_phone", "not_home"
    )
    freezer.move_to(dt_util.as_utc(now()))
    result = await _where(hass, users["Sarah"])
    assert result["location"] == "outside known zones"
    assert "since_spoken" not in result
    assert "An exact address for Dad is unknown" in result["address_note"]


# ---------------------------------------------------------------------- prompt/schema


# ------------------------------------------------------------------ device location

_BEACON = "1234abcd-0000-4000-8000-00000000beef_100_1"
_BEACON_KEY = _BEACON.replace("-", "")


def _phone_with_beacon(
    hass: HomeAssistant, *, room: str | None = "Study", tracker: str = "bermuda"
) -> None:
    """Register a Companion App phone whose BLE transmitter another integration tracks."""
    phone_config = MockConfigEntry(domain="mobile_app")
    phone_config.add_to_hass(hass)
    devices = dr.async_get(hass)
    registry = er.async_get(hass)
    phone = devices.async_get_or_create(
        config_entry_id=phone_config.entry_id,
        identifiers={("mobile_app", "james")},
        name="James Example",
        model="Example Phone 9",
    )
    registry.async_get_or_create(
        "device_tracker",
        "mobile_app",
        "james-tracker",
        device_id=phone.id,
        config_entry=phone_config,
        suggested_object_id="james_phone",
    )
    registry.async_get_or_create(
        "sensor",
        "mobile_app",
        "james-hook_ble_emitter",
        device_id=phone.id,
        config_entry=phone_config,
        suggested_object_id="james_phone_ble_transmitter",
    )
    hass.states.async_set(
        "sensor.james_phone_ble_transmitter", "Transmitting", {"id": _BEACON}
    )
    hass.states.async_set("device_tracker.james_phone", "home")

    bermuda_config = MockConfigEntry(domain=tracker)
    bermuda_config.add_to_hass(hass)
    beacon = devices.async_get_or_create(
        config_entry_id=bermuda_config.entry_id,
        identifiers={(tracker, _BEACON_KEY)},
        name=_BEACON_KEY,
    )
    for domain, object_id in (
        ("sensor", "james_beacon_area"),
        ("device_tracker", "james_beacon"),
    ):
        registry.async_get_or_create(
            domain,
            tracker,
            f"{_BEACON_KEY}-{domain}",
            device_id=beacon.id,
            config_entry=bermuda_config,
            suggested_object_id=object_id,
        )
    hass.states.async_set(
        "sensor.james_beacon_area",
        room or "unknown",
        {"area_id": "study", "area_name": room} if room else {},
    )
    hass.states.async_set("device_tracker.james_beacon", "home")
    hass.states.async_set(
        "person.james",
        "home",
        {
            "device_trackers": [
                "device_tracker.james_phone",
                "device_tracker.james_beacon",
            ]
        },
    )


async def _devices(hass, user, **args):
    data, error = await call(hass, user, "get_device_location", **args)
    assert not error
    return data["people"][0]


async def test_my_phone_is_in_the_room_bermuda_reports(hass, users, freezer) -> None:
    freezer.move_to(local(26, 15, 0))
    _phone_with_beacon(hass)
    freezer.move_to(now())
    result = await _devices(hass, users["James"])
    assert result["person"] == "Dad"
    assert result["devices"] == [
        {
            "device": "james phone",
            "entity_id": "device_tracker.james_phone",
            "room": "Study",
            "location": "home",
            "since_spoken": "in the Study since three o'clock",
        }
    ]


async def test_any_ble_tracking_integration_gives_the_room(hass, users) -> None:
    _phone_with_beacon(hass, tracker="example_ble")
    result = await _devices(hass, users["James"])
    assert [(d["entity_id"], d.get("room")) for d in result["devices"]] == [
        ("device_tracker.james_phone", "Study")
    ]


async def test_beacon_not_on_the_person_entity_is_not_used(hass, users) -> None:
    _phone_with_beacon(hass)
    hass.states.async_set(
        "person.james", "home", {"device_trackers": ["device_tracker.james_phone"]}
    )
    device = (await _devices(hass, users["James"]))["devices"][0]
    assert "room" not in device
    assert "room_note" in device


async def test_unregistered_tracker_from_the_person_entity_is_a_device(
    hass, users
) -> None:
    _phone_with_beacon(hass)
    hass.states.async_set(
        "person.james",
        "home",
        {"device_trackers": ["device_tracker.james_phone", "device_tracker.other"]},
    )
    hass.states.async_set("device_tracker.other", "home")
    result = await _devices(hass, users["Sarah"], people=["Dad"])
    by_id = {d["entity_id"]: d for d in result["devices"]}
    assert by_id["device_tracker.other"]["device"] == "device"
    assert by_id["device_tracker.other"]["room_note"].startswith("No room is known")
    assert "James Example" not in str(result)


async def test_trackers_come_from_the_person_entity(hass, users) -> None:
    _phone_with_beacon(hass)
    hass.states.async_set("person.kim_extra", "home")
    result = await _devices(hass, users["Sarah"], people=["Dad"])
    assert [d["entity_id"] for d in result["devices"]] == ["device_tracker.james_phone"]
    assert result["devices"][0]["room"] == "Study"


async def test_no_room_while_the_phone_is_away(hass, users) -> None:
    _phone_with_beacon(hass)
    hass.states.async_set(
        "device_tracker.james_phone", "not_home", {"address": "17 Fixture Lane"}
    )
    device = (await _devices(hass, users["James"]))["devices"][0]
    assert "room" not in device
    assert device["location"] == "Fixture Lane"


async def test_unknown_room_says_home_without_guessing(hass, users) -> None:
    _phone_with_beacon(hass, room=None)
    device = (await _devices(hass, users["James"]))["devices"][0]
    assert "room" not in device
    assert device["location"] == "home"
    assert "do not guess a room" in device["room_note"]


async def test_away_phone_without_address_gets_exact_reply(hass, users) -> None:
    hass.states.async_set("person.james", "not_home")
    hass.states.async_set("device_tracker.james_phone", "not_home")
    devices = (await _devices(hass, users["Sarah"], people=["Dad"]))["devices"]
    assert devices[0]["address_note"].startswith(
        "Reply with exactly: \"Sorry Mum, An exact address for Dad's"
    )
    assert "since_spoken" not in devices[0]


async def test_device_filter_picks_one_device(hass, users) -> None:
    _phone_with_beacon(hass)
    result = await _devices(hass, users["James"], device="phone")
    assert [d["entity_id"] for d in result["devices"]] == ["device_tracker.james_phone"]
    data, error = await call(
        hass, users["James"], "get_device_location", device="tablet"
    )
    assert error
    assert _problems(data)["device_not_found"][0]["options"]


async def test_device_location_respects_privacy(hass, users) -> None:
    hass.states.async_set("device_tracker.ann_phone", "home")
    hass.states.async_set(
        "person.james", "home", {"device_trackers": ["device_tracker.ann_phone"]}
    )
    result = await _devices(hass, users["James"])
    assert "device_tracker.ann_phone" not in str(result)
    tom = await _devices(hass, users["James"], people=["Grandad"])
    assert tom == {"person": "Grandad", "devices": [], "reason": "private"}
    own = await _devices(hass, users["Ann"])
    assert [d["entity_id"] for d in own["devices"]] == ["device_tracker.ann_phone"]


async def test_private_room_sensor_is_not_read_for_others(hass) -> None:
    _phone_with_beacon(hass)
    owner = Person(
        "u1", "Kim", "Cousin", private=frozenset({"sensor.james_beacon_area"})
    )
    other = Person("u2", "Sam", "Sam")
    (beacon,) = dr.async_get(hass).async_get_devices(
        identifiers={("bermuda", _BEACON_KEY)}
    )  # registered by _phone_with_beacon
    assert _device_room(hass, Household([owner, other], other), beacon.id) is None
    assert _device_room(hass, Household([owner, other], owner), beacon.id)[0] == "Study"


# ----------------------------------------------------------- private location


def _hidden_household(users, speaker="James"):
    james = Person(
        users["James"].id,
        "James",
        "Dad",
        (("device_tracker.james_phone", "Phone"),),
        person_entity="person.james",
    )
    sarah = Person(
        users["Sarah"].id,
        "Sarah",
        "Mum",
        (("person.sarah", "Sarah"), ("device_tracker.sarah_phone", "Phone")),
        person_entity="person.sarah",
        location_private=True,
    )
    return Household([james, sarah], james if speaker == "James" else sarah)


async def _ask(hass, users, tool_cls, speaker="James", **args):
    tool = tool_cls(_hidden_household(users, speaker))
    api_instance = await instance(hass, users[speaker])
    result = await tool.async_call(
        hass,
        llm.ToolInput(tool_name=tool.name, tool_args=args),
        api_instance.llm_context,
    )
    return result.data, result.error


def _sarah_is(hass, zone: str, phone: str | None = None, **attributes) -> None:
    hass.states.async_set(
        "person.sarah",
        zone,
        {"device_trackers": ["device_tracker.sarah_phone"], **attributes},
    )
    hass.states.async_set("device_tracker.sarah_phone", phone or zone)


async def test_others_get_a_privacy_note_instead_of_a_private_location(
    hass, users
) -> None:
    _sarah_is(hass, "Work")
    data, error = await _ask(
        hass, users, location_tools.GetPersonLocationTool, people=["Mum"]
    )
    assert not error
    (entry,) = data["people"]
    assert entry["reason"] == "private" and entry["location"] is None
    assert "Mum's location is private" in entry["note"]
    assert "Work" not in str(data)


async def test_home_is_hidden_too_for_a_private_location(hass, users) -> None:
    _sarah_is(hass, "home")
    data, _ = await _ask(hass, users, location_tools.GetPersonLocationTool)
    by_person = {p["person"]: p for p in data["people"]}
    assert by_person["Mum"]["reason"] == "private"
    assert "home" not in str(by_person["Mum"]).replace("whether they are home", "")


async def test_owner_still_sees_their_own_private_location(hass, users) -> None:
    _sarah_is(hass, "Work")
    data, error = await _ask(
        hass, users, location_tools.GetPersonLocationTool, speaker="Sarah", people=["me"]
    )
    assert not error
    assert data["people"][0]["location"] == "Work"


async def test_private_location_hides_the_history(hass, users) -> None:
    data, error = await _ask(
        hass,
        users,
        location_tools.GetPersonLocationHistoryTool,
        people=["Mum"],
        start="2026-10-29",
        end="2026-10-30",
    )
    assert not error
    assert data["people"][0]["reason"] == "private"
    assert data["people"][0]["history"] == []


async def test_private_location_device_at_home_gives_home(hass, users) -> None:
    _sarah_is(hass, "home")
    data, error = await _ask(
        hass, users, location_tools.GetDeviceLocationTool, people=["Mum"]
    )
    assert not error
    (device,) = data["people"][0]["devices"]
    assert device["location"] == "home"


async def test_private_location_device_at_home_gives_its_room(hass, users) -> None:
    config = MockConfigEntry(domain="test")
    config.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config.entry_id, identifiers={("test", "sarah")}
    )
    er.async_get(hass).async_get_or_create(
        "device_tracker",
        "test",
        "sarah-phone",
        device_id=device.id,
        config_entry=config,
        suggested_object_id="sarah_phone",
    )
    _sarah_is(hass, "home")
    hass.states.async_set("device_tracker.sarah_phone", "home", {"area": "Study"})
    data, _ = await _ask(
        hass, users, location_tools.GetDeviceLocationTool, people=["Mum"]
    )
    assert data["people"][0]["devices"][0]["room"] == "Study"


async def test_private_location_device_away_gets_a_privacy_note(hass, users) -> None:
    _sarah_is(hass, "Work")
    data, error = await _ask(
        hass, users, location_tools.GetDeviceLocationTool, people=["Mum"]
    )
    assert not error
    (device,) = data["people"][0]["devices"]
    assert device["reason"] == "private" and device["location"] is None
    assert "Mum's location is private" in device["note"]
    assert "Work" not in str(data) and "entity_id" not in device


async def test_private_location_device_away_outside_zones_hides_the_address(
    hass, users
) -> None:
    _sarah_is(hass, "not_home", address="17 Fixture Lane")
    data, _ = await _ask(
        hass, users, location_tools.GetDeviceLocationTool, people=["Mum"]
    )
    assert "Fixture" not in str(data)
    assert data["people"][0]["devices"][0]["reason"] == "private"


async def test_private_location_device_unavailable_says_so(hass, users) -> None:
    _sarah_is(hass, "home", phone="unavailable")
    data, _ = await _ask(
        hass, users, location_tools.GetDeviceLocationTool, people=["Mum"]
    )
    assert data["people"][0]["devices"][0]["location"] == "unavailable"


async def test_private_location_blocks_direct_state_reads(hass, users) -> None:
    _sarah_is(hass, "Work")
    for entity in ("person.sarah", "device_tracker.sarah_phone"):
        data, error = await _ask(
            hass,
            users,
            entity_tools.GetEntityStateTool,
            entity=entity,
            person="Mum",
        )
        assert error and data["problem"] == "private"
        assert "Work" not in str(data)


async def test_owner_can_read_their_own_person_entity(hass, users) -> None:
    _sarah_is(hass, "Work")
    data, error = await _ask(
        hass,
        users,
        entity_tools.GetEntityStateTool,
        speaker="Sarah",
        entity="person.sarah",
    )
    assert not error and data["state"] == "Work"

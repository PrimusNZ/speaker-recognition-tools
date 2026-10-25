"""Tests for the person-aware calendar and location tools and their privacy rules."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import Context, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_PRIVATE_ENTITIES,
    CONF_TITLE,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_TITLE,
    CONF_USER_ID,
    DOMAIN,
    PERSON_API_ID,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
)

PEOPLE = {
    # name: (title, entities, private)
    "James": ("Dad", ["calendar.james", "person.james", "device_tracker.james_phone"], []),
    "Sarah": (
        "Mum",
        ["calendar.sarah_home", "calendar.sarah_work", "calendar.sarah_diary"],
        ["calendar.sarah_diary"],
    ),
    "Ann": (
        "Aunt",
        ["calendar.ann", "calendar.ann_shared", "device_tracker.ann_phone"],
        ["calendar.ann", "device_tracker.ann_phone"],
    ),
    "Tom": (
        "Grandad",
        ["calendar.tom", "device_tracker.tom_phone"],
        ["calendar.tom", "device_tracker.tom_phone"],
    ),
}


class Calendars:
    """Fake calendar services that record every call."""

    def __init__(self) -> None:
        self.reads: list[dict] = []
        self.creates: list[dict] = []
        self.fail_on: set[str] = set()


@pytest.fixture
async def calendars(hass: HomeAssistant) -> Calendars:
    fake = Calendars()

    async def get_events(call: ServiceCall):
        entity_id = call.data["entity_id"]
        fake.reads.append(dict(call.data))
        if entity_id in fake.fail_on:
            raise HomeAssistantError("calendar offline")
        return {entity_id: {"events": [{"summary": f"event on {entity_id}"}]}}

    async def create_event(call: ServiceCall) -> None:
        if call.data["entity_id"] in fake.fail_on:
            raise HomeAssistantError("calendar is read only")
        fake.creates.append(dict(call.data))

    hass.services.async_register(
        "calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register("calendar", "create_event", create_event)
    return fake


@pytest.fixture
async def users(hass: HomeAssistant, calendars: Calendars):
    accounts = {
        name: await hass.auth.async_create_user(name, group_ids=["system-users"])
        for name in PEOPLE
    }
    subentries = [
        ConfigSubentryData(
            subentry_type=SUBENTRY_SPEAKER,
            title=name,
            unique_id=accounts[name].id,
            data={
                CONF_USER_ID: accounts[name].id,
                CONF_TITLE: title,
                CONF_ENTITIES: entities,
                CONF_PRIVATE_ENTITIES: private,
            },
        )
        for name, (title, entities, private) in PEOPLE.items()
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={CONF_UNKNOWN_TITLE: "Unknown Person", CONF_DENY_UNKNOWN: False},
        subentries_data=subentries,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return accounts


async def instance(hass: HomeAssistant, user) -> llm.APIInstance:
    context = llm.LLMContext(
        platform="test",
        context=Context(user_id=user.id),
        language="en",
        assistant="conversation",
        device_id=None,
    )
    return await llm.async_get_api(hass, PERSON_API_ID, context)


async def call(hass, user, tool: str, **args):
    """Call a tool directly (async_call_tool needs the conversation component)."""
    inst = await instance(hass, user)
    chosen = next(t for t in inst.tools if t.name == tool)
    result = await chosen.async_call(
        hass, llm.ToolInput(tool_name=tool, tool_args=args), inst.llm_context
    )
    return result.data, result.error


def _entities(data: dict, key: str = "calendars") -> list[str]:
    return [c["entity_id"] for c in data.get(key, [])]


def _problems(data: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in data.get("problems", []):
        out.setdefault(p["problem"], []).append(p)
    return out


RANGE = {"start": "2026-10-29T09:00:00", "end": "2026-10-29T17:00:00"}

# ----------------------------------------------------------------------------- read


async def test_read_own_calendar_by_default(hass, users, calendars) -> None:
    data, error = await call(hass, users["James"], "get_calendar_events", **RANGE)
    assert not error
    assert _entities(data) == ["calendar.james"]
    assert data["calendars"][0]["person"] == "Dad"
    assert calendars.reads[0]["entity_id"] == "calendar.james"
    assert calendars.reads[0]["start_date_time"].startswith("2026-10-29T09:00:00")
    assert calendars.reads[0]["end_date_time"].startswith("2026-10-29T17:00:00")


@pytest.mark.parametrize("who", ["me", "I", "my", "Dad", "James", "dad"])
async def test_read_self_by_any_name(hass, users, who) -> None:
    data, _ = await call(
        hass, users["James"], "get_calendar_events", people=[who], **RANGE
    )
    assert _entities(data) == ["calendar.james"]


async def test_read_other_person_asks_which_calendar_and_hides_private(
    hass, users, calendars
) -> None:
    data, error = await call(
        hass, users["James"], "get_calendar_events", people=["Mum"], **RANGE
    )
    assert error
    choose = _problems(data)["choose_calendar"][0]
    assert [o["entity_id"] for o in choose["options"]] == [
        "calendar.sarah_home",
        "calendar.sarah_work",
    ]
    assert "calendar.sarah_diary" not in str(data)
    assert calendars.reads == []


async def test_read_other_person_with_choice(hass, users, calendars) -> None:
    data, error = await call(
        hass,
        users["James"],
        "get_calendar_events",
        people=["Mum"],
        calendars=["calendar.sarah_work"],
        **RANGE,
    )
    assert not error
    assert _entities(data) == ["calendar.sarah_work"]


async def test_read_can_choose_several_calendars_of_one_person(hass, users) -> None:
    data, _ = await call(
        hass,
        users["James"],
        "get_calendar_events",
        people=["Sarah"],
        calendars=["calendar.sarah_home", "calendar.sarah_work"],
        **RANGE,
    )
    assert _entities(data) == ["calendar.sarah_home", "calendar.sarah_work"]


async def test_private_calendar_cannot_be_chosen_by_someone_else(
    hass, users, calendars
) -> None:
    data, error = await call(
        hass,
        users["James"],
        "get_calendar_events",
        people=["Mum"],
        calendars=["calendar.sarah_diary"],
        **RANGE,
    )
    assert error
    assert calendars.reads == []
    problems = _problems(data)
    assert "calendar_not_available" in problems
    assert "choose_calendar" in problems


async def test_owner_can_read_their_private_calendar(hass, users, calendars) -> None:
    data, error = await call(
        hass,
        users["Sarah"],
        "get_calendar_events",
        calendars=["calendar.sarah_diary"],
        **RANGE,
    )
    assert not error
    assert _entities(data) == ["calendar.sarah_diary"]


async def test_owner_is_asked_to_choose_between_all_their_calendars(hass, users) -> None:
    data, _ = await call(hass, users["Sarah"], "get_calendar_events", **RANGE)
    options = _problems(data)["choose_calendar"][0]["options"]
    assert [o["entity_id"] for o in options] == [
        "calendar.sarah_home",
        "calendar.sarah_work",
        "calendar.sarah_diary",
    ]


async def test_fully_private_calendar_is_refused(hass, users, calendars) -> None:
    data, error = await call(
        hass, users["James"], "get_calendar_events", people=["Grandad"], **RANGE
    )
    assert error
    assert _problems(data)["private"][0]["person"] == "Grandad"
    assert calendars.reads == []


async def test_partly_private_person_uses_the_shared_calendar(
    hass, users, calendars
) -> None:
    data, error = await call(
        hass, users["James"], "get_calendar_events", people=["Aunt"], **RANGE
    )
    assert not error
    assert _entities(data) == ["calendar.ann_shared"]
    assert "'calendar.ann'" not in str(data)


async def test_several_people_in_one_request(hass, users) -> None:
    data, error = await call(
        hass,
        users["James"],
        "get_calendar_events",
        people=["me", "Mum"],
        calendars=["calendar.sarah_home"],
        **RANGE,
    )
    assert not error
    assert _entities(data) == ["calendar.james", "calendar.sarah_home"]


async def test_one_blocked_person_does_not_hide_the_others(hass, users) -> None:
    data, error = await call(
        hass, users["James"], "get_calendar_events", people=["me", "Grandad"], **RANGE
    )
    assert not error
    assert _entities(data) == ["calendar.james"]
    assert "private" in _problems(data)


async def test_unknown_person(hass, users) -> None:
    data, error = await call(
        hass, users["James"], "get_calendar_events", people=["Bob"], **RANGE
    )
    assert error
    problem = _problems(data)["unknown_person"][0]
    assert problem["name"] == "Bob"
    assert "Dad" in problem["known_people"]


async def test_date_only_end_includes_the_whole_day(hass, users, calendars) -> None:
    await call(
        hass,
        users["James"],
        "get_calendar_events",
        start="2026-10-29",
        end="2026-10-29",
    )
    read = calendars.reads[0]
    assert read["start_date_time"].startswith("2026-10-29T00:00:00")
    assert read["end_date_time"].startswith("2026-10-30T00:00:00")


@pytest.mark.parametrize(
    "args",
    [
        {"start": "soon", "end": "2026-10-29"},
        {"start": "2026-10-29T10:00:00", "end": "2026-10-29T09:00:00"},
    ],
)
async def test_bad_dates_are_errors(hass, users, calendars, args) -> None:
    data, error = await call(hass, users["James"], "get_calendar_events", **args)
    assert error and "error" in data
    assert calendars.reads == []


async def test_calendar_failure_is_reported(hass, users, calendars) -> None:
    calendars.fail_on.add("calendar.james")
    data, error = await call(hass, users["James"], "get_calendar_events", **RANGE)
    assert error
    assert _problems(data)["read_failed"][0]["entity_id"] == "calendar.james"


# --------------------------------------------------------------------------- create


async def test_create_for_self_defaults_to_one_hour(hass, users, calendars) -> None:
    data, error = await call(
        hass,
        users["James"],
        "create_calendar_event",
        summary="Dentist",
        start="2026-10-31T15:00:00",
        description="Check-up",
        location="Main St",
    )
    assert not error
    assert data["created"] == [{"person": "Dad", "calendar": "calendar.james"}]
    made = calendars.creates[0]
    assert made["entity_id"] == "calendar.james"
    assert made["summary"] == "Dentist"
    assert made["start_date_time"].startswith("2026-10-31T15:00:00")
    assert made["end_date_time"].startswith("2026-10-31T16:00:00")
    assert made["description"] == "Check-up"
    assert made["location"] == "Main St"


async def test_create_on_several_peoples_calendars(hass, users, calendars) -> None:
    data, error = await call(
        hass,
        users["James"],
        "create_calendar_event",
        people=["me", "Mum"],
        calendars=["calendar.sarah_home"],
        summary="Dinner",
        start="2026-10-31T19:00:00",
        end="2026-10-31T21:00:00",
    )
    assert not error
    assert [c["entity_id"] for c in calendars.creates] == [
        "calendar.james",
        "calendar.sarah_home",
    ]
    assert calendars.creates[1]["end_date_time"].startswith("2026-10-31T21:00:00")


async def test_create_is_all_or_nothing_when_a_choice_is_needed(
    hass, users, calendars
) -> None:
    data, error = await call(
        hass,
        users["James"],
        "create_calendar_event",
        people=["me", "Mum"],
        summary="Dinner",
        start="2026-10-31T19:00:00",
    )
    assert error
    assert calendars.creates == []
    assert "choose_calendar" in _problems(data)
    assert "Nothing was created" in data["note"]


async def test_create_is_refused_on_someone_elses_private_calendar(
    hass, users, calendars
) -> None:
    data, error = await call(
        hass,
        users["James"],
        "create_calendar_event",
        people=["me", "Grandad"],
        summary="Visit",
        start="2026-10-31T10:00:00",
    )
    assert error
    assert calendars.creates == []
    assert "private" in _problems(data)


async def test_create_on_someone_elses_private_calendar_by_id_is_refused(
    hass, users, calendars
) -> None:
    _, error = await call(
        hass,
        users["James"],
        "create_calendar_event",
        people=["Mum"],
        calendars=["calendar.sarah_diary"],
        summary="Snoop",
        start="2026-10-31T10:00:00",
    )
    assert error
    assert calendars.creates == []


async def test_owner_can_create_on_their_private_calendar(hass, users, calendars) -> None:
    _, error = await call(
        hass,
        users["Sarah"],
        "create_calendar_event",
        calendars=["calendar.sarah_diary"],
        summary="Secret",
        start="2026-10-31T10:00:00",
    )
    assert not error
    assert calendars.creates[0]["entity_id"] == "calendar.sarah_diary"


async def test_create_all_day_event(hass, users, calendars) -> None:
    await call(
        hass, users["James"], "create_calendar_event", summary="Holiday", start="2026-10-31"
    )
    made = calendars.creates[0]
    assert made["start_date"] == "2026-10-31"
    assert made["end_date"] == "2026-11-01"
    assert "start_date_time" not in made


async def test_all_day_end_date_is_inclusive(hass, users, calendars) -> None:
    await call(
        hass,
        users["James"],
        "create_calendar_event",
        summary="Trip",
        start="2026-10-31",
        end="2026-11-02",
    )
    assert calendars.creates[0]["end_date"] == "2026-11-03"


async def test_mixed_date_and_datetime_is_an_error(hass, users, calendars) -> None:
    data, error = await call(
        hass,
        users["James"],
        "create_calendar_event",
        summary="x",
        start="2026-10-31",
        end="2026-11-01T10:00:00",
    )
    assert error and "error" in data
    assert calendars.creates == []


async def test_create_reports_partial_failure(hass, users, calendars) -> None:
    calendars.fail_on.add("calendar.sarah_home")
    data, error = await call(
        hass,
        users["James"],
        "create_calendar_event",
        people=["me", "Mum"],
        calendars=["calendar.sarah_home"],
        summary="Dinner",
        start="2026-10-31T19:00:00",
    )
    assert error
    assert data["created"] == [{"person": "Dad", "calendar": "calendar.james"}]
    assert data["failed"][0]["calendar"] == "calendar.sarah_home"


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
        "device_tracker.james_phone": "away",
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
    assert set(by_person) == {"Dad", "Mum", "Aunt", "Grandad"}
    assert by_person["Dad"]["location"] == "home"
    assert by_person["Mum"]["reason"] == "no location entity assigned"
    assert by_person["Aunt"] == {"person": "Aunt", "location": None, "reason": "private"}
    assert by_person["Grandad"]["reason"] == "private"
    assert "device_tracker.ann_phone" not in str(data)


async def test_owner_can_see_their_private_tracker(hass, users) -> None:
    hass.states.async_set("device_tracker.ann_phone", "not_home")
    data, _ = await call(hass, users["Ann"], "get_person_location", people=["me"])
    assert data["people"][0]["location"] == "away"


async def test_location_unknown_person(hass, users) -> None:
    data, error = await call(hass, users["James"], "get_person_location", people=["Bob"])
    assert error
    assert _problems(data)["unknown_person"]


# ---------------------------------------------------------------------- prompt/schema


async def test_others_private_entities_are_not_in_the_prompt(hass, users) -> None:
    prompt = (await instance(hass, users["James"])).api_prompt
    assert "calendar.sarah_home" in prompt
    assert "calendar.ann_shared" in prompt
    for hidden in ("calendar.sarah_diary", "calendar.ann |", "calendar.ann\n", "device_tracker.ann_phone", "calendar.tom", "device_tracker.tom_phone"):
        assert hidden not in prompt
    assert not [l for l in prompt.splitlines() if l.startswith(" - ") and l.endswith("(private)")]


async def test_owners_private_entities_are_marked_in_their_prompt(hass, users) -> None:
    prompt = (await instance(hass, users["Sarah"])).api_prompt
    assert " - calendar.sarah_diary (private)" in prompt
    assert " - calendar.sarah_home\n" in prompt or " - calendar.sarah_home |" in prompt
    assert "Entities marked (private) belong only to that person" in prompt
    assert "get_calendar_events" in prompt and "get_person_location" in prompt


async def test_tool_schemas_validate(hass, users) -> None:
    tools = {t.name: t for t in (await instance(hass, users["James"])).tools}
    tools["get_calendar_events"].parameters({"start": "2026-10-29", "end": "2026-10-30"})
    tools["get_person_location"].parameters({})
    with pytest.raises(Exception):
        tools["get_calendar_events"].parameters({"start": "2026-10-29"})
    with pytest.raises(Exception):
        tools["create_calendar_event"].parameters({"summary": "x"})

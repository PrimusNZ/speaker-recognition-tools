"""Tests for the calendar tools and their privacy and confirmation rules."""

from __future__ import annotations

import pytest
from homeassistant.components.calendar import CalendarEvent
from homeassistant.components.calendar.const import CalendarEntityFeature
from homeassistant.util import dt as dt_util

from custom_components.speaker_recognition_tools import calendar_tools
from custom_components.speaker_recognition_tools.const import (
    CONF_ENTITY_ALIASES,
    CONF_TOOL_TYPE,
    CONF_USER_ID,
    DOMAIN,
    TOOL_TYPE_PERSON,
)
from tests.tools.helpers import (
    RANGE,
    _entities,
    _problems,
    call,
    confirmed_call,
)

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


async def test_owner_is_asked_to_choose_between_all_their_calendars(
    hass, users
) -> None:
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


async def test_search_and_availability_use_calendar_events(
    hass, users, monkeypatch
) -> None:
    event = CalendarEvent(
        start=dt_util.parse_datetime("2026-10-29T10:00:00+13:00"),
        end=dt_util.parse_datetime("2026-10-29T11:00:00+13:00"),
        summary="Dentist appointment",
        uid="event-1",
    )

    async def events(*_args):
        return [event]

    monkeypatch.setattr(calendar_tools, "_calendar_events", events)
    data, error = await call(
        hass,
        users["James"],
        "search_calendar_events",
        query="DENTIST",
        **RANGE,
    )
    assert not error
    assert data["matches"][0]["event"]["uid"] == "event-1"

    data, error = await call(
        hass,
        users["James"],
        "check_calendar_availability",
        start="2026-10-29T10:30:00",
        end="2026-10-29T11:30:00",
    )
    assert not error
    assert data["calendars"][0]["available"] is False
    assert data["calendars"][0]["conflicts"][0]["summary"] == "Dentist appointment"


async def test_update_and_delete_calendar_events_require_confirmation(
    hass, users, monkeypatch
) -> None:
    event = CalendarEvent(
        start=dt_util.parse_datetime("2026-10-29T10:00:00+13:00"),
        end=dt_util.parse_datetime("2026-10-29T11:00:00+13:00"),
        summary="Dentist appointment",
        uid="event-1",
    )

    class Entity:
        supported_features = (
            CalendarEntityFeature.UPDATE_EVENT | CalendarEntityFeature.DELETE_EVENT
        )
        updates = []
        deletions = []

        async def async_update_event(self, uid, data, recurrence_id=None):
            self.updates.append((uid, data, recurrence_id))

        async def async_delete_event(self, uid, recurrence_id=None):
            self.deletions.append((uid, recurrence_id))

    entity = Entity()
    monkeypatch.setattr(calendar_tools, "_calendar_entity", lambda *_args: entity)

    async def events(*_args):
        return [event]

    monkeypatch.setattr(calendar_tools, "_calendar_events", events)
    update_args = {
        "uid": "event-1",
        "start": "2026-10-29",
        "end": "2026-10-30",
        "summary": "Doctor",
    }
    preview, error = await call(
        hass, users["James"], "update_calendar_event", **update_args
    )
    assert not error and preview["confirmation_required"]
    assert entity.updates == []
    result, error = await call(
        hass,
        users["James"],
        "update_calendar_event",
        **update_args,
        confirmation_token=preview["confirmation_token"],
        confirmed=True,
    )
    assert not error and result["updated"] is True
    assert entity.updates[0][1]["summary"] == "Doctor"

    delete_args = {"uid": "event-1", "start": "2026-10-29", "end": "2026-10-30"}
    preview, error = await call(
        hass, users["James"], "delete_calendar_event", **delete_args
    )
    assert not error and preview["confirmation_required"]
    assert entity.deletions == []
    result, error = await call(
        hass,
        users["James"],
        "delete_calendar_event",
        **delete_args,
        confirmation_token=preview["confirmation_token"],
        confirmed=True,
    )
    assert not error and result["deleted"] is True
    assert entity.deletions == [("event-1", None)]


# --------------------------------------------------------------------------- create


async def test_create_for_self_defaults_to_one_hour(hass, users, calendars) -> None:
    data, error = await confirmed_call(
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


async def test_create_requires_confirmation_before_writing(
    hass, users, calendars
) -> None:
    args = {
        "summary": "Dentist",
        "start": "2026-10-31T15:00:00",
    }
    preview, error = await call(hass, users["James"], "create_calendar_event", **args)
    assert not error
    assert preview["confirmation_required"] is True
    assert preview["preview"]["event"]["summary"] == "Dentist"
    assert calendars.creates == []

    cancelled, error = await call(
        hass,
        users["James"],
        "create_calendar_event",
        **args,
        confirmation_token=preview["confirmation_token"],
        confirmed=False,
    )
    assert not error
    assert cancelled["cancelled"] is True
    assert calendars.creates == []


async def test_calendar_confirmation_uses_first_alias_as_name(
    hass, users, calendars
) -> None:
    entry = next(
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data[CONF_TOOL_TYPE] == TOOL_TYPE_PERSON
    )
    subentry = next(
        subentry
        for subentry in entry.subentries.values()
        if subentry.data[CONF_USER_ID] == users["Sarah"].id
    )
    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data={
            **subentry.data,
            CONF_ENTITY_ALIASES: {"calendar.sarah_work": ["Personal", "Diary"]},
        },
    )

    args = {
        "people": ["me"],
        "calendars": ["personal"],
        "summary": "Dentist",
        "start": "2026-10-31T15:00:00",
    }
    preview, error = await call(hass, users["Sarah"], "create_calendar_event", **args)
    assert not error
    assert preview["preview"]["calendars"] == [
        {"person": "Mum", "calendar": "Personal", "entity_id": "calendar.sarah_work"}
    ]
    assert calendars.creates == []

    created, error = await call(
        hass,
        users["Sarah"],
        "create_calendar_event",
        **args,
        confirmation_token=preview["confirmation_token"],
        confirmed=True,
    )
    assert not error
    assert created["created"] == [{"person": "Mum", "calendar": "Personal"}]
    assert calendars.creates[0]["entity_id"] == "calendar.sarah_work"


async def test_create_on_several_peoples_calendars(hass, users, calendars) -> None:
    data, error = await confirmed_call(
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


async def test_owner_can_create_on_their_private_calendar(
    hass, users, calendars
) -> None:
    _, error = await confirmed_call(
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
    await confirmed_call(
        hass,
        users["James"],
        "create_calendar_event",
        summary="Holiday",
        start="2026-10-31",
    )
    made = calendars.creates[0]
    assert made["start_date"] == "2026-10-31"
    assert made["end_date"] == "2026-11-01"
    assert "start_date_time" not in made


async def test_all_day_end_date_is_inclusive(hass, users, calendars) -> None:
    await confirmed_call(
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
    data, error = await confirmed_call(
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

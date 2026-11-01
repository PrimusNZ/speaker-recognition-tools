"""Tests for the household, entity aliases, tool descriptions and prompt privacy."""

from __future__ import annotations

import pytest

from custom_components.speaker_recognition_tools import (
    location_tools,
    tool_base,
)
from custom_components.speaker_recognition_tools.prompt import Person
from tests.tools.helpers import (
    instance,
)


def test_household_uses_third_person_reference_for_other_people():
    speaker = Person("u1", "Sarah", "Mum", third_person_reference="The mother")
    target = Person("u2", "James", "Dad", third_person_reference="The father")
    household = tool_base.Household([speaker, target], speaker)
    found, problems = household.find(["The father"])
    assert not problems
    assert found == [target]
    assert household.reference(speaker) == "The mother"
    assert household.reference(target) == "The father"
    assert (
        "An exact address for The father is unknown."
        in location_tools._no_address_note(speaker, target)
    )

    untitled = Person("u3", "Tom", "")
    household = tool_base.Household([speaker, untitled], speaker)
    found, problems = household.find(["Tom"])
    assert not problems
    assert found == [untitled]
    assert household.reference(untitled) == "Tom"


def test_calendar_alias_selects_assigned_calendar():
    speaker = Person(
        "u1",
        "James",
        "Dad",
        (("calendar.james_work", "James Work"), ("calendar.james_home", "James Home")),
        entity_aliases=(
            ("calendar.james_work", ("work", "office diary")),
            ("calendar.james_home", ("home",)),
        ),
    )
    household = tool_base.Household([speaker], speaker)

    targets, problems = household.resolve_calendars([speaker], ["OFFICE DIARY"])

    assert targets == [(speaker, "calendar.james_work", "work")]
    assert not problems


def test_ambiguous_calendar_alias_returns_choices():
    speaker = Person(
        "u1",
        "James",
        "Dad",
        (("calendar.james_work", "James Work"), ("calendar.james_home", "James Home")),
        entity_aliases=(
            ("calendar.james_work", ("personal",)),
            ("calendar.james_home", ("personal",)),
        ),
    )
    household = tool_base.Household([speaker], speaker)

    targets, problems = household.resolve_calendars([speaker], ["personal"])

    assert not targets
    assert [p["problem"] for p in problems] == ["choose_calendar"]
    assert [o["entity_id"] for o in problems[0]["options"]] == [
        "calendar.james_work",
        "calendar.james_home",
    ]
    assert problems[0]["options"][0]["name"] == "personal"
    assert "aliases" not in problems[0]["options"][0]


def test_unknown_alias_does_not_select_a_single_calendar():
    speaker = Person(
        "u1",
        "James",
        "Dad",
        (("calendar.james_work", "James Work"),),
        entity_aliases=(("calendar.james_work", ("work",)),),
    )
    household = tool_base.Household([speaker], speaker)

    targets, problems = household.resolve_calendars([speaker], ["office"])

    assert not targets
    assert [p["problem"] for p in problems] == ["calendar_not_available"]


def test_other_person_cannot_select_private_calendar_by_alias():
    speaker = Person("u1", "James", "Dad")
    target = Person(
        "u2",
        "Sarah",
        "Mum",
        (("calendar.sarah_private", "Sarah Diary"),),
        frozenset({"calendar.sarah_private"}),
        entity_aliases=(("calendar.sarah_private", ("private diary",)),),
    )
    household = tool_base.Household([speaker, target], speaker)

    targets, problems = household.resolve_calendars([target], ["private diary"])

    assert not targets
    assert "private" in [p["problem"] for p in problems]
    assert "calendar_not_available" in [p["problem"] for p in problems]


async def test_tool_descriptions_document_person_aliases(hass, users) -> None:
    api_instance = await instance(hass, users["James"])
    descriptions = {tool.name: tool.description for tool in api_instance.tools}
    assert len(descriptions) == 15
    for description in descriptions.values():
        assert "first name" in description
        assert "configured form of address" in description
        assert "configured third-person reference" in description

    assert (
        "Omit people to use the current speaker" in descriptions["get_calendar_events"]
    )
    assert "Omit people to get everyone" in descriptions["get_person_location"]
    assert "use that as where they are" in descriptions["get_person_location"]
    assert (
        "follow address_note exactly and do not guess"
        in descriptions["get_person_location"]
    )
    assert "optional person parameter" in descriptions["update_calendar_event"]
    assert "optional person parameter" in descriptions["delete_calendar_event"]
    assert "current state and attributes" in descriptions["get_entity_state"]
    assert "one assigned entity" in descriptions["control_assigned_entity"]


async def test_others_private_entities_are_not_in_the_prompt(hass, users) -> None:
    prompt = (await instance(hass, users["James"])).api_prompt
    assert "calendar.sarah_home" in prompt
    assert "calendar.ann_shared" in prompt
    for hidden in (
        "calendar.sarah_diary",
        "calendar.ann |",
        "calendar.ann\n",
        "device_tracker.ann_phone",
        "calendar.tom",
        "device_tracker.tom_phone",
    ):
        assert hidden not in prompt
    assert not [
        line
        for line in prompt.splitlines()
        if line.startswith(" - ") and line.endswith("(private)")
    ]


async def test_owners_private_entities_are_shown_without_privacy_markers(
    hass, users
) -> None:
    prompt = (await instance(hass, users["Sarah"])).api_prompt
    assert " - calendar.sarah_diary" in prompt
    assert " - calendar.sarah_home\n" in prompt or " - calendar.sarah_home |" in prompt
    assert "(private)" not in prompt
    assert "Entities marked (private)" not in prompt
    assert "get_calendar_events" in prompt and "get_person_location" in prompt


async def test_tool_schemas_validate(hass, users) -> None:
    tools = {t.name: t for t in (await instance(hass, users["James"])).tools}
    tools["get_calendar_events"].parameters(
        {"start": "2026-10-29", "end": "2026-10-30"}
    )
    tools["get_person_location"].parameters({})
    with pytest.raises(Exception):
        tools["get_calendar_events"].parameters({"start": "2026-10-29"})
    with pytest.raises(Exception):
        tools["create_calendar_event"].parameters({"summary": "x"})

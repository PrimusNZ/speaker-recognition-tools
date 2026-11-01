"""Tests for the per-person to-do list tools."""

from __future__ import annotations

import pytest
from homeassistant.components.todo.const import TodoListEntityFeature
from homeassistant.core import ServiceCall, SupportsResponse
from homeassistant.helpers import llm

from custom_components.speaker_recognition_tools import todo_tools, tool_base
from custom_components.speaker_recognition_tools.prompt import Person
from tests.tools.helpers import instance

ALL_FEATURES = (
    TodoListEntityFeature.CREATE_TODO_ITEM
    | TodoListEntityFeature.UPDATE_TODO_ITEM
    | TodoListEntityFeature.DELETE_TODO_ITEM
)


class FakeTodo:
    """Fake todo services that record each call."""

    def __init__(self, hass) -> None:
        self.items = {
            "todo.james": [
                {"uid": "1", "summary": "Renew licence", "status": "needs_action"},
                {"uid": "2", "summary": "Call plumber", "status": "completed"},
            ],
            "todo.sarah": [
                {"uid": "3", "summary": "Book flights", "status": "needs_action"}
            ],
            "todo.sarah_private": [
                {"uid": "4", "summary": "Surprise party", "status": "needs_action"}
            ],
        }
        self.calls: list[tuple[str, dict]] = []
        for entity_id in self.items:
            hass.states.async_set(
                entity_id, "1", {"supported_features": int(ALL_FEATURES)}
            )

        async def get_items(call: ServiceCall):
            ids = call.data["entity_id"]
            ids = [ids] if isinstance(ids, str) else ids
            return {e: {"items": self.items[e]} for e in ids}

        hass.services.async_register(
            "todo", "get_items", get_items, supports_response=SupportsResponse.ONLY
        )
        for service in ("add_item", "update_item", "remove_item"):

            async def record(call: ServiceCall, service=service) -> None:
                self.calls.append((service, dict(call.data)))

            hass.services.async_register("todo", service, record)


@pytest.fixture
def todo(hass) -> FakeTodo:
    return FakeTodo(hass)


def _household(users, speaker_name="James"):
    james = Person(users["James"].id, "James", "Dad", todo_list="todo.james")
    sarah = Person(
        users["Sarah"].id,
        "Sarah",
        "Mum",
        todo_list="todo.sarah_private",
        todo_private=True,
    )
    speaker = james if speaker_name == "James" else sarah
    return tool_base.Household([james, sarah], speaker)


async def _call(hass, users, tool_cls, speaker="James", **args):
    tool = tool_cls(_household(users, speaker))
    api_instance = await instance(hass, users[speaker])
    result = await tool.async_call(
        hass,
        llm.ToolInput(tool_name=tool.name, tool_args=args),
        api_instance.llm_context,
    )
    return result.data, result.error


async def _confirmed(hass, users, tool_cls, speaker="James", **args):
    preview, error = await _call(hass, users, tool_cls, speaker, **args)
    assert not error, preview
    assert preview["confirmation_required"] is True
    return await _call(
        hass,
        users,
        tool_cls,
        speaker,
        **args,
        confirmation_token=preview["confirmation_token"],
        confirmed=True,
    )


async def test_reads_open_items_on_the_speakers_list(hass, users, todo) -> None:
    data, error = await _call(hass, users, todo_tools.GetTodoItemsTool)
    assert not error
    (only,) = data["lists"]
    assert only["list"] == "your to-do list"
    assert [i["summary"] for i in only["items"]] == ["Renew licence"]


async def test_reads_completed_items_when_asked(hass, users, todo) -> None:
    data, _ = await _call(hass, users, todo_tools.GetTodoItemsTool, status="completed")
    assert [i["summary"] for i in data["lists"][0]["items"]] == ["Call plumber"]


async def test_other_persons_private_list_is_refused(hass, users, todo) -> None:
    data, error = await _call(hass, users, todo_tools.GetTodoItemsTool, people=["Mum"])
    assert error
    assert data["lists"] == []
    assert data["problems"] == [
        {
            "person": "Mum",
            "problem": "private",
            "message": "Mum's to-do list is private.",
        }
    ]
    assert "todo.sarah_private" not in str(data)


async def test_lists_are_named_by_whose_they_are(hass, users, todo) -> None:
    data, error = await _call(
        hass, users, todo_tools.GetTodoItemsTool, speaker="Sarah", people=["me", "Dad"]
    )
    assert not error
    assert [entry["list"] for entry in data["lists"]] == [
        "your to-do list",
        "Dad's to-do list",
    ]


async def test_owner_can_change_their_private_list(hass, users, todo) -> None:
    result, error = await _confirmed(
        hass, users, todo_tools.AddTodoItemTool, speaker="Sarah", item="Pay rates"
    )
    assert not error
    assert result["list"] == "your to-do list"
    assert todo.calls == [
        ("add_item", {"entity_id": "todo.sarah_private", "item": "Pay rates"})
    ]


async def test_person_without_a_list_is_told_so(hass, users, todo) -> None:
    james = Person(users["James"].id, "James", "Dad")
    tool = todo_tools.GetTodoItemsTool(tool_base.Household([james], james))
    api_instance = await instance(hass, users["James"])
    result = await tool.async_call(
        hass,
        llm.ToolInput(tool_name=tool.name, tool_args={}),
        api_instance.llm_context,
    )
    assert result.error
    assert result.data["problems"][0]["problem"] == "no_todo_list"
    assert result.data["problems"][0]["message"] == "Dad has no to-do list."


async def test_add_needs_confirmation_then_adds(hass, users, todo) -> None:
    preview, error = await _call(
        hass, users, todo_tools.AddTodoItemTool, item="Wash car", due="2026-11-03"
    )
    assert not error
    assert preview["preview"] == {
        "person": "Dad",
        "list": "your to-do list",
        "item": "Wash car",
        "due_date": "2026-11-03",
    }
    assert todo.calls == []

    result, error = await _confirmed(
        hass, users, todo_tools.AddTodoItemTool, item="Wash car", due="2026-11-03"
    )
    assert not error
    assert result["added"] is True
    assert todo.calls == [
        (
            "add_item",
            {"entity_id": "todo.james", "item": "Wash car", "due_date": "2026-11-03"},
        )
    ]


async def test_cannot_add_to_someone_elses_private_list(hass, users, todo) -> None:
    data, error = await _call(
        hass,
        users,
        todo_tools.AddTodoItemTool,
        item="Peek",
        person="Mum",
    )
    assert error
    assert todo.calls == []
    assert [p["problem"] for p in data["problems"]] == ["private"]


async def test_complete_an_item_by_its_text(hass, users, todo) -> None:
    result, error = await _confirmed(
        hass,
        users,
        todo_tools.UpdateTodoItemTool,
        item="renew licence",
        status="completed",
    )
    assert not error
    assert result["item"] == "Renew licence"
    assert todo.calls == [
        ("update_item", {"entity_id": "todo.james", "item": "1", "status": "completed"})
    ]


async def test_update_needs_a_change(hass, users, todo) -> None:
    data, error = await _call(
        hass, users, todo_tools.UpdateTodoItemTool, item="Renew licence"
    )
    assert error
    assert "Say what to change" in data["error"]


async def test_unknown_item_is_reported(hass, users, todo) -> None:
    data, error = await _call(
        hass, users, todo_tools.RemoveTodoItemTool, item="Nothing like this"
    )
    assert error
    assert data["problem"] == "item_not_found"


async def test_remove_needs_confirmation_then_removes(hass, users, todo) -> None:
    result, error = await _confirmed(
        hass, users, todo_tools.RemoveTodoItemTool, item="Call plumber"
    )
    assert not error
    assert result["removed"] is True
    assert todo.calls == [("remove_item", {"entity_id": "todo.james", "item": ["2"]})]


async def test_list_without_the_feature_is_refused(hass, users, todo) -> None:
    hass.states.async_set("todo.james", "1", {"supported_features": 0})
    data, error = await _call(hass, users, todo_tools.AddTodoItemTool, item="Wash car")
    assert error
    assert data["error"] == "Your to-do list does not accept new items."

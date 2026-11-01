"""Tests for sending a message to a person's phone."""

from __future__ import annotations

from homeassistant.core import ServiceCall
from homeassistant.helpers import llm

from custom_components.speaker_recognition_tools import message_tools, tool_base
from custom_components.speaker_recognition_tools.prompt import Person
from tests.tools.helpers import instance


def _record(hass, service: str) -> list[dict]:
    calls: list[dict] = []

    async def handler(call: ServiceCall) -> None:
        calls.append(dict(call.data))

    hass.services.async_register("notify", service, handler)
    return calls


def _household(users, *, sarah_entities=(), sarah_private=(), sarah_action=None):
    james = Person(users["James"].id, "James", "Dad")
    sarah = Person(
        users["Sarah"].id,
        "Sarah",
        "Mum",
        tuple(sarah_entities),
        frozenset(sarah_private),
        notify_service=sarah_action,
    )
    return tool_base.Household([james, sarah], james)


async def _call(hass, users, household, **args):
    tool = message_tools.SendMessageToPersonTool(household)
    api_instance = await instance(hass, users["James"])
    result = await tool.async_call(
        hass,
        llm.ToolInput(tool_name=tool.name, tool_args=args),
        api_instance.llm_context,
    )
    return result.data, result.error


async def test_message_is_previewed_then_sent(hass, users) -> None:
    calls = _record(hass, "mobile_app_sarah_phone")
    household = _household(users, sarah_action="notify.mobile_app_sarah_phone")
    args = {"people": ["Mum"], "message": "Dinner is ready"}

    preview, error = await _call(hass, users, household, **args)
    assert not error
    assert preview["preview"] == {
        "to": ["Mum"],
        "title": "Message from Dad",
        "message": "Dinner is ready",
    }
    assert calls == []

    result, error = await _call(
        hass,
        users,
        household,
        **args,
        confirmation_token=preview["confirmation_token"],
        confirmed=True,
    )
    assert not error
    assert result["sent_to"] == ["Mum"]
    assert calls == [{"message": "Dinner is ready", "title": "Message from Dad"}]


async def test_notify_entities_use_send_message(hass, users) -> None:
    calls = _record(hass, "send_message")
    household = _household(users, sarah_entities=[("notify.sarah_phone", "Phone")])
    args = {"people": ["Sarah"], "message": "Running late", "title": "Note"}
    preview, _ = await _call(hass, users, household, **args)
    await _call(
        hass,
        users,
        household,
        **args,
        confirmation_token=preview["confirmation_token"],
        confirmed=True,
    )
    assert calls == [
        {
            "entity_id": ["notify.sarah_phone"],
            "message": "Running late",
            "title": "Note",
        }
    ]


async def test_private_notify_entity_is_not_used_by_others(hass, users) -> None:
    _record(hass, "send_message")
    household = _household(
        users,
        sarah_entities=[("notify.sarah_phone", "Phone")],
        sarah_private=["notify.sarah_phone"],
    )
    data, error = await _call(hass, users, household, people=["Mum"], message="Hi")
    assert error
    assert data["problems"][0]["problem"] == "no_message_target"


async def test_missing_notify_action_counts_as_no_phone(hass, users) -> None:
    household = _household(users, sarah_action="notify.mobile_app_gone")
    data, error = await _call(hass, users, household, people=["Mum"], message="Hi")
    assert error
    assert data["problems"][0]["problem"] == "no_message_target"


async def test_all_or_nothing_when_one_person_cannot_be_reached(hass, users) -> None:
    calls = _record(hass, "mobile_app_sarah_phone")
    household = _household(users, sarah_action="notify.mobile_app_sarah_phone")
    data, error = await _call(
        hass, users, household, people=["Mum", "Dad"], message="Family meeting"
    )
    assert error
    assert [p["person"] for p in data["problems"]] == ["Dad"]
    assert calls == []


async def test_empty_message_is_refused(hass, users) -> None:
    household = _household(users, sarah_action="notify.mobile_app_sarah_phone")
    data, error = await _call(hass, users, household, people=["Mum"], message=" ")
    assert error
    assert "Say what the message should say" in data["error"]

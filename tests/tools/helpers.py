"""Shared data and helpers for the tool tests."""

from __future__ import annotations

import datetime

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import (
    llm,
)
from homeassistant.util import dt as dt_util

from custom_components.speaker_recognition_tools.const import (
    PERSON_API_ID,
)

PEOPLE = {
    # name: (address_as, entities, private)
    "James": (
        "Dad",
        ["calendar.james", "person.james", "device_tracker.james_phone"],
        [],
    ),
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
    "Kim": (
        "Cousin",
        ["device_tracker.kim_phone", "sensor.kim_phone_geocoded_location"],
        ["sensor.kim_phone_geocoded_location"],
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


async def confirmed_call(hass, user, tool: str, **args):
    """Preview a calendar change, then confirm that exact staged request."""
    preview, error = await call(hass, user, tool, **args)
    assert not error and preview["confirmation_required"]
    confirmed, error = await call(
        hass,
        user,
        tool,
        **args,
        confirmation_token=preview["confirmation_token"],
        confirmed=True,
    )
    return confirmed, error


def _entities(data: dict, key: str = "calendars") -> list[str]:
    return [c["entity_id"] for c in data.get(key, [])]


def _problems(data: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in data.get("problems", []):
        out.setdefault(p["problem"], []).append(p)
    return out


RANGE = {"start": "2026-10-29T09:00:00", "end": "2026-10-29T17:00:00"}


def local(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime.datetime:
    return datetime.datetime(
        2026, month, day, hour, minute, tzinfo=dt_util.DEFAULT_TIME_ZONE
    )


def now() -> datetime.datetime:
    return local(26, 17, 0)  # a Monday

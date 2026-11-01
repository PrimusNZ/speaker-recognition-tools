"""Calendar tools: read, search, check availability, create, update and delete."""

from __future__ import annotations

import datetime
from typing import Any

import probatio as vol
from homeassistant.components.calendar.const import (
    DATA_COMPONENT as CALENDAR_DATA,
)
from homeassistant.components.calendar.const import (
    CalendarEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    llm,
)
from homeassistant.util import dt as dt_util

from .tool_base import (
    _PERSON_PARAMETER_GUIDANCE,
    _READ_ONLY,
    _WRITE,
    Household,
    _as_datetime,
    _parse_when,
    _people_parameter_guidance,
    _PersonTool,
    _result,
)


def _event_dict(event: Any) -> dict[str, Any]:
    """Return the useful, stable fields from a CalendarEvent."""
    result = {
        "summary": event.summary,
        "start": event.start.isoformat(),
        "end": event.end.isoformat(),
    }
    for key in ("uid", "recurrence_id", "description", "location", "rrule", "status"):
        if value := getattr(event, key, None):
            result[key] = value.value if hasattr(value, "value") else value
    return result


def _calendar_entity(hass: HomeAssistant, entity_id: str):
    """Return a calendar entity for supported update/delete operations."""
    component = hass.data.get(CALENDAR_DATA)
    return component.get_entity(entity_id) if component else None


async def _calendar_events(
    hass: HomeAssistant,
    entity_id: str,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[Any]:
    """Read CalendarEvent objects, including UIDs omitted by the calendar service."""
    entity = _calendar_entity(hass, entity_id)
    if entity is None:
        raise HomeAssistantError(f"Calendar {entity_id} is unavailable")
    return await entity.async_get_events(
        hass, dt_util.as_local(start), dt_util.as_local(end)
    )


class GetCalendarEventsTool(_PersonTool):
    """Read the events on the calendars of one or more people."""

    name = "get_calendar_events"
    title = "Get calendar events"
    description = (
        "Get the events on one or more people's calendars between a start and an "
        f"end. {_people_parameter_guidance('Omit people to use the current speaker.')} "
        "start and end are ISO 8601 local dates or date times; a date-only end "
        "includes that whole day. Private calendars can only be read by their "
        "owner. If a person has more than one calendar the result asks for a "
        "choice; ask the speaker, then call again with the chosen entity_id or "
        "configured entity alias in "
        "calendars."
    )
    annotations = _READ_ONLY
    parameters = vol.Schema(
        {
            vol.Optional("people"): [str],
            vol.Required("start"): str,
            vol.Required("end"): str,
            vol.Optional("calendars"): [str],
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        args = tool_input.tool_args
        try:
            start = _as_datetime(_parse_when(args["start"])[0])
            end = _as_datetime(_parse_when(args["end"], end=True)[0])
        except ValueError as err:
            return _result({"error": str(err)}, error=True)
        if end <= start:
            return _result({"error": "end must be after start"}, error=True)

        people, problems = self._people(args)
        targets, more = self.household.resolve_calendars(people, args.get("calendars"))
        problems += more

        results = []
        for person, entity_id, label in targets:
            try:
                response = await hass.services.async_call(
                    "calendar",
                    "get_events",
                    {
                        "entity_id": entity_id,
                        "start_date_time": start.isoformat(),
                        "end_date_time": end.isoformat(),
                    },
                    context=llm_context.context,
                    blocking=True,
                    return_response=True,
                )
                events = response[entity_id]["events"]
            except (HomeAssistantError, KeyError, ValueError) as err:
                problems.append(
                    {
                        "person": self.household.reference(person),
                        "problem": "read_failed",
                        "entity_id": entity_id,
                        "message": str(err),
                    }
                )
                continue
            results.append(
                {
                    "person": self.household.reference(person),
                    "calendar": label,
                    "entity_id": entity_id,
                    "events": events,
                }
            )
        data: dict[str, Any] = {"calendars": results}
        if problems:
            data["problems"] = problems
        return _result(data, error=not results and bool(problems))


class SearchCalendarEventsTool(_PersonTool):
    """Search assigned calendars by event title and return actionable event IDs."""

    name = "search_calendar_events"
    title = "Search calendar events"
    description = (
        "Find events whose title contains query on one or more people's assigned "
        "calendars in a date range. "
        f"{_people_parameter_guidance('Omit people to use the current speaker.')} "
        "If a calendar choice is needed, calendars accepts an exact entity_id or "
        "an alias shown for that calendar in ENTITY MAPPINGS. Results include uid "
        "and recurrence_id for event updates or deletion. A private calendar can "
        "only be read by its owner."
    )
    annotations = _READ_ONLY
    parameters = vol.Schema(
        {
            vol.Required("query"): str,
            vol.Required("start"): str,
            vol.Required("end"): str,
            vol.Optional("people"): [str],
            vol.Optional("calendars"): [str],
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        args = tool_input.tool_args
        try:
            start = _as_datetime(_parse_when(args["start"])[0])
            end = _as_datetime(_parse_when(args["end"], end=True)[0])
        except ValueError as err:
            return _result({"error": str(err)}, error=True)
        if end <= start:
            return _result({"error": "end must be after start"}, error=True)
        query = args["query"].strip().casefold()
        if not query:
            return _result({"error": "query must not be empty"}, error=True)

        people, problems = self._people(args)
        targets, more = self.household.resolve_calendars(people, args.get("calendars"))
        problems += more
        matches = []
        for person, entity_id, label in targets:
            try:
                events = await _calendar_events(hass, entity_id, start, end)
            except (HomeAssistantError, ValueError) as err:
                problems.append(
                    {
                        "person": self.household.reference(person),
                        "problem": "read_failed",
                        "entity_id": entity_id,
                        "message": str(err),
                    }
                )
                continue
            for event in events:
                if query in event.summary.casefold():
                    matches.append(
                        {
                            "person": self.household.reference(person),
                            "calendar": label,
                            "entity_id": entity_id,
                            "event": _event_dict(event),
                        }
                    )
        result: dict[str, Any] = {"query": args["query"], "matches": matches}
        if problems:
            result["problems"] = problems
        return _result(result, error=not matches and bool(problems))


class CheckCalendarAvailabilityTool(_PersonTool):
    """Check whether a time window overlaps events on assigned calendars."""

    name = "check_calendar_availability"
    title = "Check calendar availability"
    description = (
        "Check whether a time window is free on one or more people's calendars. "
        f"{_people_parameter_guidance('Omit people to use the current speaker.')} "
        "start and end are ISO 8601 local dates or date times; a date-only end "
        "includes the whole day. If a calendar choice is needed, calendars accepts "
        "an exact entity_id or an alias shown for that calendar in ENTITY MAPPINGS. "
        "Private calendars can only be checked by their owner."
    )
    annotations = _READ_ONLY
    parameters = vol.Schema(
        {
            vol.Required("start"): str,
            vol.Required("end"): str,
            vol.Optional("people"): [str],
            vol.Optional("calendars"): [str],
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        args = tool_input.tool_args
        try:
            start = _as_datetime(_parse_when(args["start"])[0])
            end = _as_datetime(_parse_when(args["end"], end=True)[0])
        except ValueError as err:
            return _result({"error": str(err)}, error=True)
        if end <= start:
            return _result({"error": "end must be after start"}, error=True)
        people, problems = self._people(args)
        targets, more = self.household.resolve_calendars(people, args.get("calendars"))
        problems += more
        calendars = []
        for person, entity_id, label in targets:
            try:
                events = await _calendar_events(hass, entity_id, start, end)
            except (HomeAssistantError, ValueError) as err:
                problems.append(
                    {
                        "person": self.household.reference(person),
                        "problem": "read_failed",
                        "entity_id": entity_id,
                        "message": str(err),
                    }
                )
                continue
            conflicts = [
                _event_dict(event)
                for event in events
                if _as_datetime(event.start) < end and _as_datetime(event.end) > start
            ]
            calendars.append(
                {
                    "person": self.household.reference(person),
                    "calendar": label,
                    "entity_id": entity_id,
                    "available": not conflicts,
                    "conflicts": conflicts,
                }
            )
        result: dict[str, Any] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "calendars": calendars,
        }
        if problems:
            result["problems"] = problems
        return _result(result, error=not calendars and bool(problems))


def _one_calendar_target(household: Household, args: dict[str, Any]):
    """Resolve exactly one assigned calendar for a write to one event."""
    if args.get("person"):
        people, problems = household.find([args["person"]])
    else:
        people, problems = [household.speaker], []
    targets, more = household.resolve_calendars(
        people, [args["calendar"]] if args.get("calendar") else None
    )
    problems.extend(more)
    if len(targets) != 1 and not problems:
        problems.append(
            {
                "problem": "one_calendar_required",
                "message": "Choose exactly one person's calendar for this event change.",
            }
        )
    return (targets[0] if len(targets) == 1 else None), problems


def _event_matches(event: Any, uid: str, recurrence_id: str | None) -> bool:
    return event.uid == uid and (
        recurrence_id is None or str(event.recurrence_id) == recurrence_id
    )


class DeleteCalendarEventTool(_PersonTool):
    """Delete an event only after a staged preview and explicit confirmation."""

    name = "delete_calendar_event"
    title = "Delete calendar event"
    description = (
        "Delete an event using a uid returned by search_calendar_events. "
        "Always call once to preview, ask the speaker for an explicit yes, then "
        "call again with the same request, confirmation_token and confirmed=true. "
        "Never delete on the first call. Omit recurrence_id to delete the series; "
        "provide it to delete one occurrence. "
        f"{_PERSON_PARAMETER_GUIDANCE} Only one assigned calendar is allowed."
    )
    annotations = _WRITE
    parameters = vol.Schema(
        {
            vol.Required("uid"): str,
            vol.Required("start"): str,
            vol.Required("end"): str,
            vol.Optional("person"): str,
            vol.Optional("calendar"): str,
            vol.Optional("recurrence_id"): str,
            vol.Optional("confirmation_token"): str,
            vol.Optional("confirmed"): bool,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        args = tool_input.tool_args
        try:
            start = _as_datetime(_parse_when(args["start"])[0])
            end = _as_datetime(_parse_when(args["end"], end=True)[0])
        except ValueError as err:
            return _result({"error": str(err)}, error=True)
        target, problems = _one_calendar_target(self.household, args)
        if problems or target is None:
            return _result({"problems": problems}, error=True)
        person, entity_id, label = target
        entity = _calendar_entity(hass, entity_id)
        if (
            entity is None
            or not entity.supported_features & CalendarEntityFeature.DELETE_EVENT
        ):
            return _result(
                {"error": f"{label} does not support deleting events."}, error=True
            )
        try:
            events = await _calendar_events(hass, entity_id, start, end)
        except (HomeAssistantError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        matches = [
            e
            for e in events
            if _event_matches(e, args["uid"], args.get("recurrence_id"))
        ]
        if not matches:
            return _result(
                {
                    "error": "That event was not found in the selected calendar and date range."
                },
                error=True,
            )
        if args.get("recurrence_id") and len(matches) != 1:
            return _result(
                {"error": "That occurrence is ambiguous; search the calendar again."},
                error=True,
            )
        plan = {
            "action": "delete",
            "calendar": entity_id,
            "uid": args["uid"],
            "recurrence_id": args.get("recurrence_id"),
            "event": _event_dict(matches[0]),
        }
        preview = {
            "person": self.household.reference(person),
            "calendar": label,
            "event": _event_dict(matches[0]),
            "delete_series": not args.get("recurrence_id"),
        }
        if confirmation := self._confirm(
            hass, args, llm_context, action=self.name, plan=plan, preview=preview
        ):
            return confirmation
        try:
            await entity.async_delete_event(
                args["uid"], recurrence_id=args.get("recurrence_id")
            )
        except (HomeAssistantError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        return _result(
            {
                "deleted": True,
                "person": self.household.reference(person),
                "calendar": label,
                "event": preview["event"],
            }
        )


class UpdateCalendarEventTool(_PersonTool):
    """Update an event only after a staged preview and explicit confirmation."""

    name = "update_calendar_event"
    title = "Update calendar event"
    description = (
        "Update an event using a uid returned by search_calendar_events. "
        "Always call once to preview, ask the speaker for an explicit yes, then "
        "call again with the same request, confirmation_token and confirmed=true. "
        "Never update on the first call. Only one assigned calendar is allowed. "
        f"{_PERSON_PARAMETER_GUIDANCE} If changing the time, provide both "
        "new_start and new_end."
    )
    annotations = _WRITE
    parameters = vol.Schema(
        {
            vol.Required("uid"): str,
            vol.Required("start"): str,
            vol.Required("end"): str,
            vol.Optional("person"): str,
            vol.Optional("calendar"): str,
            vol.Optional("recurrence_id"): str,
            vol.Optional("summary"): str,
            vol.Optional("description"): str,
            vol.Optional("location"): str,
            vol.Optional("new_start"): str,
            vol.Optional("new_end"): str,
            vol.Optional("confirmation_token"): str,
            vol.Optional("confirmed"): bool,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        args = tool_input.tool_args
        try:
            start = _as_datetime(_parse_when(args["start"])[0])
            end = _as_datetime(_parse_when(args["end"], end=True)[0])
        except ValueError as err:
            return _result({"error": str(err)}, error=True)
        if end <= start:
            return _result({"error": "end must be after start"}, error=True)
        if bool(args.get("new_start")) != bool(args.get("new_end")):
            return _result(
                {
                    "error": "Provide both new_start and new_end to change an event time."
                },
                error=True,
            )
        changes = any(
            key in args
            for key in ("summary", "description", "location", "new_start", "new_end")
        )
        if not changes:
            return _result(
                {"error": "Provide at least one field to update."}, error=True
            )
        target, problems = _one_calendar_target(self.household, args)
        if problems or target is None:
            return _result({"problems": problems}, error=True)
        person, entity_id, label = target
        entity = _calendar_entity(hass, entity_id)
        if (
            entity is None
            or not entity.supported_features & CalendarEntityFeature.UPDATE_EVENT
        ):
            return _result(
                {"error": f"{label} does not support updating events."}, error=True
            )
        try:
            events = await _calendar_events(hass, entity_id, start, end)
        except (HomeAssistantError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        matches = [
            e
            for e in events
            if _event_matches(e, args["uid"], args.get("recurrence_id"))
        ]
        if len(matches) != 1:
            return _result(
                {
                    "error": "The event was not found or is ambiguous in the selected calendar and date range."
                },
                error=True,
            )
        event = matches[0]
        event_data: dict[str, Any] = {
            "summary": args.get("summary", event.summary),
            "dtstart": event.start,
            "dtend": event.end,
        }
        for key in ("description", "location"):
            value = args.get(key, getattr(event, key, None))
            if value is not None:
                event_data[key] = value
        if event.rrule:
            event_data["rrule"] = event.rrule
        if event.status:
            event_data["status"] = event.status
        if args.get("new_start"):
            try:
                new_start, all_day = _parse_when(args["new_start"])
                new_end, new_end_all_day = _parse_when(args["new_end"], end=True)
            except ValueError as err:
                return _result({"error": str(err)}, error=True)
            if all_day != new_end_all_day:
                return _result(
                    {
                        "error": "new_start and new_end must both be dates or both be date times."
                    },
                    error=True,
                )
            if new_end <= new_start:
                return _result(
                    {"error": "new_end must be after new_start."}, error=True
                )
            event_data["dtstart"], event_data["dtend"] = new_start, new_end
        plan = {
            "action": "update",
            "calendar": entity_id,
            "uid": args["uid"],
            "recurrence_id": args.get("recurrence_id"),
            "before": _event_dict(event),
            "event": event_data,
        }
        preview = {
            "person": self.household.reference(person),
            "calendar": label,
            "before": _event_dict(event),
            "after": {
                k: v.isoformat()
                if isinstance(v, (datetime.date, datetime.datetime))
                else v
                for k, v in event_data.items()
            },
        }
        if confirmation := self._confirm(
            hass, args, llm_context, action=self.name, plan=plan, preview=preview
        ):
            return confirmation
        try:
            await entity.async_update_event(
                args["uid"], event_data, recurrence_id=args.get("recurrence_id")
            )
        except (HomeAssistantError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        return _result({"updated": True, **preview})


class CreateCalendarEventTool(_PersonTool):
    """Create one event on the calendars of one or more people."""

    name = "create_calendar_event"
    title = "Create calendar event"
    description = (
        "Create an event on one or more people's calendars. Always preview the "
        "change and ask the speaker for an explicit yes before the second call "
        "with its confirmation_token and confirmed=true. Never create it on "
        "the first call. "
        f"{_people_parameter_guidance('Omit people to use the current speaker.')} "
        "start is an ISO 8601 local "
        "date time, or a date for an all-day event. end is optional: one hour "
        "after start, or the same day for an all-day event. Nothing is created "
        "unless every named person's calendar can be used: a private calendar "
        "can only be written by its owner, and a person with more than one "
        "calendar needs the speaker to choose; ask, then call again with the "
        "chosen entity_id or configured entity alias in calendars."
    )
    annotations = _WRITE
    parameters = vol.Schema(
        {
            vol.Optional("people"): [str],
            vol.Required("summary"): str,
            vol.Required("start"): str,
            vol.Optional("end"): str,
            vol.Optional("calendars"): [str],
            vol.Optional("description"): str,
            vol.Optional("location"): str,
            vol.Optional("confirmation_token"): str,
            vol.Optional("confirmed"): bool,
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        args = tool_input.tool_args
        try:
            start, all_day = _parse_when(args["start"])
            if args.get("end"):
                end, end_all_day = _parse_when(args["end"], end=True)
                if end_all_day != all_day:
                    raise ValueError(
                        "start and end must both be dates or both be date times"
                    )
            elif all_day:
                end = start + datetime.timedelta(days=1)
            else:
                end = start + datetime.timedelta(hours=1)
        except ValueError as err:
            return _result({"error": str(err)}, error=True)
        if end <= start:
            return _result({"error": "end must be after start"}, error=True)

        people, problems = self._people(args)
        targets, more = self.household.resolve_calendars(people, args.get("calendars"))
        problems += more
        if problems or not targets:
            return _result(
                {
                    "created": [],
                    "problems": problems
                    or [{"problem": "no_calendar", "message": "No calendar to use."}],
                    "note": "Nothing was created. Resolve the problems, then call again.",
                },
                error=True,
            )

        data: dict[str, Any] = {"summary": args["summary"]}
        if all_day:
            data["start_date"] = start.isoformat()
            data["end_date"] = end.isoformat()
        else:
            data["start_date_time"] = start.isoformat()
            data["end_date_time"] = end.isoformat()
        for key in ("description", "location"):
            if args.get(key):
                data[key] = args[key]

        plan = {
            "action": "create",
            "calendars": [entity_id for _, entity_id, _ in targets],
            "event": data,
        }
        preview = {
            "calendars": [
                {
                    "person": self.household.reference(person),
                    "calendar": label,
                    "entity_id": entity_id,
                }
                for person, entity_id, label in targets
            ],
            "event": data,
        }
        if confirmation := self._confirm(
            hass, args, llm_context, action=self.name, plan=plan, preview=preview
        ):
            return confirmation

        created, failed = [], []
        for person, entity_id, label in targets:
            try:
                await hass.services.async_call(
                    "calendar",
                    "create_event",
                    {**data, "entity_id": entity_id},
                    context=llm_context.context,
                    blocking=True,
                )
                created.append(
                    {"person": self.household.reference(person), "calendar": label}
                )
            except (HomeAssistantError, ValueError) as err:
                failed.append(
                    {
                        "person": self.household.reference(person),
                        "calendar": label,
                        "error": str(err),
                    }
                )
        result: dict[str, Any] = {"created": created}
        if failed:
            result["failed"] = failed
        return _result(result, error=bool(failed))

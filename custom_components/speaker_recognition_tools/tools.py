"""LLM tools that work on a person's assigned entities and enforce who may use them.

A person's entities are shared unless they are marked private. A private entity
can only be used by its owner. Every tool checks this itself, so a request about
someone else's private calendar is refused whatever the model asks for.
"""

from __future__ import annotations

import datetime
import json
import re
import secrets
from typing import Any

from homeassistant.components.calendar.const import (
    DATA_COMPONENT as CALENDAR_DATA,
    CalendarEntityFeature,
)
from homeassistant.components.recorder import history as recorder_history
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, llm
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .prompt import Person

try:  # recent Home Assistant
    import probatio as vol
except ImportError:  # older Home Assistant
    import voluptuous as vol

SELF_WORDS = {"me", "my", "myself", "i", "self"}
CALENDAR_DOMAINS = ("calendar",)
LOCATION_DOMAINS = ("person", "device_tracker")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Attributes some device trackers use for a street address.
_ADDRESS_ATTRIBUTES = ("address", "geocoded_location", "formatted_address")
# The Companion App's sensor id, after the webhook id prefix.
_GEOCODED_SENSOR_SUFFIX = "geocoded_location"
_PENDING_CHANGES = "pending_calendar_changes"
_CONFIRMATION_LIFETIME = datetime.timedelta(minutes=5)
_MAX_HISTORY_RANGE = datetime.timedelta(days=31)

_PERSON_REFERENCE_GUIDANCE = (
    "People can be identified by first name, configured form of address, or configured "
    "third-person reference; these forms all refer to the same person."
)


def _people_parameter_guidance(default: str) -> str:
    """Describe aliases accepted by a plural people parameter and its default."""
    return (
        f"people accepts one or more people. {_PERSON_REFERENCE_GUIDANCE} "
        f"Use 'me' for the current speaker. {default}"
    )


_PERSON_PARAMETER_GUIDANCE = (
    "The optional person parameter accepts a person's first name, configured "
    "form of address, or configured third-person reference; these all identify the same "
    "person. Use 'me' for the current speaker; omit person to use the current speaker."
)


def _no_address_note(speaker: Person, target: Person) -> str:
    """The reply the agent must give when someone is away and no address is known."""
    who = "you" if target.user_id == speaker.user_id else target.third_person_form
    return (
        f'Reply with exactly: "Sorry {speaker.direct_address}, An exact address for {who} '
        'is unknown." Add nothing else and do not guess where they are.'
    )


_READ_ONLY = (
    llm.ToolAnnotations(
        read_only=True, destructive=False, idempotent=True, open_world=False
    )
    if hasattr(llm, "ToolAnnotations")
    else None
)
_WRITE = (
    llm.ToolAnnotations(
        read_only=False, destructive=False, idempotent=False, open_world=False
    )
    if hasattr(llm, "ToolAnnotations")
    else None
)


def _result(data: dict[str, Any], error: bool = False):
    """Return a tool result; older Home Assistant returns the bare dict."""
    if hasattr(llm, "ToolResult"):
        return llm.ToolResult(data=data, error=error)
    return {**data, "error": True} if error else data


class Household:
    """The configured people, seen from one speaker."""

    def __init__(self, people: list[Person], speaker: Person) -> None:
        self.people = people
        self.speaker = speaker

    def reference(self, person: Person) -> str:
        """Use the third-person form in tool results, even for the speaker."""
        return person.third_person_form

    def find(
        self, names: list[str] | None
    ) -> tuple[list[Person], list[dict[str, Any]]]:
        """Resolve forms of address, first names and "me" to people. Report failures."""
        found: list[Person] = []
        problems: list[dict[str, Any]] = []
        for raw in names or []:
            key = str(raw).strip().casefold()
            if key in SELF_WORDS:
                matches = [self.speaker]
            else:
                matches = [
                    p
                    for p in self.people
                    if key in (
                        p.direct_address.casefold(),
                        p.third_person_form.casefold(),
                        (p.name or "").casefold(),
                    )
                ]
            if len(matches) == 1:
                if matches[0] not in found:
                    found.append(matches[0])
            else:
                problems.append(
                    {
                        "problem": "ambiguous_person" if matches else "unknown_person",
                        "name": raw,
                        "known_people": [self.reference(p) for p in self.people],
                    }
                )
        return found, problems

    def entities(
        self, person: Person, domains: tuple[str, ...]
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Return (assigned, usable) entities of the given domains for this speaker."""
        assigned = [
            (entity_id, person.entity_label(entity_id, label))
            for entity_id, label in person.entities
            if entity_id.split(".", 1)[0] in domains
        ]
        owner = person.user_id == self.speaker.user_id
        usable = [e for e in assigned if owner or e[0] not in person.private]
        return assigned, usable

    def blocked(self, entity_id: str) -> bool:
        """Whether another person has marked this entity private."""
        return any(
            entity_id in p.private and p.user_id != self.speaker.user_id
            for p in self.people
        )

    def resolve_calendars(
        self, people: list[Person], chosen: list[str] | None
    ) -> tuple[list[tuple[Person, str, str]], list[dict[str, Any]]]:
        """Pick the calendar(s) to use for each person, or say what is in the way."""
        chosen = [str(c).strip() for c in chosen or []]
        targets: list[tuple[Person, str, str]] = []
        problems: list[dict[str, Any]] = []
        seen: set[str] = set()
        for person in people:
            _, usable = self.entities(person, CALENDAR_DOMAINS)
            for entity_id, _ in usable:
                seen.add(entity_id.casefold())
                seen.update(alias.casefold() for alias in person.aliases_for(entity_id))
        all_choices_are_known = all(value.casefold() in seen for value in chosen)

        for person in people:
            assigned, usable = self.entities(person, CALENDAR_DOMAINS)
            if not assigned:
                problems.append(
                    {
                        "person": self.reference(person),
                        "problem": "no_calendar",
                        "message": f"{self.reference(person)} has no calendar assigned.",
                    }
                )
            elif not usable:
                problems.append(
                    {
                        "person": self.reference(person),
                        "problem": "private",
                        "message": f"{self.reference(person)}'s calendar is private.",
                    }
                )
            else:
                picked_ids: set[str] = set()
                ambiguous_alias = False
                for requested in chosen:
                    key = requested.casefold()
                    id_matches = {e[0] for e in usable if e[0].casefold() == key}
                    if id_matches:
                        picked_ids.update(id_matches)
                        continue
                    alias_matches = {
                        entity_id
                        for entity_id, _ in usable
                        if any(
                            alias.casefold() == key
                            for alias in person.aliases_for(entity_id)
                        )
                    }
                    if len(alias_matches) > 1:
                        ambiguous_alias = True
                    else:
                        picked_ids.update(alias_matches)
                picked = [e for e in usable if e[0] in picked_ids]
                if ambiguous_alias:
                    picked = []
                if not picked and len(usable) == 1 and not ambiguous_alias:
                    if all_choices_are_known:
                        picked = usable
                    else:
                        continue
                if picked:
                    targets.extend((person, e[0], e[1]) for e in picked)
                else:
                    problems.append(
                        {
                            "person": self.reference(person),
                            "problem": "choose_calendar",
                            "message": (
                                f"{self.reference(person)} has more than one calendar. Ask "
                                "the speaker which one, then call again with the "
                                "chosen entity_id or configured entity alias in calendars."
                            ),
                            "options": [
                                {
                                    "entity_id": e[0],
                                    "name": e[1],
                                    **(
                                        {"aliases": list(person.aliases_for(e[0])[1:])}
                                        if len(person.aliases_for(e[0])) > 1
                                        else {}
                                    ),
                                }
                                for e in usable
                            ],
                        }
                    )
        for entity_id in chosen:
            if entity_id.casefold() not in seen:
                problems.append(
                    {
                        "problem": "calendar_not_available",
                        "entity_id": entity_id,
                        "message": "That calendar is not available for this request.",
                    }
                )
        return targets, problems


def _parse_when(value: str, *, end: bool = False) -> tuple[Any, bool]:
    """Parse an ISO date or datetime. Returns (value, is_date_only).

    A date-only end covers that whole day, so it becomes the start of the next day.
    Naive datetimes are local time.
    """
    text = str(value).strip()
    if _DATE_ONLY.match(text):
        day = dt_util.parse_date(text)
        if day is None:
            raise ValueError(f"Invalid date: {value}")
        return day + datetime.timedelta(days=1 if end else 0), True
    parsed = dt_util.parse_datetime(text)
    if parsed is None:
        raise ValueError(f"Invalid date or time: {value}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return parsed, False


def _as_datetime(value: Any) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value
    return dt_util.start_of_local_day(value)


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


async def _location_history(
    hass: HomeAssistant,
    entity_ids: list[str],
    start: datetime.datetime,
    end: datetime.datetime,
) -> dict[str, list[Any]]:
    """Read significant recorded states away from the event loop."""
    return await hass.async_add_executor_job(
        recorder_history.get_significant_states,
        hass,
        start,
        end,
        entity_ids,
        None,
        True,
        True,
        False,
        False,
        False,
    )


def _calendar_confirmation(
    hass: HomeAssistant,
    args: dict[str, Any],
    llm_context: llm.LLMContext,
    *,
    action: str,
    plan: dict[str, Any],
    preview: dict[str, Any],
):
    """Stage or confirm a calendar write. No write occurs on the first call."""
    context = llm_context.context
    user_id = context.user_id if context else None
    store = hass.data.setdefault(DOMAIN, {}).setdefault(_PENDING_CHANGES, {})
    now = dt_util.utcnow()
    for token, pending in list(store.items()):
        if pending["expires"] <= now:
            del store[token]

    token = args.get("confirmation_token")
    if not token:
        if args.get("confirmed"):
            return _result(
                {"error": "A confirmation token from a pending preview is required."},
                error=True,
            )
        token = secrets.token_urlsafe(18)
        store[token] = {
            "action": action,
            "user_id": user_id,
            "signature": json.dumps(plan, sort_keys=True, default=str),
            "expires": now + _CONFIRMATION_LIFETIME,
        }
        return _result(
            {
                "confirmation_required": True,
                "confirmation_token": token,
                "preview": preview,
                "note": (
                    "Nothing was changed. Ask the speaker whether to proceed. "
                    "Only after an explicit yes, call this tool again with the "
                    "same request, this confirmation_token and confirmed=true. "
                    "If they decline, call with the same token and confirmed=false."
                ),
            }
        )

    pending = store.get(token)
    if pending is None or pending["expires"] <= now:
        store.pop(token, None)
        return _result(
            {"error": "That confirmation is missing or has expired. Preview the change again."},
            error=True,
        )
    if pending["user_id"] != user_id or pending["action"] != action:
        return _result(
            {"error": "That confirmation does not match this speaker or action."},
            error=True,
        )
    if pending["signature"] != json.dumps(plan, sort_keys=True, default=str):
        return _result(
            {"error": "The request differs from the preview. Preview it again before confirming."},
            error=True,
        )
    if not args.get("confirmed"):
        del store[token]
        return _result({"cancelled": True, "note": "No changes were made."})
    del store[token]
    return None


_UNUSABLE = ("", "unknown", "unavailable")
_STREET_KEYS = ("thoroughfare", "street")
_TOWN_KEYS = ("locality", "city", "town")
_LEADING_NUMBER = re.compile(r"^\d+[A-Za-z]?(?:[/-]\d+[A-Za-z]?)?\s+")
_POSTCODE = re.compile(r"^(?=.*\d)[A-Za-z0-9 -]{3,10}$")


def _usable(text: Any) -> str | None:
    if not isinstance(text, str) or text.strip().casefold() in _UNUSABLE:
        return None
    return text.strip()


def _attribute(attributes: Any, keys: tuple[str, ...]) -> str | None:
    """Read the first usable attribute among keys, ignoring case and spaces."""
    normal = {str(k).casefold().replace(" ", "_"): v for k, v in attributes.items()}
    for key in keys:
        if value := _usable(normal.get(key)):
            return value
    return None


def _street_and_town(text: str | None, attributes: Any) -> str | None:
    """Reduce an address to a street name and a town, which is what gets spoken.

    The street number, postcode and country are dropped. Uses the Companion App's
    Thoroughfare and Locality attributes when present, otherwise reads the text.
    """
    street = _attribute(attributes, _STREET_KEYS)
    town = _attribute(attributes, _TOWN_KEYS)
    if street or town:
        return ", ".join(part for part in (street, town) if part)
    text = _usable(text)
    if not text:
        return None
    parts = [p.strip() for p in re.split(r"[\r\n,]+", text) if p.strip()]
    if not parts:
        return None
    street = _LEADING_NUMBER.sub("", parts[0]) or parts[0]
    rest = [p for p in parts[1:] if not _POSTCODE.match(p)]
    return ", ".join([street, *rest[:1]])


def _address_for(
    hass: HomeAssistant, household: Household, tracker_id: str
) -> str | None:
    """Find the street and town for a device tracker, or None.

    Uses an address attribute on the tracker itself, then the Companion App's
    geocoded location sensor on the same device. A sensor another person has
    marked private is never read.
    """
    if (state := hass.states.get(tracker_id)) is not None:
        for attribute in _ADDRESS_ATTRIBUTES:
            if address := _street_and_town(
                state.attributes.get(attribute), state.attributes
            ):
                return address
    registry = er.async_get(hass)
    entry = registry.async_get(tracker_id)
    if entry is None or entry.device_id is None:
        return None
    for sibling in er.async_entries_for_device(registry, entry.device_id):
        if (
            sibling.domain == "sensor"
            and (sibling.unique_id or "").endswith(_GEOCODED_SENSOR_SUFFIX)
            and not household.blocked(sibling.entity_id)
            and (sensor := hass.states.get(sibling.entity_id)) is not None
            and _usable(sensor.state)
            and (address := _street_and_town(sensor.state, sensor.attributes))
        ):
            return address
    return None


class _PersonTool(llm.Tool):
    """Shared set-up for tools that act on behalf of one recognised speaker."""

    integration = DOMAIN

    def __init__(self, household: Household) -> None:
        self.household = household

    def _people(self, args: dict[str, Any], default_to_everyone: bool = False):
        names = args.get("people")
        if not names:
            return (
                (list(self.household.people), [])
                if default_to_everyone
                else ([self.household.speaker], [])
            )
        return self.household.find(names)


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
    annotations = _READ_ONLY or llm.Tool.annotations
    parameters = vol.Schema(
        {
            vol.Optional("people"): [str],
            vol.Required("start"): str,
            vol.Required("end"): str,
            vol.Optional("calendars"): [str],
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
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
    annotations = _READ_ONLY or llm.Tool.annotations
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
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
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
                    {"person": self.household.reference(person), "problem": "read_failed", "entity_id": entity_id, "message": str(err)}
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
    annotations = _READ_ONLY or llm.Tool.annotations
    parameters = vol.Schema(
        {
            vol.Required("start"): str,
            vol.Required("end"): str,
            vol.Optional("people"): [str],
            vol.Optional("calendars"): [str],
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
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
                    {"person": self.household.reference(person), "problem": "read_failed", "entity_id": entity_id, "message": str(err)}
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
        result: dict[str, Any] = {"start": start.isoformat(), "end": end.isoformat(), "calendars": calendars}
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
    annotations = _WRITE or llm.Tool.annotations
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
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
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
        if entity is None or not entity.supported_features & CalendarEntityFeature.DELETE_EVENT:
            return _result({"error": f"{label} does not support deleting events."}, error=True)
        try:
            events = await _calendar_events(hass, entity_id, start, end)
        except (HomeAssistantError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        matches = [e for e in events if _event_matches(e, args["uid"], args.get("recurrence_id"))]
        if not matches:
            return _result({"error": "That event was not found in the selected calendar and date range."}, error=True)
        if args.get("recurrence_id") and len(matches) != 1:
            return _result({"error": "That occurrence is ambiguous; search the calendar again."}, error=True)
        plan = {
            "action": "delete", "calendar": entity_id, "uid": args["uid"],
            "recurrence_id": args.get("recurrence_id"),
            "event": _event_dict(matches[0]),
        }
        preview = {"person": self.household.reference(person), "calendar": label, "event": _event_dict(matches[0]), "delete_series": not args.get("recurrence_id")}
        if confirmation := _calendar_confirmation(
            hass, args, llm_context, action=self.name, plan=plan, preview=preview
        ):
            return confirmation
        try:
            await entity.async_delete_event(args["uid"], recurrence_id=args.get("recurrence_id"))
        except (HomeAssistantError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        return _result({"deleted": True, "person": self.household.reference(person), "calendar": label, "event": preview["event"]})


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
    annotations = _WRITE or llm.Tool.annotations
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
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
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
            return _result({"error": "Provide both new_start and new_end to change an event time."}, error=True)
        changes = any(key in args for key in ("summary", "description", "location", "new_start", "new_end"))
        if not changes:
            return _result({"error": "Provide at least one field to update."}, error=True)
        target, problems = _one_calendar_target(self.household, args)
        if problems or target is None:
            return _result({"problems": problems}, error=True)
        person, entity_id, label = target
        entity = _calendar_entity(hass, entity_id)
        if entity is None or not entity.supported_features & CalendarEntityFeature.UPDATE_EVENT:
            return _result({"error": f"{label} does not support updating events."}, error=True)
        try:
            events = await _calendar_events(hass, entity_id, start, end)
        except (HomeAssistantError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        matches = [e for e in events if _event_matches(e, args["uid"], args.get("recurrence_id"))]
        if len(matches) != 1:
            return _result({"error": "The event was not found or is ambiguous in the selected calendar and date range."}, error=True)
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
                return _result({"error": "new_start and new_end must both be dates or both be date times."}, error=True)
            if new_end <= new_start:
                return _result({"error": "new_end must be after new_start."}, error=True)
            event_data["dtstart"], event_data["dtend"] = new_start, new_end
        plan = {
            "action": "update", "calendar": entity_id, "uid": args["uid"],
            "recurrence_id": args.get("recurrence_id"),
            "before": _event_dict(event), "event": event_data,
        }
        preview = {"person": self.household.reference(person), "calendar": label, "before": _event_dict(event), "after": {k: v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v for k, v in event_data.items()}}
        if confirmation := _calendar_confirmation(
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
    annotations = _WRITE or llm.Tool.annotations
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
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ):
        args = tool_input.tool_args
        try:
            start, all_day = _parse_when(args["start"])
            if args.get("end"):
                end, end_all_day = _parse_when(args["end"], end=True)
                if end_all_day != all_day:
                    raise ValueError("start and end must both be dates or both be date times")
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
                {"person": self.household.reference(person), "calendar": label, "entity_id": entity_id}
                for person, entity_id, label in targets
            ],
            "event": data,
        }
        if confirmation := _calendar_confirmation(
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
                created.append({"person": self.household.reference(person), "calendar": label})
            except (HomeAssistantError, ValueError) as err:
                failed.append(
                    {"person": self.household.reference(person), "calendar": label, "error": str(err)}
                )
        result: dict[str, Any] = {"created": created}
        if failed:
            result["failed"] = failed
        return _result(result, error=bool(failed))


class GetPersonLocationTool(_PersonTool):
    """Say where people are, from their person and device tracker entities."""

    name = "get_person_location"
    title = "Get person location"
    description = (
        "Say where one or more people are. "
        f"{_people_parameter_guidance('Omit people to get everyone, which answers who is home.')} "
        "Uses the "
        "person and device tracker entities assigned to each person. Each result "
        "has since_spoken, how long they have been there, for example 'home "
        "since three o'clock'; say it that way. When someone "
        "is away, outside every zone, the result includes the street name and "
        "town if their phone or tracker reports an address; not every device "
        "does, and then the result says so. A private tracker can only be read by its owner."
    )
    annotations = _READ_ONLY or llm.Tool.annotations
    parameters = vol.Schema({vol.Optional("people"): [str]})

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ):
        people, problems = self._people(tool_input.tool_args, default_to_everyone=True)
        results = []
        for person in people:
            assigned, usable = self.household.entities(person, LOCATION_DOMAINS)
            if not assigned:
                results.append(
                    {"person": self.household.reference(person), "location": None, "reason": "no location entity assigned"}
                )
                continue
            if not usable:
                results.append(
                    {"person": self.household.reference(person), "location": None, "reason": "private"}
                )
                continue
            entities = []
            for entity_id, label in usable:
                state = hass.states.get(entity_id)
                entities.append(
                    {
                        "entity_id": entity_id,
                        "name": label,
                        "state": _location_name(state.state if state else None),
                    }
                )
            # Prefer the person entity, which combines all of their trackers.
            ordered = sorted(entities, key=lambda e: not e["entity_id"].startswith("person."))
            known = next((e for e in ordered if e["state"] != "unavailable"), None)
            entry: dict[str, Any] = {
                "person": self.household.reference(person),
                "location": known["state"] if known else "unavailable",
                "entities": entities,
            }
            # How long they have been there, ready to say aloud.
            if known and (state := hass.states.get(known["entity_id"])) is not None:
                entry["since"] = dt_util.as_local(state.last_changed).isoformat()
                entry["since_spoken"] = _since_spoken(
                    entry["location"], state.last_changed, dt_util.utcnow()
                )
            # Outside every zone: add a street address when one is reported.
            if entry["location"] == "away":
                address = None
                for tracker_id in self._trackers_to_try(hass, known, usable):
                    if address := _address_for(hass, self.household, tracker_id):
                        break
                if address:
                    entry["address"] = address
                else:
                    # Plenty of phones have geocoding off; say so rather than leave
                    # a gap the model might fill with a guess.
                    entry["address_note"] = _no_address_note(self.household.speaker, person)
            results.append(entry)
        data: dict[str, Any] = {"people": results}
        if problems:
            data["problems"] = problems
        return _result(data, error=not results and bool(problems))


    def _trackers_to_try(
        self,
        hass: HomeAssistant,
        known: dict[str, Any] | None,
        usable: list[tuple[str, str]],
    ) -> list[str]:
        """Trackers that could hold the address, best first."""
        found: list[str] = []
        if known and known["entity_id"].startswith("person."):
            # The person entity says which tracker it is currently using.
            state = hass.states.get(known["entity_id"])
            source = state.attributes.get("source") if state else None
            if source and not self.household.blocked(source):
                found.append(source)
        for entity_id, _ in usable:
            state = hass.states.get(entity_id)
            if entity_id.startswith("device_tracker.") and state and state.state == "not_home":
                found.append(entity_id)
        return list(dict.fromkeys(found))


class GetPersonLocationHistoryTool(_PersonTool):
    """Report recorded location transitions for assigned person/tracker entities."""

    name = "get_person_location_history"
    title = "Get person location history"
    description = (
        "Show recorded location states and transitions for one or more people "
        "between start and end. Use it to answer where someone was or when they "
        "left or arrived. "
        f"{_people_parameter_guidance('Omit people to use the current speaker.')} "
        "start and end are ISO 8601 local dates or date times; a "
        "date-only end includes that whole day. The requested range cannot exceed "
        "31 days. Only assigned, non-private person and tracker entities are queried."
    )
    annotations = _READ_ONLY or llm.Tool.annotations
    parameters = vol.Schema(
        {
            vol.Required("start"): str,
            vol.Required("end"): str,
            vol.Optional("people"): [str],
        }
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: llm.ToolInput, llm_context: llm.LLMContext
    ):
        args = tool_input.tool_args
        try:
            start = _as_datetime(_parse_when(args["start"])[0])
            end = _as_datetime(_parse_when(args["end"], end=True)[0])
        except ValueError as err:
            return _result({"error": str(err)}, error=True)
        if end <= start:
            return _result({"error": "end must be after start"}, error=True)
        if end - start > _MAX_HISTORY_RANGE:
            return _result({"error": "Location history is limited to a 31-day range."}, error=True)

        people, problems = self._people(args)
        requested: dict[str, tuple[Person, str]] = {}
        results = []
        for person in people:
            assigned, usable = self.household.entities(person, LOCATION_DOMAINS)
            if not assigned:
                results.append({"person": self.household.reference(person), "history": [], "reason": "no location entity assigned"})
                continue
            if not usable:
                results.append({"person": self.household.reference(person), "history": [], "reason": "private"})
                continue
            for entity_id, label in usable:
                requested[entity_id] = (person, label)

        if requested:
            try:
                states_by_entity = await _location_history(
                    hass, list(requested), dt_util.as_utc(start), dt_util.as_utc(end)
                )
            except (HomeAssistantError, KeyError, RuntimeError, ValueError) as err:
                return _result({"error": f"Location history is unavailable: {err}"}, error=True)
            now = dt_util.utcnow()
            timelines: dict[str, list[dict[str, Any]]] = {p.user_id: [] for p in people}
            titles = {p.user_id: self.household.reference(p) for p in people}
            for entity_id, (person, label) in requested.items():
                states = states_by_entity.get(entity_id, [])
                prior = None
                for state in states:
                    state_name = _location_name(state.state)
                    changed = state.last_changed
                    item = {
                        "entity_id": entity_id,
                        "name": label,
                        "location": state_name,
                        "at": dt_util.as_local(changed).isoformat(),
                        "at_spoken": _since_phrase(changed, now),
                    }
                    if prior is not None:
                        item["from_location"] = _location_name(prior.state)
                    timelines[person.user_id].append(item)
                    prior = state
            for person in people:
                timeline = sorted(timelines[person.user_id], key=lambda item: item["at"])
                was_truncated = len(timeline) > 100
                results.append(
                    {
                        "person": titles[person.user_id],
                        "history": timeline[-100:],
                        **({"truncated": True} if was_truncated else {}),
                        **({"reason": "no history recorded in that period"} if not timeline else {}),
                    }
                )
        data: dict[str, Any] = {"start": start.isoformat(), "end": end.isoformat(), "people": results}
        if problems:
            data["problems"] = problems
        return _result(data, error=not results and bool(problems))


_HOUR_WORDS = (
    "twelve", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten", "eleven",
)  # fmt: skip


def _spoken_clock(when: datetime.datetime) -> str:
    """Say a time the way a person would, without am or pm."""
    hour, minute = when.hour, when.minute
    if (hour, minute) == (0, 0):
        return "midnight"
    if (hour, minute) == (12, 0):
        return "midday"
    if minute == 0:
        return f"{_HOUR_WORDS[hour % 12]} o'clock"
    if minute == 15:
        return f"quarter past {_HOUR_WORDS[hour % 12]}"
    if minute == 30:
        return f"half past {_HOUR_WORDS[hour % 12]}"
    if minute == 45:
        return f"quarter to {_HOUR_WORDS[(hour + 1) % 12]}"
    return f"{hour % 12 or 12}:{minute:02d}"


def _day_part(hour: int, *, today: bool) -> str:
    """Say roughly when in the day, for today or for yesterday."""
    if hour < 5:
        return "early this morning" if today else "early yesterday morning"
    if hour < 12:
        return "this morning" if today else "yesterday morning"
    if hour < 17:
        return "this afternoon" if today else "yesterday afternoon"
    if hour < 21:
        return "this evening" if today else "yesterday evening"
    return "tonight" if today else "last night"


def _ordinal(day: int) -> str:
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _since_phrase(changed: datetime.datetime, now: datetime.datetime) -> str:
    """Say when something changed, for example "three o'clock" or "yesterday evening"."""
    changed, now = dt_util.as_local(changed), dt_util.as_local(now)
    elapsed = now - changed
    if elapsed < datetime.timedelta(minutes=2):
        return "just now"
    clock = _spoken_clock(changed)
    exact = clock in ("midnight", "midday")
    days = (now.date() - changed.date()).days
    if days == 0:
        if exact or elapsed < datetime.timedelta(hours=6):
            return clock
        return f"{clock} {_day_part(changed.hour, today=True)}"
    if days == 1:
        if exact:
            return f"{clock} yesterday"
        return f"{clock} {_day_part(changed.hour, today=False)}"
    if days < 7:
        return f"{clock} on {changed.strftime('%A')}"
    return f"the {_ordinal(changed.day)} of {changed.strftime('%B')}"


def _since_spoken(location: str, changed: datetime.datetime, now: datetime.datetime) -> str:
    """Say where someone is and since when, for example "home since three o'clock"."""
    phrase = _since_phrase(changed, now)
    if phrase == "just now":
        return f"{location}, as of just now"
    return f"{location} since {phrase}"


def _location_name(state: str | None) -> str:
    """Make a tracker state readable: not_home is away, unknown is unavailable."""
    if state in (None, "unknown", "unavailable"):
        return "unavailable"
    return "away" if state == "not_home" else state


def build_tools(people: list[Person], speaker: Person) -> list[llm.Tool]:
    """Return the tools for one recognised speaker."""
    household = Household(people, speaker)
    return [
        GetCalendarEventsTool(household),
        SearchCalendarEventsTool(household),
        CheckCalendarAvailabilityTool(household),
        CreateCalendarEventTool(household),
        UpdateCalendarEventTool(household),
        DeleteCalendarEventTool(household),
        GetPersonLocationTool(household),
        GetPersonLocationHistoryTool(household),
    ]

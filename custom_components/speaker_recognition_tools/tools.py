"""LLM tools that work on a person's assigned entities and enforce who may use them.

A person's entities are shared unless they are marked private. A private entity
can only be used by its owner. Every tool checks this itself, so a request about
someone else's private calendar is refused whatever the model asks for.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

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


def _no_address_note(speaker: Person, target: Person) -> str:
    """The reply the agent must give when someone is away and no address is known."""
    who = "you" if target.user_id == speaker.user_id else target.title
    return (
        f'Reply with exactly: "Sorry {speaker.title}, An exact address for {who} '
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

    def find(
        self, names: list[str] | None
    ) -> tuple[list[Person], list[dict[str, Any]]]:
        """Resolve titles, first names and "me" to people. Report what failed."""
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
                    if key in (p.title.casefold(), (p.name or "").casefold())
                ]
            if len(matches) == 1:
                if matches[0] not in found:
                    found.append(matches[0])
            else:
                problems.append(
                    {
                        "problem": "ambiguous_person" if matches else "unknown_person",
                        "name": raw,
                        "known_people": [p.title for p in self.people],
                    }
                )
        return found, problems

    def entities(
        self, person: Person, domains: tuple[str, ...]
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Return (assigned, usable) entities of the given domains for this speaker."""
        assigned = [e for e in person.entities if e[0].split(".", 1)[0] in domains]
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
        chosen = [str(c) for c in chosen or []]
        targets: list[tuple[Person, str, str]] = []
        problems: list[dict[str, Any]] = []
        seen: set[str] = set()
        for person in people:
            assigned, usable = self.entities(person, CALENDAR_DOMAINS)
            seen.update(e[0] for e in usable)
            if not assigned:
                problems.append(
                    {
                        "person": person.title,
                        "problem": "no_calendar",
                        "message": f"{person.title} has no calendar assigned.",
                    }
                )
            elif not usable:
                problems.append(
                    {
                        "person": person.title,
                        "problem": "private",
                        "message": f"{person.title}'s calendar is private.",
                    }
                )
            else:
                picked = [e for e in usable if e[0] in chosen]
                if not picked and len(usable) == 1:
                    picked = usable
                if picked:
                    targets.extend((person, e[0], e[1]) for e in picked)
                else:
                    problems.append(
                        {
                            "person": person.title,
                            "problem": "choose_calendar",
                            "message": (
                                f"{person.title} has more than one calendar. Ask "
                                "the speaker which one, then call again with the "
                                "chosen entity_id in calendars."
                            ),
                            "options": [
                                {"entity_id": e[0], "name": e[1]} for e in usable
                            ],
                        }
                    )
        for entity_id in chosen:
            if entity_id not in seen:
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
        "end. people lists titles, names or 'me'; leave it out for the speaker. "
        "start and end are ISO 8601 local dates or date times; a date-only end "
        "includes that whole day. Private calendars can only be read by their "
        "owner. If a person has more than one calendar the result asks for a "
        "choice; ask the speaker, then call again with the chosen entity_id in "
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
                        "person": person.title,
                        "problem": "read_failed",
                        "entity_id": entity_id,
                        "message": str(err),
                    }
                )
                continue
            results.append(
                {
                    "person": person.title,
                    "calendar": label,
                    "entity_id": entity_id,
                    "events": events,
                }
            )
        data: dict[str, Any] = {"calendars": results}
        if problems:
            data["problems"] = problems
        return _result(data, error=not results and bool(problems))


class CreateCalendarEventTool(_PersonTool):
    """Create one event on the calendars of one or more people."""

    name = "create_calendar_event"
    title = "Create calendar event"
    description = (
        "Create an event on one or more people's calendars. people lists titles, "
        "names or 'me'; leave it out for the speaker. start is an ISO 8601 local "
        "date time, or a date for an all-day event. end is optional: one hour "
        "after start, or the same day for an all-day event. Nothing is created "
        "unless every named person's calendar can be used: a private calendar "
        "can only be written by its owner, and a person with more than one "
        "calendar needs the speaker to choose; ask, then call again with the "
        "chosen entity_id in calendars."
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
                created.append({"person": person.title, "calendar": label})
            except (HomeAssistantError, ValueError) as err:
                failed.append(
                    {"person": person.title, "calendar": label, "error": str(err)}
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
        "Say where one or more people are. people lists titles, names or 'me'; "
        "leave it out to get everyone, which answers who is home. Uses the "
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
                    {"person": person.title, "location": None, "reason": "no location entity assigned"}
                )
                continue
            if not usable:
                results.append(
                    {"person": person.title, "location": None, "reason": "private"}
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
                "person": person.title,
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
        CreateCalendarEventTool(household),
        GetPersonLocationTool(household),
    ]

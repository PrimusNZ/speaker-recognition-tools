"""Location tools: where people are now and where they have been."""

from __future__ import annotations

import datetime
import re
from typing import Any

import probatio as vol
from homeassistant.components.recorder import history as recorder_history
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    llm,
)
from homeassistant.util import dt as dt_util

from .prompt import Person
from .tool_base import (
    _READ_ONLY,
    LOCATION_DOMAINS,
    Household,
    _as_datetime,
    _parse_when,
    _people_parameter_guidance,
    _PersonTool,
    _result,
)

# Attributes some device trackers use for a street address.
_ADDRESS_ATTRIBUTES = ("address", "geocoded_location", "formatted_address")
# The Companion App's sensor id, after the webhook id prefix.
_GEOCODED_SENSOR_SUFFIX = "geocoded_location"
_MAX_HISTORY_RANGE = datetime.timedelta(days=31)


def _no_address_note(speaker: Person, target: Person) -> str:
    """The reply the agent must give when no exact address is known."""
    who = "you" if target.user_id == speaker.user_id else target.third_person_form
    return (
        f'Reply with exactly: "Sorry {speaker.direct_address}, An exact address for {who} '
        'is unknown." Add nothing else and do not guess where they are.'
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
        "is outside every zone and has an address, location is their street "
        "name and town; use that as where they are. If location is 'outside "
        "known zones', follow address_note exactly and do not guess. A private "
        "tracker can only be read by its owner. If a person's location is "
        "private, follow the result's note and reveal nothing about where they are."
    )
    annotations = _READ_ONLY
    parameters = vol.Schema({vol.Optional("people"): [str]})

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        people, problems = self._people(tool_input.tool_args, default_to_everyone=True)
        results = []
        for person in people:
            if self.household.location_hidden(person):
                denial = self.household.location_denial(person)
                results.append(
                    {
                        "person": denial["person"],
                        "location": None,
                        "reason": "private",
                        "note": denial["note"],
                    }
                )
                continue
            assigned, usable = self.household.entities(person, LOCATION_DOMAINS)
            if not assigned:
                results.append(
                    {
                        "person": self.household.reference(person),
                        "location": None,
                        "reason": "no location entity assigned",
                    }
                )
                continue
            if not usable:
                results.append(
                    {
                        "person": self.household.reference(person),
                        "location": None,
                        "reason": "private",
                    }
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
            ordered = sorted(
                entities, key=lambda e: not e["entity_id"].startswith("person.")
            )
            known = next((e for e in ordered if e["state"] != "unavailable"), None)
            entry: dict[str, Any] = {
                "person": self.household.reference(person),
                "location": known["state"] if known else "unavailable",
                "entities": entities,
            }
            # Outside every zone: prefer the street and town when available.
            if entry["location"] == "outside known zones":
                address = None
                for tracker_id in self._trackers_to_try(hass, known, usable):
                    if address := _address_for(hass, self.household, tracker_id):
                        break
                if address:
                    entry["address"] = address
                    entry["location"] = address
                else:
                    # Plenty of phones have geocoding off; say so rather than leave
                    # a gap the model might fill with a guess.
                    entry["address_note"] = _no_address_note(
                        self.household.speaker, person
                    )
            # How long they have been at the reported location, ready to say aloud.
            # With no address outside a zone, the exact address note is the reply.
            if (
                known
                and "address_note" not in entry
                and (state := hass.states.get(known["entity_id"])) is not None
            ):
                entry["since"] = dt_util.as_local(state.last_changed).isoformat()
                entry["since_spoken"] = _since_spoken(
                    entry["location"], state.last_changed, dt_util.utcnow()
                )
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
            if (
                entity_id.startswith("device_tracker.")
                and state
                and state.state == "not_home"
            ):
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
        "31 days. Only assigned, non-private person and tracker entities are queried. "
        "If a person's location is private, follow the result's note and reveal "
        "nothing about where they have been."
    )
    annotations = _READ_ONLY
    parameters = vol.Schema(
        {
            vol.Required("start"): str,
            vol.Required("end"): str,
            vol.Optional("people"): [str],
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
        if end - start > _MAX_HISTORY_RANGE:
            return _result(
                {"error": "Location history is limited to a 31-day range."}, error=True
            )

        people, problems = self._people(args)
        requested: dict[str, tuple[Person, str]] = {}
        results = []
        for person in people:
            if self.household.location_hidden(person):
                denial = self.household.location_denial(person)
                results.append(
                    {
                        "person": denial["person"],
                        "history": [],
                        "reason": "private",
                        "note": denial["note"],
                    }
                )
                continue
            assigned, usable = self.household.entities(person, LOCATION_DOMAINS)
            if not assigned:
                results.append(
                    {
                        "person": self.household.reference(person),
                        "history": [],
                        "reason": "no location entity assigned",
                    }
                )
                continue
            if not usable:
                results.append(
                    {
                        "person": self.household.reference(person),
                        "history": [],
                        "reason": "private",
                    }
                )
                continue
            for entity_id, label in usable:
                requested[entity_id] = (person, label)

        if requested:
            try:
                states_by_entity = await _location_history(
                    hass, list(requested), dt_util.as_utc(start), dt_util.as_utc(end)
                )
            except (HomeAssistantError, KeyError, RuntimeError, ValueError) as err:
                return _result(
                    {"error": f"Location history is unavailable: {err}"}, error=True
                )
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
                timeline = sorted(
                    timelines[person.user_id], key=lambda item: item["at"]
                )
                was_truncated = len(timeline) > 100
                results.append(
                    {
                        "person": titles[person.user_id],
                        "history": timeline[-100:],
                        **({"truncated": True} if was_truncated else {}),
                        **(
                            {"reason": "no history recorded in that period"}
                            if not timeline
                            else {}
                        ),
                    }
                )
        data: dict[str, Any] = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "people": results,
        }
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
    suffix = (
        "th"
        if 11 <= day % 100 <= 13
        else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    )
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


def _since_spoken(
    location: str, changed: datetime.datetime, now: datetime.datetime
) -> str:
    """Say where someone is and since when, for example "home since three o'clock"."""
    phrase = _since_phrase(changed, now)
    if phrase == "just now":
        return f"{location}, as of just now"
    return f"{location} since {phrase}"


def _location_name(state: str | None) -> str:
    """Make a tracker state readable: not_home is outside known zones."""
    if state in (None, "unknown", "unavailable"):
        return "unavailable"
    return "outside known zones" if state == "not_home" else state


# The Companion App's BLE transmitter sensor, after the webhook id prefix. Its id
# attribute is the iBeacon that a BLE tracking integration may track as a separate
# device.
_BLE_TRANSMITTER_SUFFIX = "_ble_emitter"


def _beacon_key(value: str) -> str:
    return value.replace("-", "").replace(":", "").casefold()


def _device_room(
    hass: HomeAssistant, household: Household, device_id: str
) -> tuple[str, datetime.datetime | None] | None:
    """Find the room a device is in now, and since when, or None.

    Uses an area sensor on the device, such as Bermuda's Area sensor, whose state is
    the area name, then an area attribute on one of its device trackers. A sensor or
    tracker another person has marked private is never read.
    """
    registry = er.async_get(hass)
    entries = [
        e
        for e in er.async_entries_for_device(registry, device_id)
        if not household.blocked(e.entity_id)
    ]
    for entry in entries:
        if (
            entry.domain != "sensor"
            or (state := hass.states.get(entry.entity_id)) is None
        ):
            continue
        area = _usable(state.attributes.get("area_name"))
        if area and _usable(state.state) == area:
            return area, state.last_changed
    for entry in entries:
        if entry.domain != "device_tracker":
            continue
        state = hass.states.get(entry.entity_id)
        if state is not None and (area := _usable(state.attributes.get("area"))):
            return area, None
    return None


def _beacon_device(
    hass: HomeAssistant, device_id: str, candidates: set[str]
) -> str | None:
    """Find which of the candidate devices tracks this phone's BLE transmitter.

    Any integration counts: a candidate matches when one of its identifiers is the
    transmitter's iBeacon id, ignoring case, dashes and colons.
    """
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    for entry in er.async_entries_for_device(registry, device_id):
        if entry.domain != "sensor" or not (entry.unique_id or "").endswith(
            _BLE_TRANSMITTER_SUFFIX
        ):
            continue
        state = hass.states.get(entry.entity_id)
        beacon = _usable(state.attributes.get("id")) if state else None
        if not beacon:
            continue
        key = _beacon_key(beacon)
        for candidate in candidates - {device_id}:
            device = devices.async_get(candidate)
            if device and any(_beacon_key(i) == key for _, i in device.identifiers):
                return candidate
    return None


def _no_device_address_note(speaker: Person, target: Person, device: str) -> str:
    """The reply the agent must give when no exact address is known for a device."""
    whose = (
        "your" if target.user_id == speaker.user_id else f"{target.third_person_form}'s"
    )
    return (
        f'Reply with exactly: "Sorry {speaker.direct_address}, An exact address for '
        f'{whose} {device} is unknown." Add nothing else and do not guess where it is.'
    )


class GetDeviceLocationTool(_PersonTool):
    """Say where a person's phone or other tracked device is, down to the room."""

    name = "get_device_location"
    title = "Get device location"
    description = (
        "Say where a person's phone or other tracked device is, for example "
        "'where is my phone?'. "
        f"{_people_parameter_guidance('Omit people to use the current speaker.')} "
        "Optional device narrows the result to one device by its name, alias, "
        "model or entity_id; omit it to get all of their devices. Uses their "
        "assigned device trackers and the trackers of their assigned person "
        "entity. When a device is at home and a room is known, room is the Home "
        "Assistant area it is in; say that room. Otherwise location is its zone, "
        "or its street name and town when it is outside every zone. Each result "
        "has since_spoken, ready to say aloud. Follow any room_note or "
        "address_note exactly and never guess a room or a place. A private "
        "device can only be located by its owner. If a person's location is "
        "private, a device at home still gives its room or 'home', but a device "
        "away from home returns a privacy note: follow it and reveal nothing "
        "else about where it is."
    )
    annotations = _READ_ONLY
    parameters = vol.Schema(
        {vol.Optional("people"): [str], vol.Optional("device"): str}
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        args = tool_input.tool_args
        people, problems = self._people(args)
        wanted = str(args.get("device") or "").strip().casefold()
        results = []
        for person in people:
            assigned, usable = self.household.entities(person, LOCATION_DOMAINS)
            if not assigned:
                results.append(
                    {
                        "person": self.household.reference(person),
                        "devices": [],
                        "reason": "no device tracker or person entity assigned",
                    }
                )
                continue
            if not usable:
                results.append(
                    {
                        "person": self.household.reference(person),
                        "devices": [],
                        "reason": "private",
                    }
                )
                continue
            devices = self._devices(
                hass, person, usable, self.household.location_hidden(person)
            )
            if wanted:
                matching = [d for d in devices if wanted in d.pop("_names")]
                if not matching:
                    problems.append(
                        {
                            "person": self.household.reference(person),
                            "problem": "device_not_found",
                            "message": (
                                f"No device matching {args['device']!r} is tracked for "
                                f"{self.household.reference(person)}."
                            ),
                            "options": [d["device"] for d in devices],
                        }
                    )
                    continue
                devices = matching
            else:
                for device in devices:
                    device.pop("_names")
            results.append(
                {
                    "person": self.household.reference(person),
                    "devices": devices,
                    **({} if devices else {"reason": "no device tracker found"}),
                }
            )
        data: dict[str, Any] = {"people": results}
        if problems:
            data["problems"] = problems
        return _result(data, error=not results and bool(problems))

    def _trackers(
        self, hass: HomeAssistant, person: Person, usable: list[tuple[str, str]]
    ) -> list[tuple[str, str | None]]:
        """The person's trackers, with their configured label when assigned.

        A person entity contributes the trackers Home Assistant combines for it.
        """
        owner = person.user_id == self.household.speaker.user_id
        found: dict[str, str | None] = {}
        for entity_id, label in usable:
            if entity_id.startswith("device_tracker."):
                found.setdefault(entity_id, label)
        for entity_id, _ in usable:
            if not entity_id.startswith("person."):
                continue
            state = hass.states.get(entity_id)
            for tracker in (
                (state.attributes.get("device_trackers") or []) if state else []
            ):
                if (
                    isinstance(tracker, str)
                    and not self.household.blocked(tracker)
                    and (owner or tracker not in person.private)
                ):
                    found.setdefault(tracker, None)
        return list(found.items())

    def _devices(
        self,
        hass: HomeAssistant,
        person: Person,
        usable: list[tuple[str, str]],
        hidden: bool = False,
    ) -> list[dict[str, Any]]:
        registry = er.async_get(hass)
        devices = dr.async_get(hass)
        trackers = self._trackers(hass, person, usable)
        # A tracked BLE beacon for a phone is the same device as the phone, so it
        # is folded into the phone's result rather than listed on its own.
        tracked = {
            entry.device_id
            for tracker_id, _ in trackers
            if (entry := registry.async_get(tracker_id)) and entry.device_id
        }
        beacons: dict[str, str] = {}
        for device_id in tracked:
            if beacon := _beacon_device(hass, device_id, tracked):
                beacons[device_id] = beacon
        folded = set(beacons.values())
        results = []
        for tracker_id, label in trackers:
            entry = registry.async_get(tracker_id)
            device_id = entry.device_id if entry else None
            if device_id in folded and device_id not in beacons:
                continue
            device = devices.async_get(device_id) if device_id else None
            state = hass.states.get(tracker_id)
            model = device.model if device else None
            # Device names are often a full account name, so only a configured
            # label or the model is shown.
            name = (
                label
                or model
                or ("phone" if entry and entry.platform == "mobile_app" else "device")
            )
            result: dict[str, Any] = {
                "device": name,
                "entity_id": tracker_id,
                "_names": {
                    n.casefold()
                    for n in (
                        tracker_id,
                        name,
                        model or "",
                        *person.aliases_for(tracker_id),
                    )
                    if n
                },
            }
            if not entry or entry.platform == "mobile_app":
                result["_names"].add("phone")
            zone = state.state if state else None
            if hidden and zone not in (None, "home", *_UNUSABLE):
                # Away from home: the zone or address would reveal their location.
                denial = self.household.location_denial(person)
                result.pop("entity_id")
                result.update(location=None, reason="private", note=denial["note"])
                results.append(result)
                continue
            room = None
            # A room only makes sense while the device is at home.
            if device_id and zone in (None, "home", *_UNUSABLE):
                for source in (device_id, beacons.get(device_id)):
                    if source and (room := _device_room(hass, self.household, source)):
                        break
            if room:
                area, since = room
                result["room"] = area
                result["location"] = "home"
                result["since_spoken"] = (
                    _since_spoken(f"in the {area}", since, dt_util.utcnow())
                    if since
                    else f"in the {area}"
                )
                results.append(result)
                continue
            location = _location_name(zone)
            result["location"] = location
            if location == "outside known zones":
                if address := _address_for(hass, self.household, tracker_id):
                    result["location"] = address
                else:
                    result["address_note"] = _no_device_address_note(
                        self.household.speaker, person, name
                    )
            elif location == "home":
                result["room_note"] = (
                    f"No room is known for this {name}. Say it is at home and do "
                    "not guess a room."
                )
            if (
                state is not None
                and "address_note" not in result
                and location != "unavailable"
            ):
                result["since_spoken"] = _since_spoken(
                    result["location"], state.last_changed, dt_util.utcnow()
                )
            results.append(result)
        return results

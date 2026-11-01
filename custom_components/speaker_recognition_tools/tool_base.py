"""Shared pieces for the person tools: the household, results and the base tool."""

from __future__ import annotations

import datetime
import json
import re
import secrets
from typing import Any, NamedTuple

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    llm,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .prompt import Person

SELF_WORDS = {"me", "my", "myself", "i", "self"}
CALENDAR_DOMAINS = ("calendar",)
LOCATION_DOMAINS = ("person", "device_tracker")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PENDING_CHANGES = "pending_changes"
_CONFIRMATION_LIFETIME = datetime.timedelta(minutes=5)

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


_READ_ONLY = llm.ToolAnnotations(
    read_only=True, destructive=False, idempotent=True, open_world=False
)
_WRITE = llm.ToolAnnotations(
    read_only=False, destructive=False, idempotent=False, open_world=False
)


def _sentence(text: str) -> str:
    """Capitalise the first letter only, leaving names as they are."""
    return text[:1].upper() + text[1:]


def _result(data: dict[str, Any], error: bool = False) -> llm.ToolResult:
    """Return a tool result."""
    return llm.ToolResult(data=data, error=error)


class TargetKind(NamedTuple):
    """One kind of assigned entity a tool can pick per person."""

    domains: tuple[str, ...]
    noun: str  # used in messages, for example "calendar"
    code: str  # used in problem codes, for example "calendar"
    parameter: str  # the tool parameter that takes the choice


CALENDARS = TargetKind(CALENDAR_DOMAINS, "calendar", "calendar", "calendars")


class Household:
    """The configured people, seen from one speaker."""

    def __init__(
        self, people: list[Person], speaker: Person, *, uncertain: bool = False
    ) -> None:
        self.people = people
        self.speaker = speaker
        # Speaker Recognition scored this turn below the configured confidence.
        self.uncertain = uncertain

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
                    if key
                    in (
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

    def location_hidden(self, person: Person) -> bool:
        """Whether this person's whereabouts are hidden from the current speaker."""
        return person.location_private and person.user_id != self.speaker.user_id

    def location_denial(self, person: Person) -> dict[str, Any]:
        """The result for a request that would reveal a hidden location."""
        who = self.reference(person)
        return {
            "person": who,
            "problem": "private",
            "message": f"{who}'s location is private.",
            "note": (
                f"Say that {who}'s location is private. Do not say where they "
                "are, whether they are home or away, or anything else about it."
            ),
        }

    def todo_name(self, person: Person) -> str:
        """How to name a person's to-do list aloud, for example "your to-do list"."""
        if person.user_id == self.speaker.user_id:
            return "your to-do list"
        return f"{self.reference(person)}'s to-do list"

    def todo_list(self, person: Person) -> tuple[str | None, dict[str, Any] | None]:
        """Return a person's one to-do list, or the problem in the way."""
        who = self.reference(person)
        if not person.todo_list:
            return None, {
                "person": who,
                "problem": "no_todo_list",
                "message": f"{who} has no to-do list.",
            }
        if person.todo_private and person.user_id != self.speaker.user_id:
            return None, {
                "person": who,
                "problem": "private",
                "message": f"{_sentence(self.todo_name(person))} is private.",
            }
        return person.todo_list, None

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
        return self.resolve_targets(people, chosen, CALENDARS)

    def resolve_targets(
        self, people: list[Person], chosen: list[str] | None, kind: TargetKind
    ) -> tuple[list[tuple[Person, str, str]], list[dict[str, Any]]]:
        """Pick the entities of one kind to use for each person, or say what is in the way."""
        chosen = [str(c).strip() for c in chosen or []]
        targets: list[tuple[Person, str, str]] = []
        problems: list[dict[str, Any]] = []
        seen: set[str] = set()
        for person in people:
            _, usable = self.entities(person, kind.domains)
            for entity_id, _ in usable:
                seen.add(entity_id.casefold())
                seen.update(alias.casefold() for alias in person.aliases_for(entity_id))
        all_choices_are_known = all(value.casefold() in seen for value in chosen)

        for person in people:
            assigned, usable = self.entities(person, kind.domains)
            if not assigned:
                problems.append(
                    {
                        "person": self.reference(person),
                        "problem": f"no_{kind.code}",
                        "message": f"{self.reference(person)} has no {kind.noun} assigned.",
                    }
                )
            elif not usable:
                problems.append(
                    {
                        "person": self.reference(person),
                        "problem": "private",
                        "message": f"{self.reference(person)}'s {kind.noun} is private.",
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
                            "problem": f"choose_{kind.code}",
                            "message": (
                                f"{self.reference(person)} has more than one {kind.noun}. "
                                "Ask the speaker which one, then call again with the "
                                "chosen entity_id or configured entity alias in "
                                f"{kind.parameter}."
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
                        "problem": f"{kind.code}_not_available",
                        "entity_id": entity_id,
                        "message": f"That {kind.noun} is not available for this request.",
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


def _confirm_change(
    hass: HomeAssistant,
    args: dict[str, Any],
    llm_context: llm.LLMContext,
    *,
    action: str,
    plan: dict[str, Any],
    preview: dict[str, Any],
    extra_note: str | None = None,
):
    """Stage or confirm a write. No write occurs on the first call.

    Returns a result to send back (a preview, a refusal or a cancellation), or
    None when the speaker confirmed this exact request and the write may go ahead.
    """
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
                    + (f" {extra_note}" if extra_note else "")
                ),
            }
        )

    pending = store.get(token)
    if pending is None or pending["expires"] <= now:
        store.pop(token, None)
        return _result(
            {
                "error": "That confirmation is missing or has expired. Preview the change again."
            },
            error=True,
        )
    if pending["user_id"] != user_id or pending["action"] != action:
        return _result(
            {"error": "That confirmation does not match this speaker or action."},
            error=True,
        )
    if pending["signature"] != json.dumps(plan, sort_keys=True, default=str):
        return _result(
            {
                "error": "The request differs from the preview. Preview it again before confirming."
            },
            error=True,
        )
    if not args.get("confirmed"):
        del store[token]
        return _result({"cancelled": True, "note": "No changes were made."})
    del store[token]
    return None


class _PersonTool(llm.Tool):
    """Shared set-up for tools that act on behalf of one recognised speaker."""

    integration = DOMAIN

    def __init__(self, household: Household) -> None:
        self.household = household

    def _confirm(self, hass, args, llm_context, *, action, plan, preview):
        """Stage or confirm a write, asking for identity too when unsure who is speaking."""
        note = None
        if self.household.uncertain:
            note = (
                "Speaker recognition was not confident that this is "
                f"{self.household.speaker.direct_address}. Before asking whether to "
                "go ahead, ask them to confirm who they are."
            )
        return _confirm_change(
            hass,
            args,
            llm_context,
            action=action,
            plan=plan,
            preview=preview,
            extra_note=note,
        )

    def _people(self, args: dict[str, Any], default_to_everyone: bool = False):
        names = args.get("people")
        if not names:
            return (
                (list(self.household.people), [])
                if default_to_everyone
                else ([self.household.speaker], [])
            )
        return self.household.find(names)

    def _entity_person(self, args: dict[str, Any]):
        """Resolve an optional person, defaulting entity access to the speaker."""
        requested = str(args.get("person", "")).strip()
        if not requested:
            return self.household.speaker, []
        people, problems = self.household.find([requested])
        return (people[0] if len(people) == 1 else None), problems

    def _assigned_entity(self, person: Person, requested: str):
        """Resolve an entity ID, configured name, or alias within one person's list."""
        key = requested.strip().casefold()
        if not key:
            return None, {
                "problem": "entity_required",
                "message": "Name the assigned entity to use.",
            }
        matched = []
        private_match = False
        for entity_id, label in person.entities:
            aliases = person.aliases_for(entity_id)
            names = {
                entity_id.casefold(),
                label.casefold(),
                *(alias.casefold() for alias in aliases),
            }
            if key not in names:
                continue
            if (
                person.user_id != self.household.speaker.user_id
                and entity_id in person.private
            ):
                private_match = True
                continue
            matched.append((entity_id, person.entity_label(entity_id, label), aliases))
        if private_match and not matched:
            return None, {
                "problem": "private",
                "message": "That entity is private to its owner.",
            }
        if not matched:
            return None, {
                "problem": "entity_not_assigned",
                "message": (
                    f"No entity matching {requested!r} is assigned to "
                    f"{self.household.reference(person)}."
                ),
            }
        if len(matched) > 1:
            return None, {
                "problem": "choose_entity",
                "message": (
                    "More than one assigned entity matches. Ask which one, then call "
                    "again with its entity ID or alias."
                ),
                "options": [
                    {
                        "entity_id": entity_id,
                        "name": label,
                        **({"aliases": list(aliases[1:])} if len(aliases) > 1 else {}),
                    }
                    for entity_id, label, aliases in matched
                ],
            }
        return matched[0], None

    def _entity_for_operation(self, person: Person, requested: str, operation: str):
        """Resolve a linked device by its shared name and route by operation."""
        key = requested.strip().casefold()
        links = [
            link
            for link in person.entity_links
            if key
            in {
                link[0].casefold(),
                link[1].casefold(),
                link[2].casefold(),
                *(alias.casefold() for alias in link[4]),
            }
        ]
        if links:
            if len(links) > 1:
                return None, {
                    "problem": "choose_entity",
                    "message": "More than one linked device matches. Ask which device, then try again.",
                    "options": [{"name": link[0]} for link in links],
                }
            name, state_entity, action_entity, private, _aliases = links[0]
            entity_id = state_entity if operation == "read" else action_entity
            if not entity_id:
                return None, {
                    "problem": f"no_{operation}_entity",
                    "message": f"{name} has no entity configured for {operation} operations.",
                }
            if self.household.speaker.user_id != person.user_id and (
                private or entity_id in person.private
            ):
                return None, {
                    "problem": "private",
                    "message": "That linked device is private to its owner.",
                }
            return (entity_id, name, ()), None
        return self._assigned_entity(person, requested)

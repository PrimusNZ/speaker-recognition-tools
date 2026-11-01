"""Per-person to-do list tools: read items, add, update and remove them.

Only to-do lists assigned to a person are used. A household list, such as a
shared shopping list, is left to Home Assistant's own tools unless it is
assigned to someone. Every change is previewed and needs an explicit yes.
"""

from __future__ import annotations

from typing import Any

import probatio as vol
from homeassistant.components.todo.const import TodoListEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm

from .tool_base import (
    _PERSON_PARAMETER_GUIDANCE,
    _READ_ONLY,
    _WRITE,
    TODO_LISTS,
    Household,
    _parse_when,
    _people_parameter_guidance,
    _PersonTool,
    _result,
)

_STATUSES = ("needs_action", "completed")
_CHOICE_NOTE = (
    "If a person has more than one to-do list the result asks for a choice; ask "
    "the speaker, then call again with the chosen entity_id or configured entity "
    "alias in lists."
)
_CONFIRM_NOTE = (
    "Always call once to preview, ask the speaker for an explicit yes, then call "
    "again with the same request, confirmation_token and confirmed=true. Never "
    "change the list on the first call."
)


def _one_list(household: Household, args: dict[str, Any]):
    """Resolve exactly one assigned to-do list for a change."""
    if args.get("person"):
        people, problems = household.find([args["person"]])
    else:
        people, problems = [household.speaker], []
    targets, more = household.resolve_targets(
        people, [args["list"]] if args.get("list") else None, TODO_LISTS
    )
    problems.extend(more)
    if len(targets) != 1 and not problems:
        problems.append(
            {
                "problem": "one_todo_list_required",
                "message": "Choose exactly one person's to-do list for this change.",
            }
        )
    return (targets[0] if len(targets) == 1 else None), problems


def _supports(hass: HomeAssistant, entity_id: str, feature: int) -> bool:
    state = hass.states.get(entity_id)
    return bool(state and int(state.attributes.get("supported_features", 0)) & feature)


async def _items(
    hass: HomeAssistant, entity_id: str, llm_context: llm.LLMContext
) -> list[dict[str, Any]]:
    response = await hass.services.async_call(
        "todo",
        "get_items",
        {"entity_id": entity_id},
        context=llm_context.context,
        blocking=True,
        return_response=True,
    )
    return list(response[entity_id]["items"])


def _find_item(items: list[dict[str, Any]], requested: str) -> list[dict[str, Any]]:
    """Match an item by uid, then by exact summary ignoring case."""
    by_uid = [i for i in items if i.get("uid") == requested]
    if by_uid:
        return by_uid
    key = requested.strip().casefold()
    return [i for i in items if str(i.get("summary", "")).casefold() == key]


def _due_fields(args: dict[str, Any]) -> dict[str, str]:
    """Turn an optional due value into the todo service's due field."""
    if not args.get("due"):
        return {}
    when, date_only = _parse_when(args["due"])
    return (
        {"due_date": when.isoformat()}
        if date_only
        else {"due_datetime": when.isoformat()}
    )


class GetTodoItemsTool(_PersonTool):
    """Read the items on one or more people's assigned to-do lists."""

    name = "get_todo_items"
    title = "Get to-do items"
    description = (
        "Get the items on one or more people's own assigned to-do lists. "
        f"{_people_parameter_guidance('Omit people to use the current speaker.')} "
        "status is needs_action (the default) or completed. Private lists can only "
        f"be read by their owner. {_CHOICE_NOTE} These are personal lists; a "
        "household list such as a shared shopping list is not covered unless it "
        "is assigned to a person."
    )
    annotations = _READ_ONLY
    parameters = vol.Schema(
        {
            vol.Optional("people"): [str],
            vol.Optional("lists"): [str],
            vol.Optional("status"): vol.In(_STATUSES),
        }
    )

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ):
        args = tool_input.tool_args
        status = args.get("status", "needs_action")
        people, problems = self._people(args)
        targets, more = self.household.resolve_targets(
            people, args.get("lists"), TODO_LISTS
        )
        problems += more
        results = []
        for person, entity_id, label in targets:
            try:
                items = await _items(hass, entity_id, llm_context)
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
                    "list": label,
                    "entity_id": entity_id,
                    "items": [i for i in items if i.get("status") == status],
                }
            )
        data: dict[str, Any] = {"lists": results}
        if problems:
            data["problems"] = problems
        return _result(data, error=not results and bool(problems))


class AddTodoItemTool(_PersonTool):
    """Add an item to one person's to-do list after confirmation."""

    name = "add_todo_item"
    title = "Add to-do item"
    description = (
        "Add an item to one person's assigned to-do list. item is the text of the "
        "item. Optional due is an ISO 8601 local date or date time, and optional "
        f"description adds detail. {_PERSON_PARAMETER_GUIDANCE} {_CHOICE_NOTE} "
        f"{_CONFIRM_NOTE}"
    )
    annotations = _WRITE
    parameters = vol.Schema(
        {
            vol.Required("item"): str,
            vol.Optional("person"): str,
            vol.Optional("list"): str,
            vol.Optional("due"): str,
            vol.Optional("description"): str,
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
        item = str(args.get("item", "")).strip()
        if not item:
            return _result({"error": "Say what to add."}, error=True)
        target, problems = _one_list(self.household, args)
        if problems or target is None:
            return _result({"problems": problems}, error=True)
        person, entity_id, label = target
        if not _supports(hass, entity_id, TodoListEntityFeature.CREATE_TODO_ITEM):
            return _result({"error": f"{label} does not accept new items."}, error=True)
        try:
            due = _due_fields(args)
        except ValueError as err:
            return _result({"error": str(err)}, error=True)
        fields = {
            "item": item,
            **due,
            **({"description": args["description"]} if args.get("description") else {}),
        }
        preview = {
            "person": self.household.reference(person),
            "list": label,
            **fields,
        }
        if confirmation := self._confirm(
            hass,
            args,
            llm_context,
            action=self.name,
            plan={"list": entity_id, **fields},
            preview=preview,
        ):
            return confirmation
        try:
            await hass.services.async_call(
                "todo",
                "add_item",
                {"entity_id": entity_id, **fields},
                context=llm_context.context,
                blocking=True,
            )
        except (HomeAssistantError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        return _result({"added": True, **preview})


class UpdateTodoItemTool(_PersonTool):
    """Complete, reopen, rename or reschedule one item after confirmation."""

    name = "update_todo_item"
    title = "Update to-do item"
    description = (
        "Change one item on a person's assigned to-do list, for example to mark it "
        "done. item is the item's exact text or uid from get_todo_items. Set status "
        "to completed or needs_action, rename to change its text, or due to an ISO "
        f"8601 local date or date time. {_PERSON_PARAMETER_GUIDANCE} {_CHOICE_NOTE} "
        f"{_CONFIRM_NOTE}"
    )
    annotations = _WRITE
    parameters = vol.Schema(
        {
            vol.Required("item"): str,
            vol.Optional("status"): vol.In(_STATUSES),
            vol.Optional("rename"): str,
            vol.Optional("due"): str,
            vol.Optional("person"): str,
            vol.Optional("list"): str,
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
        target, problems = _one_list(self.household, args)
        if problems or target is None:
            return _result({"problems": problems}, error=True)
        person, entity_id, label = target
        if not _supports(hass, entity_id, TodoListEntityFeature.UPDATE_TODO_ITEM):
            return _result({"error": f"{label} does not allow changes."}, error=True)
        try:
            due = _due_fields(args)
        except ValueError as err:
            return _result({"error": str(err)}, error=True)
        changes = {
            **({"status": args["status"]} if args.get("status") else {}),
            **({"rename": args["rename"].strip()} if args.get("rename") else {}),
            **due,
        }
        if not changes:
            return _result(
                {"error": "Say what to change: status, rename or due."}, error=True
            )
        try:
            matches = _find_item(
                await _items(hass, entity_id, llm_context), str(args["item"])
            )
        except (HomeAssistantError, KeyError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        if len(matches) != 1:
            return _result(
                {
                    "problem": "ambiguous_item" if matches else "item_not_found",
                    "message": (
                        "More than one item matches; use its uid."
                        if matches
                        else f"No item matching {args['item']!r} is on {label}."
                    ),
                    **(
                        {
                            "options": [
                                {"uid": m["uid"], "summary": m["summary"]}
                                for m in matches
                            ]
                        }
                        if matches
                        else {}
                    ),
                },
                error=True,
            )
        found = matches[0]
        preview = {
            "person": self.household.reference(person),
            "list": label,
            "item": found["summary"],
            **changes,
        }
        if confirmation := self._confirm(
            hass,
            args,
            llm_context,
            action=self.name,
            plan={"list": entity_id, "uid": found["uid"], **changes},
            preview=preview,
        ):
            return confirmation
        try:
            await hass.services.async_call(
                "todo",
                "update_item",
                {"entity_id": entity_id, "item": found["uid"], **changes},
                context=llm_context.context,
                blocking=True,
            )
        except (HomeAssistantError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        return _result({"updated": True, **preview})


class RemoveTodoItemTool(_PersonTool):
    """Remove one item from a person's to-do list after confirmation."""

    name = "remove_todo_item"
    title = "Remove to-do item"
    description = (
        "Remove one item from a person's assigned to-do list. item is the item's "
        "exact text or uid from get_todo_items. To mark an item done rather than "
        f"delete it, use update_todo_item. {_PERSON_PARAMETER_GUIDANCE} "
        f"{_CHOICE_NOTE} {_CONFIRM_NOTE}"
    )
    annotations = _WRITE
    parameters = vol.Schema(
        {
            vol.Required("item"): str,
            vol.Optional("person"): str,
            vol.Optional("list"): str,
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
        target, problems = _one_list(self.household, args)
        if problems or target is None:
            return _result({"problems": problems}, error=True)
        person, entity_id, label = target
        if not _supports(hass, entity_id, TodoListEntityFeature.DELETE_TODO_ITEM):
            return _result(
                {"error": f"{label} does not allow removing items."}, error=True
            )
        try:
            matches = _find_item(
                await _items(hass, entity_id, llm_context), str(args["item"])
            )
        except (HomeAssistantError, KeyError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        if len(matches) != 1:
            return _result(
                {
                    "problem": "ambiguous_item" if matches else "item_not_found",
                    "message": (
                        "More than one item matches; use its uid."
                        if matches
                        else f"No item matching {args['item']!r} is on {label}."
                    ),
                },
                error=True,
            )
        found = matches[0]
        preview = {
            "person": self.household.reference(person),
            "list": label,
            "item": found["summary"],
        }
        if confirmation := self._confirm(
            hass,
            args,
            llm_context,
            action=self.name,
            plan={"list": entity_id, "uid": found["uid"]},
            preview=preview,
        ):
            return confirmation
        try:
            await hass.services.async_call(
                "todo",
                "remove_item",
                {"entity_id": entity_id, "item": [found["uid"]]},
                context=llm_context.context,
                blocking=True,
            )
        except (HomeAssistantError, ValueError) as err:
            return _result({"error": str(err)}, error=True)
        return _result({"removed": True, **preview})

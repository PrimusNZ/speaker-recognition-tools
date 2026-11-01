"""Send a message to a person's phone, after a preview and an explicit yes."""

from __future__ import annotations

from typing import Any

import probatio as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm

from .prompt import Person
from .tool_base import (
    _people_parameter_guidance,
    _PersonTool,
    _result,
)

NOTIFY_DOMAINS = ("notify",)


def message_targets(
    hass: HomeAssistant, household, person: Person
) -> tuple[list[str], list[str]]:
    """Return (notify entities, legacy notify actions) the speaker may use."""
    _, usable = household.entities(person, NOTIFY_DOMAINS)
    entities = [entity_id for entity_id, _ in usable]
    actions = []
    if person.notify_service:
        domain, _, service = person.notify_service.partition(".")
        if (
            domain == "notify"
            and service
            and hass.services.has_service(domain, service)
        ):
            actions.append(person.notify_service)
    return entities, actions


class SendMessageToPersonTool(_PersonTool):
    """Send a short message to one or more people's phones."""

    name = "send_message_to_person"
    title = "Send message to person"
    description = (
        "Send a short message to one or more people's phones, for example "
        '"tell Sarah dinner is ready". '
        f"{_people_parameter_guidance('people is required.')} message is the "
        "text to send, written for the recipient. title is optional and defaults "
        "to saying who it is from. Always call once to preview, ask the speaker "
        "for an explicit yes, then call again with the same request, "
        "confirmation_token and confirmed=true. Never send on the first call."
    )
    annotations = llm.ToolAnnotations(
        read_only=False, destructive=False, idempotent=False, open_world=True
    )
    parameters = vol.Schema(
        {
            vol.Required("people"): [str],
            vol.Required("message"): str,
            vol.Optional("title"): str,
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
        message = str(args.get("message", "")).strip()
        if not message:
            return _result({"error": "Say what the message should say."}, error=True)
        people, problems = self.household.find(args.get("people"))
        if not people and not problems:
            return _result({"error": "Say who to send the message to."}, error=True)
        title = str(args.get("title") or "").strip() or (
            f"Message from {self.household.reference(self.household.speaker)}"
        )
        recipients: list[tuple[Person, list[str], list[str]]] = []
        for person in people:
            entities, actions = message_targets(hass, self.household, person)
            if entities or actions:
                recipients.append((person, entities, actions))
            else:
                problems.append(
                    {
                        "person": self.household.reference(person),
                        "problem": "no_message_target",
                        "message": (
                            f"{self.household.reference(person)} has no phone set "
                            "up for messages."
                        ),
                    }
                )
        if problems:
            # All or nothing, so nobody gets a message the others did not.
            return _result({"problems": problems}, error=True)

        preview = {
            "to": [self.household.reference(p) for p, _, _ in recipients],
            "title": title,
            "message": message,
        }
        plan = {
            "to": [
                (p.user_id, sorted(entities), sorted(actions))
                for p, entities, actions in recipients
            ],
            "title": title,
            "message": message,
        }
        if confirmation := self._confirm(
            hass, args, llm_context, action=self.name, plan=plan, preview=preview
        ):
            return confirmation

        sent: list[str] = []
        failed: list[dict[str, Any]] = []
        for person, entities, actions in recipients:
            try:
                if entities:
                    await hass.services.async_call(
                        "notify",
                        "send_message",
                        {"entity_id": entities, "message": message, "title": title},
                        context=llm_context.context,
                        blocking=True,
                    )
                for action in actions:
                    await hass.services.async_call(
                        "notify",
                        action.partition(".")[2],
                        {"message": message, "title": title},
                        context=llm_context.context,
                        blocking=True,
                    )
            except (HomeAssistantError, ValueError) as err:
                failed.append(
                    {"person": self.household.reference(person), "error": str(err)}
                )
                continue
            sent.append(self.household.reference(person))
        result: dict[str, Any] = {"sent_to": sent, "title": title, "message": message}
        if failed:
            result["failed"] = failed
        return _result(result, error=bool(failed))

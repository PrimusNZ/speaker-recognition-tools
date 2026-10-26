"""Config, options and subentry flows for Speaker Recognition Tools."""

from __future__ import annotations

import random
from html import escape as html_escape
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    selector,
)

from .const import (
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_PRIVATE_ENTITIES,
    CONF_REFUSAL_LINES,
    CONF_TITLE,
    CONF_THIRD_PERSON_REFERENCE,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_TITLE,
    CONF_USER_ID,
    DEFAULT_REFUSAL_LINES,
    DEFAULT_UNKNOWN_TITLE,
    DOMAIN,
    SUBENTRY_PREVIEW,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_DEVICE,
    TOOL_TYPE_PERSON,
)
from .prompt import Person, build_device_prompt, build_person_prompt

_PREVIEW_UNKNOWN = "__unknown_speaker__"


class SpeakerRecognitionToolsFlow(ConfigFlow, domain=DOMAIN):
    """Pick a prompt addition to add, or preview the integration prompt."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=["speaking_person", "speaking_device", "preview_full"],
        )

    async def async_step_preview_full(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Preview the integration prompt, even when no person entry exists."""
        prompt, disclaimer, note = await _full_prompt_content(self.hass, self.context)
        return self.async_show_form(
            step_id="preview_full_result",
            data_schema=vol.Schema({}),
            description_placeholders={
                "disclaimer": disclaimer,
                "prompt": prompt,
                "prompt_box": _prompt_preview_box(prompt),
                "note": note,
            },
        )

    async def async_step_preview_full_result(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_abort(reason="preview_complete")

    async def async_step_speaking_person(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        await self.async_set_unique_id(f"{DOMAIN}_{TOOL_TYPE_PERSON}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Speaking Person",
            data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
            options={
                CONF_UNKNOWN_TITLE: DEFAULT_UNKNOWN_TITLE,
                CONF_DENY_UNKNOWN: False,
                CONF_REFUSAL_LINES: DEFAULT_REFUSAL_LINES,
            },
        )

    async def async_step_speaking_device(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        await self.async_set_unique_id(f"{DOMAIN}_{TOOL_TYPE_DEVICE}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Speaking Device", data={CONF_TOOL_TYPE: TOOL_TYPE_DEVICE}
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SpeakerRecognitionToolsOptions()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Expose person configuration and the integration-level preview on Speaking Person."""
        if config_entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON:
            return {
                SUBENTRY_SPEAKER: SpeakerSubentryFlow,
                SUBENTRY_PREVIEW: FullPromptPreviewSubentryFlow,
            }
        return {}


class SpeakerRecognitionToolsOptions(OptionsFlow):
    """Settings for Speaking Person (the gear icon)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self.config_entry.data.get(CONF_TOOL_TYPE) != TOOL_TYPE_PERSON:
            return self.async_abort(reason="no_options")
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "preview"]
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        opts = self.config_entry.options
        if user_input is not None:
            return self.async_create_entry(data={**opts, **user_input})
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DENY_UNKNOWN, default=opts.get(CONF_DENY_UNKNOWN, False)
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_UNKNOWN_TITLE,
                    default=opts.get(CONF_UNKNOWN_TITLE, DEFAULT_UNKNOWN_TITLE),
                ): selector.TextSelector(),
                vol.Required(
                    CONF_REFUSAL_LINES,
                    default=opts.get(CONF_REFUSAL_LINES, DEFAULT_REFUSAL_LINES),
                ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_preview(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            selected_user_id = user_input[CONF_USER_ID]
            user_id = None if selected_user_id == _PREVIEW_UNKNOWN else selected_user_id
            people = await _configured_people(self.hass, self.config_entry)
            if user_id is not None and not any(p.user_id == user_id for p in people):
                return self.async_abort(reason="preview_person_missing")
            account = await self.hass.auth.async_get_user(user_id) if user_id else None
            prompt = build_person_prompt(
                user_id=user_id,
                user_name=(account.name.split()[0] if account and account.name else None),
                speakers={p.user_id: p.address_title for p in people},
                people=people,
                unknown_title=self.config_entry.options.get(CONF_UNKNOWN_TITLE, DEFAULT_UNKNOWN_TITLE),
                deny_unknown=self.config_entry.options.get(CONF_DENY_UNKNOWN, False),
                refusal_lines=_configured_refusal_lines(self.config_entry),
            )
            return self.async_show_form(
                step_id="preview_result",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "prompt": prompt,
                    "prompt_box": _prompt_preview_box(prompt),
                },
            )
        people = await _configured_people(self.hass, self.config_entry)
        if not people:
            return self.async_abort(reason="preview_no_people")
        return self.async_show_form(
            step_id="preview",
            data_schema=vol.Schema({
                vol.Required(CONF_USER_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=_PREVIEW_UNKNOWN, label="Unknown speaker"
                            ),
                            *[
                                selector.SelectOptionDict(
                                    value=p.user_id,
                                    label=f"{p.name or p.address_title} ({p.address_title})",
                                )
                                for p in people
                            ],
                        ]
                    )
                )
            }),
        )

    async def async_step_preview_result(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_abort(reason="preview_complete")

def _configured_refusal_lines(entry) -> list[str]:
    return [
        line.strip()
        for line in entry.options.get(CONF_REFUSAL_LINES, DEFAULT_REFUSAL_LINES).splitlines()
        if line.strip()
    ] or DEFAULT_REFUSAL_LINES.splitlines()


async def _full_prompt_content(hass, context) -> tuple[str, str, str]:
    """Build only the prompt sections from configured integration APIs."""
    entries = hass.config_entries.async_entries(DOMAIN)
    person_entry = next(
        (entry for entry in entries if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON),
        None,
    )
    device_entry = next(
        (entry for entry in entries if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_DEVICE),
        None,
    )
    sections = []
    notes = []
    disclaimer = ""

    if person_entry:
        people = await _configured_people(hass, person_entry)
        options = person_entry.options
        account, uses_session_account = await _preview_account(hass, context)
        person_prompt = build_person_prompt(
            user_id=account.id if account else None,
            user_name=(account.name.split()[0] if account and account.name else None),
            speakers={p.user_id: p.address_title for p in people},
            people=people,
            unknown_title=options.get(CONF_UNKNOWN_TITLE, DEFAULT_UNKNOWN_TITLE),
            deny_unknown=options.get(CONF_DENY_UNKNOWN, False),
            refusal_lines=_configured_refusal_lines(person_entry),
        )
        sections.append(person_prompt)
        notes.append(
            "Uses the signed-in Home Assistant account."
            if uses_session_account
            else "This flow did not provide the signed-in account ID, so the Home Assistant owner account is used."
        )

    if device_entry:
        device_prompt, device_note = _sample_device_prompt(hass)
        sections.append(device_prompt)
        disclaimer = (
            "Disclaimer: This is an example rendering. The Speaking Device section "
            "may show a randomly selected registered device."
        )
        notes.append(device_note)

    if not sections:
        return (
            "",
            "",
            "Neither Speaking Person nor Speaking Device is configured, so the integration adds no prompt sections.",
        )

    notes.append(
        "A conversation agent receives only APIs selected for that agent. Home Assistant "
        "appends them after the conversation prompt in the order they were added. This "
        "preview excludes the agent's own prompt and Home Assistant's API wrapper text."
    )
    return "\n\n".join(sections), disclaimer, " ".join(notes)


def _prompt_preview_box(prompt: str) -> str:
    """Render literal prompt text in a shaded, wrapping Home Assistant alert."""
    if not prompt:
        return ""
    escaped_prompt = html_escape(prompt, quote=False).replace("\n", "<br>")
    return f'<ha-alert alert-type="info">{escaped_prompt}</ha-alert>'


async def _preview_account(hass, context):
    """Use the flow's signed-in user when available, or the HA owner account."""
    if user_id := context.get("user_id"):
        if account := await hass.auth.async_get_user(user_id):
            return account, True
    users = await hass.auth.async_get_users()
    account = next((user for user in users if user.is_owner and user.is_active), None)
    return account, False


def _sample_device_prompt(hass) -> tuple[str, str]:
    """Build a device section from an Assist satellite in this installation."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    assist_device_ids = {
        entity.device_id
        for entity in entity_registry.entities.values()
        if entity.domain == "assist_satellite"
        and entity.disabled_by is None
        and entity.device_id is not None
    }
    devices = [
        device_registry.devices[device_id]
        for device_id in assist_device_ids
        if device_id in device_registry.devices
    ]
    with_area = [device for device in devices if _device_area_id(hass, device)]
    candidates = with_area or devices
    if not candidates:
        return (
            build_device_prompt(device_id=None, device_name=None),
            "No registered Assist satellite was found, so the device section says the device is unknown.",
        )
    device = random.choice(candidates)
    area_id = _device_area_id(hass, device)
    area = ar.async_get(hass).async_get_area(area_id) if area_id else None
    prompt = build_device_prompt(
        device_id=device.id,
        device_name=device.name,
        area_name=area.name if area else None,
    )
    return prompt, f"The device section uses {device.name or device.id} as an example device."


def _device_area_id(hass, device) -> str | None:
    """Return a device's assigned or inherited area."""
    return (
        dr.async_get_effective_area_id(hass, device)
        if hasattr(dr, "async_get_effective_area_id")
        else device.area_id
    )


async def _configured_people(hass, entry) -> list[Person]:
    """Build the same per-person data used by the live prompt for preview."""
    people = []
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_SPEAKER:
            continue
        account = await hass.auth.async_get_user(sub.data[CONF_USER_ID])
        name_parts = (account.name if account else "").split()
        name = name_parts[0] if name_parts else None
        title = sub.data.get(CONF_TITLE) or ""
        if not name:
            continue
        entities = tuple(
            (entity_id, hass.states.get(entity_id).name if hass.states.get(entity_id) else entity_id)
            for entity_id in sub.data.get(CONF_ENTITIES, [])
        )
        people.append(Person(
            sub.data[CONF_USER_ID], name, title, entities,
            frozenset(sub.data.get(CONF_PRIVATE_ENTITIES, [])),
            sub.data.get(CONF_THIRD_PERSON_REFERENCE) or None,
        ))
    return people


def _private_is_assigned(user_input: dict[str, Any]) -> bool:
    """Private entities must also be in the person's entity list."""
    return set(user_input.get(CONF_PRIVATE_ENTITIES, [])) <= set(
        user_input.get(CONF_ENTITIES, [])
    )


class SpeakerSubentryFlow(ConfigSubentryFlow):
    """Add or change one person: a Home Assistant user account and an optional title."""

    async def _user_options(self) -> list[selector.SelectOptionDict]:
        users = await self.hass.auth.async_get_users()
        return [
            selector.SelectOptionDict(value=u.id, label=u.name or u.id)
            for u in users
            if not u.system_generated and u.is_active
        ]

    async def _title(
        self, user_id: str, title: str, entities: list[str], private: list[str]
    ) -> str:
        """Return the list label, e.g. "James: Dad (3 entities, 1 private)"."""
        user = await self.hass.auth.async_get_user(user_id)
        name = user.name if user else user_id
        count = len(entities)
        amount = (
            "no entities" if not count else f"{count} {'entity' if count == 1 else 'entities'}"
        )
        if private:
            amount += f", {len(private)} private"
        return f"{f'{name}: {title}' if title else name} ({amount})"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        errors: dict[str, str] = {}
        warnings = ""
        if user_input is not None:
            taken = {
                sub.data[CONF_USER_ID]
                for sub in entry.subentries.values()
                if sub.subentry_type == SUBENTRY_SPEAKER
            }
            if user_input[CONF_USER_ID] in taken:
                errors[CONF_USER_ID] = "already_configured"
            elif not _private_is_assigned(user_input):
                errors[CONF_PRIVATE_ENTITIES] = "private_not_assigned"
            else:
                warnings = await _entity_issues(
                    self.hass, entry, user_input.get(CONF_ENTITIES, [])
                )
                warning_key = (
                    user_input[CONF_USER_ID],
                    tuple(sorted(user_input.get(CONF_ENTITIES, []))),
                    warnings,
                )
                if warnings and getattr(self, "_acknowledged_entity_warning", None) != warning_key:
                    self._acknowledged_entity_warning = warning_key
                    errors["base"] = "entity_warnings_acknowledge"
                else:
                    title = user_input.get(CONF_TITLE, "").strip()
                    return self.async_create_entry(
                        title=await self._title(
                            user_input[CONF_USER_ID], title,
                            user_input.get(CONF_ENTITIES, []),
                            user_input.get(CONF_PRIVATE_ENTITIES, []),
                        ),
                        data={
                            CONF_USER_ID: user_input[CONF_USER_ID],
                            CONF_TITLE: title,
                            CONF_ENTITIES: user_input.get(CONF_ENTITIES, []),
                            CONF_PRIVATE_ENTITIES: user_input.get(CONF_PRIVATE_ENTITIES, []),
                            **({CONF_THIRD_PERSON_REFERENCE: user_input[CONF_THIRD_PERSON_REFERENCE].strip()}
                               if user_input.get(CONF_THIRD_PERSON_REFERENCE, "").strip() else {}),
                        },
                        unique_id=user_input[CONF_USER_ID],
                    )
        schema = vol.Schema(
            {
                vol.Required(CONF_USER_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=await self._user_options())
                ),
                vol.Optional(CONF_TITLE): selector.TextSelector(),
                vol.Optional(CONF_THIRD_PERSON_REFERENCE): selector.TextSelector(),
                vol.Optional(CONF_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
                vol.Optional(CONF_PRIVATE_ENTITIES): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
            }
        )
        chosen = user_input.get(CONF_ENTITIES, []) if user_input else []
        issues = warnings or await _entity_issues(self.hass, entry, chosen)
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors,
            description_placeholders={"entity_warnings": issues},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        warnings = ""
        if user_input is not None and not _private_is_assigned(user_input):
            errors[CONF_PRIVATE_ENTITIES] = "private_not_assigned"
        elif user_input is not None:
            warnings = await _entity_issues(
                self.hass, entry, user_input.get(CONF_ENTITIES, []),
                exclude_user_id=subentry.data[CONF_USER_ID],
            )
            warning_key = (
                tuple(sorted(user_input.get(CONF_ENTITIES, []))), warnings
            )
            if warnings and getattr(self, "_acknowledged_entity_warning", None) != warning_key:
                self._acknowledged_entity_warning = warning_key
                errors["base"] = "entity_warnings_acknowledge"
            else:
                title = user_input.get(CONF_TITLE, "").strip()
                user_id = subentry.data[CONF_USER_ID]
                return self.async_update_and_abort(
                    entry, subentry,
                    title=await self._title(
                        user_id, title, user_input.get(CONF_ENTITIES, []),
                        user_input.get(CONF_PRIVATE_ENTITIES, []),
                    ),
                    data={
                        CONF_USER_ID: user_id,
                        CONF_TITLE: title,
                        CONF_ENTITIES: user_input.get(CONF_ENTITIES, []),
                        CONF_PRIVATE_ENTITIES: user_input.get(CONF_PRIVATE_ENTITIES, []),
                        **({CONF_THIRD_PERSON_REFERENCE: user_input[CONF_THIRD_PERSON_REFERENCE].strip()}
                           if user_input.get(CONF_THIRD_PERSON_REFERENCE, "").strip() else {}),
                    },
                )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TITLE,
                    description={"suggested_value": subentry.data.get(CONF_TITLE, "")},
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_THIRD_PERSON_REFERENCE,
                    description={"suggested_value": subentry.data.get(CONF_THIRD_PERSON_REFERENCE, "")},
                ): selector.TextSelector(),
                vol.Optional(
                    CONF_ENTITIES,
                    default=subentry.data.get(CONF_ENTITIES, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
                vol.Optional(
                    CONF_PRIVATE_ENTITIES,
                    default=subentry.data.get(CONF_PRIVATE_ENTITIES, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
            }
        )
        chosen = user_input.get(CONF_ENTITIES, []) if user_input else subentry.data.get(CONF_ENTITIES, [])
        issues = warnings or await _entity_issues(self.hass, entry, chosen, exclude_user_id=subentry.data[CONF_USER_ID])
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors,
            description_placeholders={"entity_warnings": issues},
        )


class FullPromptPreviewSubentryFlow(ConfigSubentryFlow):
    """Show the full prompt from the integration page without creating a subentry."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            return self.async_abort(reason="preview_complete")
        prompt, disclaimer, note = await _full_prompt_content(self.hass, self.context)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "disclaimer": disclaimer,
                "prompt": prompt,
                "prompt_box": _prompt_preview_box(prompt),
                "note": note,
            },
        )


async def _entity_issues(hass, entry, entities: list[str], exclude_user_id: str | None = None) -> str:
    """Describe stale entity IDs and assignments shared by multiple people."""
    stale = sorted(entity_id for entity_id in entities if hass.states.get(entity_id) is None)
    owners = {}
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_SPEAKER or sub.data[CONF_USER_ID] == exclude_user_id:
            continue
        for entity_id in sub.data.get(CONF_ENTITIES, []):
            if entity_id in entities:
                owners.setdefault(entity_id, []).append(sub.title)
    shared = sorted(owners)
    messages = []
    if stale:
        messages.append("No current state found for: " + ", ".join(stale))
    if shared:
        messages.append("Also assigned to another person: " + ", ".join(shared))
    return "\n".join(messages)

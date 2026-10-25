"""Config, options and subentry flows for Speaker Recognition Tools."""

from __future__ import annotations

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
from homeassistant.helpers import selector

from .const import (
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_PRIVATE_ENTITIES,
    CONF_REFUSAL_LINES,
    CONF_TITLE,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_TITLE,
    CONF_USER_ID,
    DEFAULT_REFUSAL_LINES,
    DEFAULT_UNKNOWN_TITLE,
    DOMAIN,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_DEVICE,
    TOOL_TYPE_PERSON,
)
from .prompt import Person, build_person_prompt


class SpeakerRecognitionToolsFlow(ConfigFlow, domain=DOMAIN):
    """Pick which tool to add; one entry per tool, like the Voice Satellite tools."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=["speaking_person", "speaking_device"]
        )

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
        """Only Speaking Person has people under it."""
        if config_entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON:
            return {SUBENTRY_SPEAKER: SpeakerSubentryFlow}
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
            user_id = user_input[CONF_USER_ID]
            people = await _configured_people(self.hass, self.config_entry)
            person = next((p for p in people if p.user_id == user_id), None)
            if person is None:
                return self.async_abort(reason="preview_person_missing")
            account = await self.hass.auth.async_get_user(user_id)
            prompt = build_person_prompt(
                user_id=user_id,
                user_name=(account.name.split()[0] if account and account.name else None),
                speakers={p.user_id: p.title for p in people},
                people=people,
                unknown_title=self.config_entry.options.get(CONF_UNKNOWN_TITLE, DEFAULT_UNKNOWN_TITLE),
                deny_unknown=self.config_entry.options.get(CONF_DENY_UNKNOWN, False),
                refusal_lines=[
                    line.strip() for line in self.config_entry.options.get(
                        CONF_REFUSAL_LINES, DEFAULT_REFUSAL_LINES
                    ).splitlines() if line.strip()
                ] or DEFAULT_REFUSAL_LINES.splitlines(),
            )
            return self.async_show_form(
                step_id="preview_result",
                data_schema=vol.Schema({}),
                description_placeholders={"prompt": prompt},
            )
        people = await _configured_people(self.hass, self.config_entry)
        if not people:
            return self.async_abort(reason="preview_no_people")
        return self.async_show_form(
            step_id="preview",
            data_schema=vol.Schema({
                vol.Required(CONF_USER_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=p.user_id, label=f"{p.name or p.title} ({p.title})")
                        for p in people
                    ])
                )
            }),
        )

    async def async_step_preview_result(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_abort(reason="preview_complete")


async def _configured_people(hass, entry) -> list[Person]:
    """Build the same per-person data used by the live prompt for preview."""
    people = []
    for sub in entry.subentries.values():
        if sub.subentry_type != SUBENTRY_SPEAKER:
            continue
        account = await hass.auth.async_get_user(sub.data[CONF_USER_ID])
        name_parts = (account.name if account else "").split()
        name = name_parts[0] if name_parts else None
        title = sub.data.get(CONF_TITLE) or name
        if not title:
            continue
        entities = tuple(
            (entity_id, hass.states.get(entity_id).name if hass.states.get(entity_id) else entity_id)
            for entity_id in sub.data.get(CONF_ENTITIES, [])
        )
        people.append(Person(
            sub.data[CONF_USER_ID], name, title, entities,
            frozenset(sub.data.get(CONF_PRIVATE_ENTITIES, [])),
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
                        },
                        unique_id=user_input[CONF_USER_ID],
                    )
        schema = vol.Schema(
            {
                vol.Required(CONF_USER_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=await self._user_options())
                ),
                vol.Optional(CONF_TITLE): selector.TextSelector(),
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
                    },
                )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TITLE,
                    description={"suggested_value": subentry.data.get(CONF_TITLE, "")},
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

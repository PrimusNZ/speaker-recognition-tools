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
        return self.async_show_form(step_id="init", data_schema=schema)


class SpeakerSubentryFlow(ConfigSubentryFlow):
    """Add or change one person: a Home Assistant user account and its title."""

    async def _user_options(self) -> list[selector.SelectOptionDict]:
        users = await self.hass.auth.async_get_users()
        return [
            selector.SelectOptionDict(value=u.id, label=u.name or u.id)
            for u in users
            if not u.system_generated and u.is_active
        ]

    async def _title(self, user_id: str, title: str) -> str:
        user = await self.hass.auth.async_get_user(user_id)
        return f"{user.name if user else user_id}: {title}"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            taken = {
                sub.data[CONF_USER_ID]
                for sub in entry.subentries.values()
                if sub.subentry_type == SUBENTRY_SPEAKER
            }
            if user_input[CONF_USER_ID] in taken:
                errors[CONF_USER_ID] = "already_configured"
            else:
                title = user_input[CONF_TITLE].strip()
                return self.async_create_entry(
                    title=await self._title(user_input[CONF_USER_ID], title),
                    data={CONF_USER_ID: user_input[CONF_USER_ID], CONF_TITLE: title},
                    unique_id=user_input[CONF_USER_ID],
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_USER_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=await self._user_options())
                ),
                vol.Required(CONF_TITLE): selector.TextSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            title = user_input[CONF_TITLE].strip()
            user_id = subentry.data[CONF_USER_ID]
            return self.async_update_and_abort(
                entry,
                subentry,
                title=await self._title(user_id, title),
                data={CONF_USER_ID: user_id, CONF_TITLE: title},
            )
        schema = vol.Schema(
            {vol.Required(CONF_TITLE, default=subentry.data[CONF_TITLE]): selector.TextSelector()}
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

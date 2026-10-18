"""Config and options flow for Speaker Recognition Tools."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_DENY_UNKNOWN,
    CONF_REFUSAL_LINES,
    CONF_SPEAKERS,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_TITLE,
    DEFAULT_REFUSAL_LINES,
    DEFAULT_UNKNOWN_TITLE,
    DOMAIN,
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
            title="Speaker Recognition: Speaking Person",
            data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
            options={
                CONF_SPEAKERS: {},
                CONF_UNKNOWN_TITLE: DEFAULT_UNKNOWN_TITLE,
                CONF_DENY_UNKNOWN: False,
                CONF_REFUSAL_LINES: DEFAULT_REFUSAL_LINES,
            },
        )

    async def async_step_speaking_device(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        await self.async_set_unique_id(f"{DOMAIN}_{TOOL_TYPE_DEVICE}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Speaker Recognition: Speaking Device", data={CONF_TOOL_TYPE: TOOL_TYPE_DEVICE}
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SpeakerRecognitionToolsOptions()


class SpeakerRecognitionToolsOptions(OptionsFlow):
    """Menu: settings, add a person, remove a person."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self.config_entry.data.get(CONF_TOOL_TYPE) != TOOL_TYPE_PERSON:
            return self.async_abort(reason="no_options")
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "add_speaker", "remove_speaker"]
        )

    def _save(self, **changes: Any) -> FlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        opts = self.config_entry.options
        if user_input is not None:
            return self._save(**user_input)
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

    async def async_step_add_speaker(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            speakers = dict(self.config_entry.options.get(CONF_SPEAKERS, {}))
            speakers[user_input["user"]] = user_input["title"].strip()
            return self._save(**{CONF_SPEAKERS: speakers})
        users = [
            u for u in await self.hass.auth.async_get_users()
            if not u.system_generated and u.is_active
        ]
        options = [
            selector.SelectOptionDict(value=u.id, label=u.name or u.id) for u in users
        ]
        schema = vol.Schema(
            {
                vol.Required("user"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options)
                ),
                vol.Required("title"): selector.TextSelector(),
            }
        )
        return self.async_show_form(step_id="add_speaker", data_schema=schema)

    async def async_step_remove_speaker(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        speakers = dict(self.config_entry.options.get(CONF_SPEAKERS, {}))
        if user_input is not None:
            for uid in user_input["remove"]:
                speakers.pop(uid, None)
            return self._save(**{CONF_SPEAKERS: speakers})
        if not speakers:
            return self.async_abort(reason="no_speakers")
        options = []
        for uid, title in speakers.items():
            user = await self.hass.auth.async_get_user(uid)
            options.append(
                selector.SelectOptionDict(
                    value=uid, label=f"{user.name if user else uid}: {title}"
                )
            )
        schema = vol.Schema(
            {
                vol.Required("remove"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, multiple=True)
                )
            }
        )
        return self.async_show_form(step_id="remove_speaker", data_schema=schema)

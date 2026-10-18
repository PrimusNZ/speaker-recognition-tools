"""LLM APIs that inject the speaking person and the speaking device into the prompt."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, llm

from .const import (
    CONF_DENY_UNKNOWN,
    CONF_REFUSAL_LINES,
    CONF_TITLE,
    CONF_USER_ID,
    SUBENTRY_SPEAKER,
    CONF_UNKNOWN_TITLE,
    DEFAULT_REFUSAL_LINES,
    DEFAULT_UNKNOWN_TITLE,
    DEVICE_API_ID,
    DEVICE_API_NAME,
    PERSON_API_ID,
    PERSON_API_NAME,
)
from .prompt import build_device_prompt, build_person_prompt


class SpeakingPersonAPI(llm.API):
    """No tools; adds the speaker's title, or a refusal for unknown speakers."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass=hass, id=PERSON_API_ID, name=PERSON_API_NAME)
        self._entry = entry

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        options = self._entry.options
        user_id = llm_context.context.user_id if llm_context.context else None

        user_name = None
        if user_id and (user := await self.hass.auth.async_get_user(user_id)):
            user_name = user.name

        lines = [
            line.strip()
            for line in options.get(CONF_REFUSAL_LINES, DEFAULT_REFUSAL_LINES).splitlines()
            if line.strip()
        ]
        prompt = build_person_prompt(
            user_id=user_id,
            user_name=user_name,
            speakers={
                sub.data[CONF_USER_ID]: sub.data[CONF_TITLE]
                for sub in self._entry.subentries.values()
                if sub.subentry_type == SUBENTRY_SPEAKER
            },
            unknown_title=options.get(CONF_UNKNOWN_TITLE, DEFAULT_UNKNOWN_TITLE),
            deny_unknown=options.get(CONF_DENY_UNKNOWN, False),
            refusal_lines=lines or DEFAULT_REFUSAL_LINES.splitlines(),
        )
        return llm.APIInstance(
            api=self, api_prompt=prompt, llm_context=llm_context, tools=[]
        )


class SpeakingDeviceAPI(llm.API):
    """No tools; adds the id and name of the device the speaker is using."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass=hass, id=DEVICE_API_ID, name=DEVICE_API_NAME)

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        device_name = None
        if llm_context.device_id:
            device = dr.async_get(self.hass).async_get(llm_context.device_id)
            if device:
                device_name = device.name
        prompt = build_device_prompt(
            device_id=llm_context.device_id, device_name=device_name
        )
        return llm.APIInstance(
            api=self, api_prompt=prompt, llm_context=llm_context, tools=[]
        )

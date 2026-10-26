"""LLM APIs that inject the speaking person and the speaking device into the prompt."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, llm

from .const import (
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_PRIVATE_ENTITIES,
    CONF_REFUSAL_LINES,
    CONF_TITLE,
    CONF_THIRD_PERSON_REFERENCE,
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
from .prompt import Person, build_device_prompt, build_person_prompt
from .tools import build_tools


def _first_name(name: str | None) -> str | None:
    """Return the first word of an account name; only first names reach the prompt."""
    parts = (name or "").split()
    return parts[0] if parts else None


class SpeakingPersonAPI(llm.API):
    """Adds the speaker's title and, for recognised speakers, person-aware tools."""

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
            user_name = _first_name(user.name)

        speakers = {
            sub.data[CONF_USER_ID]: sub.data[CONF_TITLE]
            for sub in self._entry.subentries.values()
            if sub.subentry_type == SUBENTRY_SPEAKER
        }
        people = []
        for sub in self._entry.subentries.values():
            if sub.subentry_type != SUBENTRY_SPEAKER:
                continue
            account = await self.hass.auth.async_get_user(sub.data[CONF_USER_ID])
            entities = []
            for entity_id in sub.data.get(CONF_ENTITIES, []):
                state = self.hass.states.get(entity_id)
                entities.append((entity_id, state.name if state else entity_id))
            name = _first_name(account.name) if account else None
            title = sub.data.get(CONF_TITLE) or name
            if not title:
                continue  # no title and no account name to fall back on
            people.append(
                Person(
                    sub.data[CONF_USER_ID],
                    name,
                    title,
                    tuple(entities),
                    frozenset(sub.data.get(CONF_PRIVATE_ENTITIES, [])),
                    sub.data.get(CONF_THIRD_PERSON_REFERENCE) or None,
                )
            )

        lines = [
            line.strip()
            for line in options.get(CONF_REFUSAL_LINES, DEFAULT_REFUSAL_LINES).splitlines()
            if line.strip()
        ]
        prompt = build_person_prompt(
            user_id=user_id,
            user_name=user_name,
            speakers={p.user_id: p.title for p in people},
            people=people,
            unknown_title=options.get(CONF_UNKNOWN_TITLE, DEFAULT_UNKNOWN_TITLE),
            deny_unknown=options.get(CONF_DENY_UNKNOWN, False),
            refusal_lines=lines or DEFAULT_REFUSAL_LINES.splitlines(),
        )
        # Tools are only offered to recognised speakers, never to unknown ones.
        speaker = next((p for p in people if p.user_id == user_id), None)
        tools = build_tools(people, speaker) if speaker else []
        return llm.APIInstance(
            api=self, api_prompt=prompt, llm_context=llm_context, tools=tools
        )


class SpeakingDeviceAPI(llm.API):
    """No tools; adds the id, name and area of the device the speaker is using."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass=hass, id=DEVICE_API_ID, name=DEVICE_API_NAME)

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        device_name = area_name = None
        if llm_context.device_id:
            device = dr.async_get(self.hass).async_get(llm_context.device_id)
            if device:
                device_name = device.name
                area_id = (
                    dr.async_get_effective_area_id(self.hass, device)
                    if hasattr(dr, "async_get_effective_area_id")
                    else device.area_id
                )
                if area_id and (area := ar.async_get(self.hass).async_get_area(area_id)):
                    area_name = area.name
        prompt = build_device_prompt(
            device_id=llm_context.device_id,
            device_name=device_name,
            area_name=area_name,
        )
        return llm.APIInstance(
            api=self, api_prompt=prompt, llm_context=llm_context, tools=[]
        )

"""The conversation proxy: refuses speakers who are not allowed, then hands on.

It sits between Speaker Recognition's conversation proxy and the real agent, so
it sees the user Speaker Recognition set on the turn. The pattern follows that
proxy: delegate with `source_agent.async_process`, and mirror the wrapped
agent's languages, streaming and availability. It never changes the user on the
turn, so the chat-session owner handling the proxy needs is not needed here.
"""

from __future__ import annotations

import logging
import random
from dataclasses import replace

from homeassistant.components import conversation
from homeassistant.components.conversation import (
    AbstractConversationAgent,
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.intent import IntentResponse, IntentResponseErrorCode

from .const import CONF_REFUSAL_LINES
from .llm_api import announce_speaker, async_person_prompt, device_prompt
from .people import async_configured_people
from .wrapper import (
    person_entry,
    refusal_lines,
    should_deny,
    wrapped_agent,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the wrapper's conversation entity."""
    async_add_entities([SpeakerWrapperConversationEntity(hass, config_entry)])


class SpeakerWrapperConversationEntity(ConversationEntity, AbstractConversationAgent):
    """Wraps one conversation entity and applies the speaker rules before it."""

    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._attr_unique_id = config_entry.entry_id
        self._wrapped_entity_id = wrapped_agent(config_entry)
        registry = er.async_get(hass)
        wrapped = registry.async_get(self._wrapped_entity_id)
        base = (
            (wrapped.original_name if wrapped else None)
            or self._wrapped_entity_id.split(".", 1)[-1]
        )
        self._attr_name = f"{base} Speaker Recognition Tools Proxy"
        self._cached_languages: list[str] | str | None = None

    @callback
    def _source_agent(self) -> AbstractConversationAgent | None:
        return conversation.async_get_agent(self.hass, self._wrapped_entity_id)

    @callback
    def _async_refresh(self) -> None:
        state = self.hass.states.get(self._wrapped_entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            self._attr_available = False
            return
        self._attr_available = True
        if self._cached_languages is None and (agent := self._source_agent()):
            self._cached_languages = agent.supported_languages

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _changed(_event: Event[EventStateChangedData] | None = None) -> None:
            self._async_refresh()
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._wrapped_entity_id], _changed
            )
        )
        _changed()

    @property
    def supported_languages(self) -> list[str] | str:
        return self._cached_languages or []

    @property
    def supports_streaming(self) -> bool:
        """Mirror the wrapped agent. Deltas need no forwarding: it runs in the same task."""
        return getattr(self._source_agent(), "supports_streaming", False) is True

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        source_agent = self._source_agent()
        if source_agent is None:
            response = IntentResponse(language=user_input.language)
            response.async_set_error(
                IntentResponseErrorCode.FAILED_TO_HANDLE,
                f"Wrapped conversation entity {self._wrapped_entity_id} not found",
            )
            return ConversationResult(response=response, conversation_id=None)

        people_entry = person_entry(self.hass)
        people = (
            await async_configured_people(self.hass, people_entry)
            if people_entry
            else []
        )
        user_id = user_input.context.user_id
        speaker = next((p for p in people if p.user_id == user_id), None)

        if should_deny(self.hass, self._config_entry, speaker is not None):
            if people_entry:
                announce_speaker(
                    self.hass,
                    people_entry,
                    None,
                    user_input.device_id,
                    user_input.context,
                )
            lines = refusal_lines(self._config_entry.options.get(CONF_REFUSAL_LINES))
            response = IntentResponse(language=user_input.language)
            response.async_set_speech(random.choice(lines))
            return ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        if extra := await self._async_prompt_sections(
            people_entry, people, user_id, user_input.device_id
        ):
            user_input = replace(
                user_input,
                extra_system_prompt=(
                    f"{user_input.extra_system_prompt}\n\n{extra}"
                    if user_input.extra_system_prompt
                    else extra
                ),
            )
        return await source_agent.async_process(user_input)

    async def _async_prompt_sections(
        self,
        people_entry: ConfigEntry | None,
        people,
        user_id: str | None,
        device_id: str | None,
    ) -> str:
        """The speaker and device text, which only the wrapper supplies."""
        sections = []
        if people_entry:
            sections.append(
                await async_person_prompt(self.hass, people_entry, user_id, people)
            )
        sections.append(device_prompt(self.hass, device_id))
        return "\n\n".join(sections)

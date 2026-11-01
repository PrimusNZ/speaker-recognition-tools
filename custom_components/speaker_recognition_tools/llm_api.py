"""LLM APIs that inject the speaking person and the speaking device into the prompt."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import llm
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DENY_UNKNOWN,
    CONF_LEGACY_UNKNOWN_ADDRESS_AS,
    CONF_MIN_CONFIDENCE,
    CONF_REFUSAL_LINES,
    CONF_UNKNOWN_ADDRESS_AS,
    DEFAULT_REFUSAL_LINES,
    DEFAULT_UNKNOWN_ADDRESS_AS,
    DEVICE_API_ID,
    DEVICE_API_NAME,
    EVENT_SPEAKER,
    PERSON_API_ID,
    PERSON_API_NAME,
    SIGNAL_SPEAKER,
)
from .people import async_configured_people, first_name
from .prompt import Person, build_device_prompt, build_person_prompt
from .recognition import latest_confidence
from .tools import build_tools


def _device_and_area(
    hass: HomeAssistant, device_id: str | None
) -> tuple[str | None, str | None]:
    """Return the device's name and its effective area's name."""
    device_name = area_name = None
    if device_id and (device := dr.async_get(hass).async_get(device_id)):
        device_name = device.name
        area_id = dr.async_get_effective_area_id(hass, device)
        if area_id and (area := ar.async_get(hass).async_get_area(area_id)):
            area_name = area.name
    return device_name, area_name


class SpeakingPersonAPI(llm.API):
    """Adds the speaker's direct-address form and person-aware tools."""

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
            user_name = first_name(user.name)

        people = await async_configured_people(self.hass, self._entry)

        lines = [
            line.strip()
            for line in options.get(
                CONF_REFUSAL_LINES, DEFAULT_REFUSAL_LINES
            ).splitlines()
            if line.strip()
        ]
        prompt = build_person_prompt(
            user_id=user_id,
            user_name=user_name,
            speakers={p.user_id: p.direct_address for p in people},
            people=people,
            unknown_address_as=options.get(
                CONF_UNKNOWN_ADDRESS_AS,
                options.get(CONF_LEGACY_UNKNOWN_ADDRESS_AS, DEFAULT_UNKNOWN_ADDRESS_AS),
            ),
            deny_unknown=options.get(CONF_DENY_UNKNOWN, False),
            refusal_lines=lines or DEFAULT_REFUSAL_LINES.splitlines(),
        )
        # Tools are only offered to recognised speakers, never to unknown ones.
        speaker = next((p for p in people if p.user_id == user_id), None)
        confidence = (
            latest_confidence(self.hass, user_id, llm_context.device_id)
            if speaker
            else None
        )
        threshold = float(options.get(CONF_MIN_CONFIDENCE, 0) or 0)
        uncertain = bool(
            threshold and confidence is not None and confidence < threshold
        )
        tools = build_tools(people, speaker, uncertain=uncertain) if speaker else []
        self._announce(speaker, llm_context, confidence, uncertain)
        return llm.APIInstance(
            api=self, api_prompt=prompt, llm_context=llm_context, tools=tools
        )

    def _announce(
        self,
        speaker: Person | None,
        llm_context: llm.LLMContext,
        confidence: float | None,
        uncertain: bool,
    ) -> None:
        """Tell automations and the Last speaker sensor who is speaking."""
        device_name, area_name = _device_and_area(self.hass, llm_context.device_id)
        data = {
            "recognised": speaker is not None,
            "user_id": speaker.user_id if speaker else None,
            "name": (speaker.full_name or speaker.name) if speaker else None,
            "address_as": speaker.direct_address if speaker else None,
            "device_id": llm_context.device_id,
            "device": device_name,
            "area": area_name,
            "confidence": confidence,
            "uncertain": uncertain,
            "time": dt_util.utcnow().isoformat(),
        }
        self.hass.bus.async_fire(
            EVENT_SPEAKER,
            data,
            context=llm_context.context,
        )
        async_dispatcher_send(
            self.hass, SIGNAL_SPEAKER.format(self._entry.entry_id), data
        )


class SpeakingDeviceAPI(llm.API):
    """No tools; adds the id, name and area of the device the speaker is using."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(hass=hass, id=DEVICE_API_ID, name=DEVICE_API_NAME)

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        device_name, area_name = _device_and_area(self.hass, llm_context.device_id)
        prompt = build_device_prompt(
            device_id=llm_context.device_id,
            device_name=device_name,
            area_name=area_name,
        )
        return llm.APIInstance(
            api=self, api_prompt=prompt, llm_context=llm_context, tools=[]
        )

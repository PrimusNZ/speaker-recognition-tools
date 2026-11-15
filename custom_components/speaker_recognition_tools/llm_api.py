"""LLM APIs that inject the speaking person and the speaking device into the prompt."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import llm
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LEGACY_UNKNOWN_ADDRESS_AS,
    CONF_MIN_CONFIDENCE,
    CONF_UNKNOWN_ADDRESS_AS,
    DEFAULT_UNKNOWN_ADDRESS_AS,
    EVENT_SPEAKER,
    NO_WRAPPER_NOTICE,
    PERSON_API_ID,
    PERSON_API_NAME,
    SIGNAL_SPEAKER,
    WRAPPER_API_POINTER,
)
from .household_tools import build_household_tools, household_devices
from .people import (
    async_configured_people,
    first_name,
    household_aliases,
    household_entity_ids,
)
from .prompt import Person, build_device_prompt, build_person_prompt
from .recognition import latest_confidence
from .tools import build_tools
from .wrapper import denial_settings, refusal_lines, wrapper_is_active


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


async def async_person_prompt(
    hass: HomeAssistant,
    entry: ConfigEntry,
    user_id: str | None,
    people: list[Person],
) -> str:
    """The SPEAKING PERSON section for one speaker, as the API and the wrapper use it."""
    options = entry.options
    user_name = None
    if user_id and (user := await hass.auth.async_get_user(user_id)):
        user_name = first_name(user.name)
    deny_unknown, refusal_text = denial_settings(hass)
    household_ids = household_entity_ids(entry)
    return build_person_prompt(
        user_id=user_id,
        user_name=user_name,
        speakers={p.user_id: p.direct_address for p in people},
        people=people,
        unknown_address_as=options.get(
            CONF_UNKNOWN_ADDRESS_AS,
            options.get(CONF_LEGACY_UNKNOWN_ADDRESS_AS, DEFAULT_UNKNOWN_ADDRESS_AS),
        ),
        deny_unknown=deny_unknown,
        refusal_lines=refusal_lines(refusal_text),
        household_devices=tuple(
            household_devices(
                hass,
                [
                    e
                    for e in household_ids
                    if not any(e in p.private and p.user_id != user_id for p in people)
                ],
                household_aliases(entry),
            )
        ),
    )


def device_prompt(hass: HomeAssistant, device_id: str | None) -> str:
    """The SPEAKING DEVICE section for the device a request came through."""
    device_name, area_name = _device_and_area(hass, device_id)
    return build_device_prompt(
        device_id=device_id, device_name=device_name, area_name=area_name
    )


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

        people = await async_configured_people(self.hass, self._entry)
        household_ids = household_entity_ids(self._entry)
        aliases = household_aliases(self._entry)
        deny_unknown, _ = denial_settings(self.hass)
        if not wrapper_is_active(self.hass):
            # Without the wrapper nobody can be told apart, so offer no tools.
            return llm.APIInstance(
                api=self,
                api_prompt=NO_WRAPPER_NOTICE,
                llm_context=llm_context,
                tools=[],
            )
        # The wrapper supplies the speaker text through the turn's extra prompt.
        prompt = WRAPPER_API_POINTER
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
        if speaker:
            tools = [
                *build_tools(people, speaker, uncertain=uncertain),
                *build_household_tools(
                    household_ids,
                    people,
                    speaker,
                    uncertain=uncertain,
                    aliases=aliases,
                ),
            ]
        elif deny_unknown:
            tools = []
        else:
            # Unknown speakers get only the household devices, never person tools.
            tools = build_household_tools(
                household_ids, people, None, aliases=aliases
            )
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
        announce_speaker(
            self.hass,
            self._entry,
            speaker,
            llm_context.device_id,
            llm_context.context,
            confidence,
            uncertain,
        )


def announce_speaker(
    hass: HomeAssistant,
    entry: ConfigEntry,
    speaker: Person | None,
    device_id: str | None,
    context: Context | None,
    confidence: float | None = None,
    uncertain: bool = False,
) -> None:
    """Fire the speaker event and update the Last speaker sensor for one turn."""
    device_name, area_name = _device_and_area(hass, device_id)
    data = {
        "recognised": speaker is not None,
        "user_id": speaker.user_id if speaker else None,
        "name": (speaker.full_name or speaker.name) if speaker else None,
        "address_as": speaker.direct_address if speaker else None,
        "device_id": device_id,
        "device": device_name,
        "area": area_name,
        "confidence": confidence,
        "uncertain": uncertain,
        "time": dt_util.utcnow().isoformat(),
    }
    hass.bus.async_fire(EVENT_SPEAKER, data, context=context)
    async_dispatcher_send(hass, SIGNAL_SPEAKER.format(entry.entry_id), data)

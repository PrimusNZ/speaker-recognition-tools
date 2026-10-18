"""Speaker Recognition Tools: tells the conversation agent who and where the speaker is."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .const import CONF_TOOL_TYPE, TOOL_TYPE_PERSON
from .llm_api import SpeakingDeviceAPI, SpeakingPersonAPI


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register this entry's LLM API; person options are read live per request."""
    if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON:
        api: llm.API = SpeakingPersonAPI(hass, entry)
    else:
        api = SpeakingDeviceAPI(hass)
    entry.async_on_unload(llm.async_register_api(hass, api))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry (the API is unregistered by async_on_unload)."""
    return True

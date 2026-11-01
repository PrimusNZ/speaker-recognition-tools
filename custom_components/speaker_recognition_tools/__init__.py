"""Speaker Recognition Tools: tells the conversation agent who and where the speaker is."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.helpers.typing import ConfigType

from .const import CONF_TOOL_TYPE, TOOL_TYPE_PERSON
from .issues import async_clear_entry, async_setup_repairs
from .llm_api import SpeakingDeviceAPI, SpeakingPersonAPI
from .services import async_setup_services

PERSON_PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions that scripts can call."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register this entry's LLM API; person options are read live per request."""
    if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON:
        api: llm.API = SpeakingPersonAPI(hass, entry)
        async_setup_repairs(hass, entry)
    else:
        api = SpeakingDeviceAPI(hass)
    entry.async_on_unload(llm.async_register_api(hass, api))
    if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON:
        await hass.config_entries.async_forward_entry_setups(entry, PERSON_PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry (the API is unregistered by async_on_unload)."""
    if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON:
        return await hass.config_entries.async_unload_platforms(entry, PERSON_PLATFORMS)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear any Repairs issues the removed entry raised."""
    async_clear_entry(hass, entry)

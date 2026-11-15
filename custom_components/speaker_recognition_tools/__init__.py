"""Speaker Recognition Tools: tells the conversation agent who and where the speaker is."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_TOOL_TYPE,
    DOMAIN,
    TOOL_TYPE_DEVICE,
    TOOL_TYPE_PERSON,
    TOOL_TYPE_WRAPPER,
)
from .issues import async_clear_entry, async_setup_repairs, async_setup_wrapper_repairs
from .llm_api import SpeakingPersonAPI
from .migration import (
    async_move_calendars_to_their_field,
    async_move_people_to_person_entities,
)
from .services import async_setup_services

PERSON_PLATFORMS = [Platform.SENSOR]
WRAPPER_PLATFORMS = [Platform.CONVERSATION]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions that scripts can call."""
    async_setup_services(hass)
    # Speaking Device is gone: the wrapper now adds the device text. Delete old entries.
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_DEVICE:
            hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring older entries up to date."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON:
            async_move_people_to_person_entities(hass, entry)
        hass.config_entries.async_update_entry(entry, minor_version=2)
    if entry.minor_version < 3:
        if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON:
            async_move_calendars_to_their_field(hass, entry)
        hass.config_entries.async_update_entry(entry, minor_version=3)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register this entry's LLM API; person options are read live per request."""
    if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_WRAPPER:
        async_setup_wrapper_repairs(hass, entry)
        entry.async_on_unload(entry.add_update_listener(_reload_on_update))
        await hass.config_entries.async_forward_entry_setups(entry, WRAPPER_PLATFORMS)
        return True
    if entry.data.get(CONF_TOOL_TYPE) != TOOL_TYPE_PERSON:
        return True  # a Speaking Device entry is being removed
    async_setup_repairs(hass, entry)
    entry.async_on_unload(llm.async_register_api(hass, SpeakingPersonAPI(hass, entry)))
    await hass.config_entries.async_forward_entry_setups(entry, PERSON_PLATFORMS)
    return True


async def _reload_on_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the wrapper so its entity follows a changed wrapped agent."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry (the API is unregistered by async_on_unload)."""
    if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_WRAPPER:
        return await hass.config_entries.async_unload_platforms(
            entry, WRAPPER_PLATFORMS
        )
    if entry.data.get(CONF_TOOL_TYPE) == TOOL_TYPE_PERSON:
        return await hass.config_entries.async_unload_platforms(entry, PERSON_PLATFORMS)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear any Repairs issues the removed entry raised."""
    async_clear_entry(hass, entry)

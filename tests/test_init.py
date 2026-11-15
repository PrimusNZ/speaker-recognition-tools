"""Tests for entry setup, unload and reload."""

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_TOOL_TYPE,
    DOMAIN,
    PERSON_API_ID,
    TOOL_TYPE_DEVICE,
    TOOL_TYPE_PERSON,
)


def _ids(hass: HomeAssistant) -> set[str]:
    return {api.id for api in llm.async_get_apis(hass)}


def _context() -> llm.LLMContext:
    return llm.LLMContext(
        platform="test",
        context=Context(),
        language="en",
        assistant="conversation",
        device_id=None,
    )


async def _add(hass: HomeAssistant, tool_type: str) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_TOOL_TYPE: tool_type})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_registers_the_person_api_only(hass: HomeAssistant) -> None:
    entry = await _add(hass, TOOL_TYPE_PERSON)
    assert entry.state is ConfigEntryState.LOADED
    assert _ids(hass) == {PERSON_API_ID}


async def test_unload_unregisters_the_api(hass: HomeAssistant) -> None:
    entry = await _add(hass, TOOL_TYPE_PERSON)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert PERSON_API_ID not in _ids(hass)
    with pytest.raises(HomeAssistantError):
        await llm.async_get_api(hass, PERSON_API_ID, _context())


async def test_reload_registers_the_api_again(hass: HomeAssistant) -> None:
    entry = await _add(hass, TOOL_TYPE_PERSON)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert PERSON_API_ID in _ids(hass)


async def test_remove_entry_unregisters_the_api(hass: HomeAssistant) -> None:
    entry = await _add(hass, TOOL_TYPE_PERSON)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert PERSON_API_ID not in _ids(hass)


async def test_old_speaking_device_entry_is_deleted_on_setup(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_TOOL_TYPE: TOOL_TYPE_DEVICE})
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries(DOMAIN) == []

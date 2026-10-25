"""Tests for entry setup, unload and reload."""

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_TOOL_TYPE,
    DEVICE_API_ID,
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


@pytest.mark.parametrize(
    ("tool_type", "api_id", "other_id"),
    [
        (TOOL_TYPE_PERSON, PERSON_API_ID, DEVICE_API_ID),
        (TOOL_TYPE_DEVICE, DEVICE_API_ID, PERSON_API_ID),
    ],
)
async def test_setup_registers_only_its_own_api(
    hass: HomeAssistant, tool_type: str, api_id: str, other_id: str
) -> None:
    entry = await _add(hass, tool_type)
    assert entry.state is ConfigEntryState.LOADED
    assert api_id in _ids(hass)
    assert other_id not in _ids(hass)


@pytest.mark.parametrize(
    ("tool_type", "api_id"),
    [(TOOL_TYPE_PERSON, PERSON_API_ID), (TOOL_TYPE_DEVICE, DEVICE_API_ID)],
)
async def test_unload_unregisters_the_api(
    hass: HomeAssistant, tool_type: str, api_id: str
) -> None:
    entry = await _add(hass, tool_type)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert api_id not in _ids(hass)
    with pytest.raises(HomeAssistantError):
        await llm.async_get_api(hass, api_id, _context())


async def test_unloading_one_entry_keeps_the_other(hass: HomeAssistant) -> None:
    person = await _add(hass, TOOL_TYPE_PERSON)
    await _add(hass, TOOL_TYPE_DEVICE)
    assert await hass.config_entries.async_unload(person.entry_id)
    assert _ids(hass) >= {DEVICE_API_ID}
    assert PERSON_API_ID not in _ids(hass)


async def test_reload_registers_the_api_again(hass: HomeAssistant) -> None:
    entry = await _add(hass, TOOL_TYPE_PERSON)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert PERSON_API_ID in _ids(hass)


async def test_remove_entry_unregisters_the_api(hass: HomeAssistant) -> None:
    entry = await _add(hass, TOOL_TYPE_DEVICE)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert DEVICE_API_ID not in _ids(hass)

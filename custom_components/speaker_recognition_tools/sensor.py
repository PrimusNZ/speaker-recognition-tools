"""Last speaker sensor, updated on every Speaking Person turn."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_SPEAKER

UNKNOWN_STATE = "unknown_speaker"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Last speaker sensor for a Speaking Person entry."""
    async_add_entities([LastSpeakerSensor(entry)])


class LastSpeakerSensor(SensorEntity):
    """The first name of the last person who spoke, or unknown_speaker."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_speaker"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_speaker"
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SPEAKER.format(self._entry.entry_id), self._update
            )
        )

    @callback
    def _update(self, data: dict[str, Any]) -> None:
        self._attr_native_value = data["name"] if data["recognised"] else UNKNOWN_STATE
        self._attr_extra_state_attributes = {
            key: data[key]
            for key in (
                "user_id",
                "address_as",
                "device_id",
                "device",
                "area",
                "confidence",
                "uncertain",
                "time",
            )
        }
        self.async_write_ha_state()

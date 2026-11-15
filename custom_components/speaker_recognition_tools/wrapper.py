"""Shared logic for the conversation wrapper: settings, the alarm, and the denial rule."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ALARM_ENTITY,
    CONF_ALARM_UNKNOWN_DISARMED,
    CONF_DENY_UNKNOWN,
    CONF_REFUSAL_LINES,
    CONF_TOOL_TYPE,
    CONF_WRAPPED_AGENT,
    DEFAULT_REFUSAL_LINES,
    DOMAIN,
    TOOL_TYPE_DEVICE,
    TOOL_TYPE_PERSON,
    TOOL_TYPE_WRAPPER,
)

CONF_LLM_HASS_API = "llm_hass_api"  # the key conversation agents save their APIs under
ALARM_DISARMED = "disarmed"


def entry_of_type(hass: HomeAssistant, tool_type: str) -> ConfigEntry | None:
    """The one enabled entry of this type, or None."""
    return next(
        (
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_TOOL_TYPE) == tool_type and not entry.disabled_by
        ),
        None,
    )


def person_entry(hass: HomeAssistant) -> ConfigEntry | None:
    return entry_of_type(hass, TOOL_TYPE_PERSON)


def device_entry(hass: HomeAssistant) -> ConfigEntry | None:
    return entry_of_type(hass, TOOL_TYPE_DEVICE)


def wrapper_entry(hass: HomeAssistant) -> ConfigEntry | None:
    return entry_of_type(hass, TOOL_TYPE_WRAPPER)


def split_lines(text: str | None) -> list[str]:
    """The non-blank lines of a multi-line setting, stripped."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def denial_settings(hass: HomeAssistant) -> tuple[bool, str]:
    """Return (deny unknown speakers, refusal lines text) from the wrapper.

    The wrapper owns these settings. With no wrapper, unknown speakers are not
    denied and the default refusal lines apply.
    """
    options = wrapper.options if (wrapper := wrapper_entry(hass)) else {}
    return (
        bool(options.get(CONF_DENY_UNKNOWN, False)),
        options.get(CONF_REFUSAL_LINES, DEFAULT_REFUSAL_LINES),
    )


def wrapper_is_active(hass: HomeAssistant) -> bool:
    """Whether a loaded wrapper now supplies the speaker and device prompt text."""
    wrapper = wrapper_entry(hass)
    return wrapper is not None and wrapper.state is ConfigEntryState.LOADED


def refusal_lines(text: str | None) -> list[str]:
    """The refusal lines to choose from, never empty."""
    return split_lines(text) or DEFAULT_REFUSAL_LINES.splitlines()


def alarm_counts_as_armed(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Whether the wrapper's home alarm counts as armed.

    Armed means any state other than disarmed, so arming, pending and
    triggered count. With no alarm set it is never armed. An unknown,
    unavailable or missing alarm follows the "treat as disarmed" switch.
    """
    alarm = entry.options.get(CONF_ALARM_ENTITY)
    if not alarm:
        return False
    state = hass.states.get(alarm)
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return not entry.options.get(CONF_ALARM_UNKNOWN_DISARMED, False)
    return state.state != ALARM_DISARMED


def should_deny(hass: HomeAssistant, entry: ConfigEntry, speaker_known: bool) -> bool:
    """The denial rule: deny an unknown speaker if denying is on or the alarm is armed.

    A recognised, configured person is always allowed, and the alarm can only
    add denials, never remove Deny unknown speakers.
    """
    if speaker_known:
        return False
    return bool(entry.options.get(CONF_DENY_UNKNOWN, False)) or alarm_counts_as_armed(
        hass, entry
    )


def selected_apis(hass: HomeAssistant, entity_id: str) -> list[str] | None:
    """The LLM API ids selected on a conversation agent, or None if unreadable.

    Agents such as Anthropic keep this on a subentry; older ones on the entry.
    """
    reg_entry = er.async_get(hass).async_get(entity_id)
    if reg_entry is None or not reg_entry.config_entry_id:
        return None
    config_entry = hass.config_entries.async_get_entry(reg_entry.config_entry_id)
    if config_entry is None:
        return None
    sub = (
        config_entry.subentries.get(reg_entry.config_subentry_id)
        if reg_entry.config_subentry_id
        else None
    )
    data = sub.data if sub is not None else config_entry.options
    apis = data.get(CONF_LLM_HASS_API)
    if apis is None:
        return []
    return [apis] if isinstance(apis, str) else list(apis)


def wrapped_agent(entry: ConfigEntry) -> str:
    return str(entry.options.get(CONF_WRAPPED_AGENT, ""))

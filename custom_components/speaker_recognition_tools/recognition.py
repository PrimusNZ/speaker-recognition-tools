"""Read the recognition score for the current turn from Speaker Recognition.

Speaker Recognition only sets the Home Assistant user on each turn. Its score is
kept in its own decision history, which is internal to that integration and may
change in any release. Every read here is defensive: when the score cannot be
found, it is reported as unknown and nothing else changes.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

UPSTREAM_DOMAIN = "speaker_recognition"
_HISTORY_KEY = "decision_history"
_MAX_AGE = datetime.timedelta(minutes=2)
_RECENT = 10

_LOGGER = logging.getLogger(__name__)


def history_available(hass: HomeAssistant) -> bool:
    """Whether Speaker Recognition's decision history can be read."""
    history = hass.data.get(UPSTREAM_DOMAIN, {}).get(_HISTORY_KEY)
    return callable(getattr(history, "recent", None))


def _recent_records(hass: HomeAssistant) -> list[dict[str, Any]]:
    history = hass.data.get(UPSTREAM_DOMAIN, {}).get(_HISTORY_KEY)
    recent = getattr(history, "recent", None)
    if not callable(recent):
        return []
    try:
        records = recent(_RECENT)
    except Exception:  # an internal API of another integration
        _LOGGER.debug("Could not read Speaker Recognition history", exc_info=True)
        return []
    return (
        [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []
    )


def latest_confidence(
    hass: HomeAssistant, user_id: str | None, device_id: str | None
) -> float | None:
    """Return the score of the newest recent decision that identified this user.

    A decision from another satellite device is skipped when both are known.
    """
    if not user_id:
        return None
    now = dt_util.utcnow()
    registry = er.async_get(hass)
    for record in _recent_records(hass):
        if record.get("user_id") != user_id or not record.get("identity_eligible"):
            continue
        created = dt_util.parse_datetime(str(record.get("created_at", "")))
        if created is None or not now - _MAX_AGE <= created <= now + _MAX_AGE:
            continue
        satellite = record.get("satellite_id")
        if device_id and isinstance(satellite, str):
            entry = registry.async_get(satellite)
            if entry and entry.device_id and entry.device_id != device_id:
                continue
        confidence = record.get("confidence")
        if (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and 0.0 <= confidence <= 1.0
        ):
            return float(confidence)
        return None
    return None

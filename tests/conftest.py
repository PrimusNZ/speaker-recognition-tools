"""Load prompt.py directly so the tests do not need Home Assistant installed."""

import importlib.util
from pathlib import Path

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

_PROMPT = (
    Path(__file__).parent.parent
    / "custom_components"
    / "speaker_recognition_tools"
    / "prompt.py"
)


@pytest.fixture(scope="session")
def prompt():
    spec = importlib.util.spec_from_file_location("srt_prompt", _PROMPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components from this repo."""
    yield


@pytest.fixture(autouse=True)
def short_state_settle_timeout(monkeypatch):
    """Keep tests quick when a fake unit never reports a new state."""
    from custom_components.speaker_recognition_tools import entity_tools

    monkeypatch.setattr(entity_tools, "STATE_SETTLE_TIMEOUT", 0.05)

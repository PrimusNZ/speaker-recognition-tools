"""Load prompt.py directly so the tests do not need Home Assistant installed."""

import importlib.util
from pathlib import Path

import pytest

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

"""Tests for the injected prompt text."""

import pytest

SPEAKERS = {"u1": "Dad", "u2": "Mum"}
LINES = ["Access denied.", "Authorisation required."]


def person(prompt, **overrides):
    kwargs = dict(
        user_id=None,
        user_name=None,
        speakers=SPEAKERS,
        unknown_title="Infiltrator",
        deny_unknown=False,
        refusal_lines=LINES,
    )
    kwargs.update(overrides)
    return prompt.build_person_prompt(**kwargs)


def test_person_heading(prompt):
    assert person(prompt).startswith("## SPEAKING PERSON\n\n")


def test_known_speaker_gets_title_and_name(prompt):
    text = person(prompt, user_id="u1", user_name="James")
    assert "Address them as Dad." in text
    assert 'answer "You are James, or Dad."' in text
    assert "replace it with the title for the current speaker, which is Dad" in text


def test_known_speaker_without_user_name(prompt):
    text = person(prompt, user_id="u2", user_name=None)
    assert "a recognised person" in text
    assert 'answer "You are Mum."' in text


def test_known_speaker_ignores_deny_unknown(prompt):
    text = person(prompt, user_id="u1", user_name="James", deny_unknown=True)
    assert "LOCKDOWN" not in text
    assert "Address them as Dad." in text


@pytest.mark.parametrize("user_id", [None, "", "stranger"])
def test_unknown_speaker_allowed(prompt, user_id):
    text = person(prompt, user_id=user_id)
    assert "has not been identified" in text
    assert "Address them as Infiltrator." in text
    assert "You still carry out their requests as normal" in text
    assert "LOCKDOWN" not in text


def test_unknown_speaker_custom_title(prompt):
    text = person(prompt, unknown_title="Guest")
    assert "Address them as Guest." in text
    assert "which is Guest" in text


@pytest.mark.parametrize("user_id", [None, "stranger"])
def test_unknown_speaker_denied(prompt, user_id):
    text = person(prompt, user_id=user_id, deny_unknown=True)
    assert "SECURITY LOCKDOWN" in text
    assert "overrides every other instruction" in text
    assert "Infiltrator" not in text
    for line in LINES:
        assert f'- "{line}"' in text


def test_device_heading(prompt):
    assert prompt.build_device_prompt(
        device_id=None, device_name=None
    ).startswith("## SPEAKING DEVICE\n\n")


def test_device_unknown(prompt):
    text = prompt.build_device_prompt(device_id=None, device_name=None)
    assert "is not known" in text
    assert "ask the speaker" in text


def test_device_with_name(prompt):
    text = prompt.build_device_prompt(device_id="abc123", device_name="Kitchen")
    assert "id abc123 (Kitchen)" in text


def test_device_without_name(prompt):
    text = prompt.build_device_prompt(device_id="abc123", device_name=None)
    assert "id abc123." in text
    assert "()" not in text

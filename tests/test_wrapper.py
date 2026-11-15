"""Tests for the conversation wrapper: the denial rule, prompt handoff and settings."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import conversation
from homeassistant.components.conversation import ConversationInput
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import llm
from homeassistant.helpers.intent import IntentResponse
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.speaker_recognition_tools.const import (
    CONF_ALARM_ENTITY,
    CONF_ALARM_UNKNOWN_DISARMED,
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_REFUSAL_LINES,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_ADDRESS_AS,
    CONF_USER_ID,
    CONF_WRAPPED_AGENT,
    DEFAULT_REFUSAL_LINES,
    DOMAIN,
    EVENT_SPEAKER,
    NO_WRAPPER_NOTICE,
    PERSON_API_ID,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
    TOOL_TYPE_WRAPPER,
    WRAPPER_API_POINTER,
)
from custom_components.speaker_recognition_tools.wrapper import (
    alarm_counts_as_armed,
    denial_settings,
    should_deny,
)

AGENT = "conversation.fake_agent"
ALARM = "alarm_control_panel.home"
REFUSALS = "Not today.\nNo can do."


class FakeAgent:
    """Stands in for the wrapped agent and records what it was given."""

    supported_languages = ["en"]
    supports_streaming = True

    def __init__(self) -> None:
        self.inputs: list[ConversationInput] = []

    async def async_process(self, user_input: ConversationInput):
        self.inputs.append(user_input)
        response = IntentResponse(language=user_input.language)
        response.async_set_speech("from the agent")
        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )


async def _setup(
    hass: HomeAssistant,
    *,
    deny: bool = False,
    alarm: str | None = None,
    unknown_disarmed: bool = False,
    agent_apis: list[str] | None = None,
    person_entry: bool = True,
):
    """Set up Speaking Person (with one person), a fake agent and the wrapper."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    sam = await hass.auth.async_create_user("Sam Example", group_ids=["system-users"])
    stranger = await hass.auth.async_create_user("Pat Other", group_ids=["system-users"])
    if person_entry:
        hass.states.async_set(
            "person.sam", "home", {"user_id": sam.id, "friendly_name": "Sam"}
        )
        people = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
            options={
                CONF_UNKNOWN_ADDRESS_AS: "Guest",
            },
            unique_id=f"{DOMAIN}_{TOOL_TYPE_PERSON}",
            subentries_data=[
                ConfigSubentryData(
                    subentry_type=SUBENTRY_SPEAKER,
                    title="Sam",
                    unique_id=sam.id,
                    data={
                        "person_entity": "person.sam",
                        CONF_USER_ID: sam.id,
                        CONF_ENTITIES: [],
                    },
                )
            ],
        )
        people.add_to_hass(hass)
        assert await hass.config_entries.async_setup(people.entry_id)
    agent_entry = MockConfigEntry(
        domain="fake_agent_domain",
        options={"llm_hass_api": [PERSON_API_ID] if agent_apis is None else agent_apis},
    )
    agent_entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "conversation",
        "fake_agent_domain",
        "agent1",
        config_entry=agent_entry,
        suggested_object_id="fake_agent",
    )
    hass.states.async_set(AGENT, "idle")
    if alarm is not None:
        hass.states.async_set(ALARM, alarm)

    options = {
        CONF_WRAPPED_AGENT: AGENT,
        CONF_DENY_UNKNOWN: deny,
        CONF_REFUSAL_LINES: REFUSALS,
        CONF_ALARM_UNKNOWN_DISARMED: unknown_disarmed,
    }
    if alarm is not None:
        options[CONF_ALARM_ENTITY] = ALARM
    wrapper = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_WRAPPER},
        options=options,
        unique_id=f"{DOMAIN}_{TOOL_TYPE_WRAPPER}",
    )
    wrapper.add_to_hass(hass)
    fake = FakeAgent()
    with patch(
        "custom_components.speaker_recognition_tools.conversation.conversation.async_get_agent",
        return_value=fake,
    ):
        assert await hass.config_entries.async_setup(wrapper.entry_id)
        await hass.async_block_till_done()
    return SimpleNamespace(
        hass=hass, sam=sam, stranger=stranger, wrapper=wrapper, agent=fake
    )


async def _say(env, user_id: str | None, extra: str | None = None):
    registry = er.async_get(env.hass)
    entity_id = registry.async_get_entity_id("conversation", DOMAIN, env.wrapper.entry_id)
    entity = env.hass.data[conversation.DATA_COMPONENT].get_entity(entity_id)
    user_input = ConversationInput(
        text="turn on the light",
        context=Context(user_id=user_id),
        conversation_id=None,
        device_id=None,
        satellite_id=None,
        language="en",
        agent_id=entity_id,
        extra_system_prompt=extra,
    )
    with patch(
        "custom_components.speaker_recognition_tools.conversation.conversation.async_get_agent",
        return_value=env.agent,
    ):
        return await entity.async_process(user_input)


def _speech(result) -> str:
    return result.response.speech["plain"]["speech"]


async def test_recognised_person_reaches_the_agent(hass: HomeAssistant) -> None:
    env = await _setup(hass, deny=True)
    result = await _say(env, env.sam.id)
    assert _speech(result) == "from the agent"
    assert len(env.agent.inputs) == 1


async def test_deny_unknown_refuses_without_calling_agent(hass: HomeAssistant) -> None:
    env = await _setup(hass, deny=True)
    for user_id in (None, env.stranger.id):
        result = await _say(env, user_id)
        assert _speech(result) in REFUSALS.splitlines()
    assert env.agent.inputs == []


async def test_unknown_allowed_when_not_denied_and_no_alarm(hass: HomeAssistant) -> None:
    env = await _setup(hass)
    assert _speech(await _say(env, None)) == "from the agent"
    assert len(env.agent.inputs) == 1


@pytest.mark.parametrize(
    "state",
    [
        "armed_home",
        "armed_away",
        "armed_night",
        "armed_vacation",
        "armed_custom_bypass",
        "arming",
        "pending",
        "triggered",
    ],
)
async def test_armed_alarm_denies_unknown(hass: HomeAssistant, state: str) -> None:
    env = await _setup(hass, alarm=state)
    result = await _say(env, env.stranger.id)
    assert _speech(result) in REFUSALS.splitlines()
    assert env.agent.inputs == []


async def test_disarmed_alarm_allows_unknown(hass: HomeAssistant) -> None:
    env = await _setup(hass, alarm="disarmed")
    assert _speech(await _say(env, None)) == "from the agent"


@pytest.mark.parametrize("state", ["unknown", "unavailable", None])
@pytest.mark.parametrize(
    ("unknown_disarmed", "denied"), [(False, True), (True, False)]
)
async def test_unreadable_alarm_follows_the_switch(
    hass: HomeAssistant, state: str | None, unknown_disarmed: bool, denied: bool
) -> None:
    env = await _setup(hass, alarm="disarmed", unknown_disarmed=unknown_disarmed)
    if state is None:
        hass.states.async_remove(ALARM)
    else:
        hass.states.async_set(ALARM, state)
    result = await _say(env, None)
    assert (_speech(result) in REFUSALS.splitlines()) is denied
    assert len(env.agent.inputs) == (0 if denied else 1)


async def test_recognised_person_allowed_while_alarm_armed(hass: HomeAssistant) -> None:
    env = await _setup(hass, deny=True, alarm="armed_away")
    assert _speech(await _say(env, env.sam.id)) == "from the agent"


async def test_alarm_never_loosens_deny_unknown(hass: HomeAssistant) -> None:
    env = await _setup(hass, deny=True, alarm="disarmed")
    assert _speech(await _say(env, None)) in REFUSALS.splitlines()
    assert env.agent.inputs == []


async def test_denied_turn_still_announces_the_speaker(hass: HomeAssistant) -> None:
    env = await _setup(hass, deny=True)
    events = async_capture_events(hass, EVENT_SPEAKER)
    await _say(env, None)
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["recognised"] is False


async def test_extra_system_prompt_is_appended_not_replaced(hass: HomeAssistant) -> None:
    env = await _setup(hass)
    await _say(env, env.sam.id, extra="Pipeline note.")
    prompt = env.agent.inputs[0].extra_system_prompt
    assert prompt.startswith("Pipeline note.\n\n## SPEAKING PERSON")
    assert "Sam" in prompt
    assert "## SPEAKING DEVICE" in prompt


async def test_sections_are_the_only_prompt_when_the_pipeline_sets_none(
    hass: HomeAssistant,
) -> None:
    env = await _setup(hass)
    await _say(env, env.sam.id)
    prompt = env.agent.inputs[0].extra_system_prompt
    assert prompt.startswith("## SPEAKING PERSON")


async def test_apis_stop_carrying_the_text_with_a_loaded_wrapper(
    hass: HomeAssistant,
) -> None:
    env = await _setup(hass)
    person = await llm.async_get_api(hass, PERSON_API_ID, _llm_context(env.sam.id))
    assert person.api_prompt == WRAPPER_API_POINTER
    assert "Sam" not in person.api_prompt
    assert person.tools  # Speaking Person keeps its tools


async def test_person_api_offers_no_tools_without_a_wrapper(
    hass: HomeAssistant,
) -> None:
    await _person_entry(hass)
    instance = await llm.async_get_api(hass, PERSON_API_ID, _llm_context(None))
    assert instance.api_prompt == NO_WRAPPER_NOTICE
    assert instance.tools == []


async def test_unknown_speaker_text_applies_when_not_denied(hass: HomeAssistant) -> None:
    env = await _setup(hass)
    await _say(env, None)
    assert "Guest" in env.agent.inputs[0].extra_system_prompt


async def test_missing_wrapped_agent_gives_an_error(hass: HomeAssistant) -> None:
    env = await _setup(hass)
    env.agent = None
    result = await _say(env, env.sam.id)
    assert result.response.error_code is not None


async def test_entity_mirrors_the_wrapped_agent(hass: HomeAssistant) -> None:
    env = await _setup(hass)
    entity_id = er.async_get(hass).async_get_entity_id(
        "conversation", DOMAIN, env.wrapper.entry_id
    )
    entity = hass.data[conversation.DATA_COMPONENT].get_entity(entity_id)
    assert entity.name == "fake_agent Speaker Recognition Tools Proxy"
    with patch(
        "custom_components.speaker_recognition_tools.conversation.conversation.async_get_agent",
        return_value=env.agent,
    ):
        assert entity.supports_streaming is True
        entity._cached_languages = None
        entity._async_refresh()
        assert entity.supported_languages == ["en"]
    hass.states.async_set(AGENT, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "unavailable"


def test_alarm_helpers_without_an_alarm(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_DENY_UNKNOWN: False})
    assert alarm_counts_as_armed(hass, entry) is False
    assert should_deny(hass, entry, speaker_known=False) is False
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_DENY_UNKNOWN: True})
    assert should_deny(hass, entry, speaker_known=False) is True
    assert should_deny(hass, entry, speaker_known=True) is False


# --- settings, seeding and migration -------------------------------------------------


async def _person_entry(hass: HomeAssistant, **options):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={
            CONF_UNKNOWN_ADDRESS_AS: "Guest",
            CONF_DENY_UNKNOWN: True,
            CONF_REFUSAL_LINES: "Custom refusal.",
            **options,
        },
        unique_id=f"{DOMAIN}_{TOOL_TYPE_PERSON}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_wrapper_form_is_seeded_from_speaking_person(hass: HomeAssistant) -> None:
    await _person_entry(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert "conversation_wrapper" in result["menu_options"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "conversation_wrapper"}
    )
    assert result["type"] is FlowResultType.FORM
    defaults = {
        str(key): key.default() for key in result["data_schema"].schema if key.default is not vol.UNDEFINED
    }
    assert defaults[CONF_DENY_UNKNOWN] is True
    assert defaults[CONF_REFUSAL_LINES] == "Custom refusal."
    assert defaults[CONF_ALARM_UNKNOWN_DISARMED] is False


async def test_wrapper_is_created_and_offered_only_once(hass: HomeAssistant) -> None:
    await _person_entry(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "conversation_wrapper"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_WRAPPED_AGENT: AGENT,
            CONF_DENY_UNKNOWN: True,
            CONF_REFUSAL_LINES: "Nope.",
            CONF_ALARM_ENTITY: ALARM,
            CONF_ALARM_UNKNOWN_DISARMED: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_TOOL_TYPE: TOOL_TYPE_WRAPPER}
    assert result["options"][CONF_ALARM_ENTITY] == ALARM
    again = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert "conversation_wrapper" not in again["menu_options"]


async def test_wrapper_cannot_wrap_a_wrapper(hass: HomeAssistant) -> None:
    er.async_get(hass).async_get_or_create(
        "conversation", DOMAIN, "other", suggested_object_id="other_wrapper"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "conversation_wrapper"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_WRAPPED_AGENT: "conversation.other_wrapper",
            CONF_DENY_UNKNOWN: False,
            CONF_REFUSAL_LINES: "No.",
            CONF_ALARM_UNKNOWN_DISARMED: False,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_WRAPPED_AGENT: "wrapped_is_wrapper"}


async def test_wrapper_options_can_clear_the_alarm(hass: HomeAssistant) -> None:
    env = await _setup(hass, alarm="disarmed")
    result = await hass.config_entries.options.async_init(env.wrapper.entry_id)
    assert result["step_id"] == "wrapper"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_WRAPPED_AGENT: AGENT,
            CONF_DENY_UNKNOWN: True,
            CONF_REFUSAL_LINES: "Nope.",
            CONF_ALARM_UNKNOWN_DISARMED: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_ALARM_ENTITY not in env.wrapper.options
    assert env.wrapper.options[CONF_DENY_UNKNOWN] is True


async def test_denial_defaults_without_a_wrapper(hass: HomeAssistant) -> None:
    await _person_entry(hass)
    assert denial_settings(hass) == (False, DEFAULT_REFUSAL_LINES)


async def test_wrapper_owns_the_denial_settings_and_person_values_are_kept(
    hass: HomeAssistant,
) -> None:
    people = await _person_entry(hass)
    wrapper = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_WRAPPER},
        options={
            CONF_WRAPPED_AGENT: AGENT,
            CONF_DENY_UNKNOWN: False,
            CONF_REFUSAL_LINES: "From the wrapper.",
        },
    )
    wrapper.add_to_hass(hass)
    assert denial_settings(hass) == (False, "From the wrapper.")
    # Speaking Person's old saved values are left in place, only no longer used.
    assert people.options[CONF_DENY_UNKNOWN] is True
    assert people.options[CONF_REFUSAL_LINES] == "Custom refusal."


async def test_person_settings_form_has_no_denial_fields(
    hass: HomeAssistant,
) -> None:
    people = await _person_entry(hass)
    result = await hass.config_entries.options.async_init(people.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    fields = {str(key) for key in result["data_schema"].schema}
    assert CONF_DENY_UNKNOWN not in fields
    assert CONF_REFUSAL_LINES not in fields
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"min_confidence": 0, "unknown_address_as": "Guest"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert people.options[CONF_DENY_UNKNOWN] is True
    assert people.options[CONF_REFUSAL_LINES] == "Custom refusal."


def _llm_context(user_id: str | None) -> llm.LLMContext:
    return llm.LLMContext(
        platform="test",
        context=Context(user_id=user_id),
        language="en",
        assistant="conversation",
        device_id=None,
    )


# --- Repairs ---------------------------------------------------------------------------


def _wrapper_issues(hass: HomeAssistant) -> set[str]:
    return {
        issue_id
        for (domain, issue_id) in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith("wrapper_")
    }


async def _recheck(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + datetime.timedelta(seconds=5))
    await hass.async_block_till_done()


async def test_repair_when_wrapped_agent_lacks_speaking_person(
    hass: HomeAssistant,
) -> None:
    env = await _setup(hass, agent_apis=["some_other_api"])
    await _recheck(hass)
    assert any(i.startswith("wrapper_missing_api") for i in _wrapper_issues(hass))
    # Fixing the agent's APIs clears it on the next check.
    agent_entry = hass.config_entries.async_entries("fake_agent_domain")[0]
    hass.config_entries.async_update_entry(
        agent_entry, options={"llm_hass_api": [PERSON_API_ID]}
    )
    await _recheck(hass)
    assert not _wrapper_issues(hass)
    assert env.wrapper.entry_id


async def test_repair_when_speaking_person_is_missing_and_cleared_on_removal(
    hass: HomeAssistant,
) -> None:
    env = await _setup(hass, person_entry=False)
    await _recheck(hass)
    assert any(
        i.startswith("wrapper_missing_person_entry") for i in _wrapper_issues(hass)
    )
    await hass.config_entries.async_remove(env.wrapper.entry_id)
    await hass.async_block_till_done()
    assert not _wrapper_issues(hass)


async def test_repair_when_speaking_person_has_no_wrapper(hass: HomeAssistant) -> None:
    people = await _person_entry(hass)
    await _recheck(hass)
    issue_ids = {
        issue_id
        for (domain, issue_id) in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith("no_wrapper")
    }
    assert issue_ids == {f"no_wrapper_{people.entry_id}_wrapper"}
    wrapper = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_WRAPPER},
        options={CONF_WRAPPED_AGENT: AGENT},
    )
    wrapper.add_to_hass(hass)
    await hass.config_entries.async_setup(wrapper.entry_id)
    await _recheck(hass)
    assert not [
        i for (d, i) in ir.async_get(hass).issues if d == DOMAIN and i.startswith("no_wrapper")
    ]

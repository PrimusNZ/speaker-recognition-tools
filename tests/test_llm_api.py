"""End-to-end tests of the injected prompt through the registered LLM APIs."""

from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_ADDRESS_AS,
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_ENTITY_ALIASES,
    CONF_LEGACY_ADDRESS_AS,
    CONF_LEGACY_UNKNOWN_ADDRESS_AS,
    CONF_LINK_ACTION_ENTITY,
    CONF_LINK_ALIASES,
    CONF_LINK_NAME,
    CONF_LINK_PRIVATE,
    CONF_LINK_STATE_ENTITY,
    CONF_REFUSAL_LINES,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_ADDRESS_AS,
    CONF_USER_ID,
    CONF_WRAPPED_AGENT,
    DOMAIN,
    NO_WRAPPER_NOTICE,
    PERSON_API_ID,
    PERSON_API_NAME,
    SUBENTRY_ENTITY_LINK,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
    TOOL_TYPE_WRAPPER,
    WRAPPER_API_POINTER,
)
from custom_components.speaker_recognition_tools.llm_api import (
    async_person_prompt,
    device_prompt,
)
from custom_components.speaker_recognition_tools.people import (
    async_configured_people,
)
from custom_components.speaker_recognition_tools.wrapper import (
    person_entry,
    wrapper_entry,
)


async def _setup(
    hass: HomeAssistant,
    deny: bool = False,
    linked: bool = False,
    admin_users: tuple[str, ...] = (),
    wrapper: bool = True,
):
    james = await hass.auth.async_create_user(
        "James",
        group_ids=["system-admin" if "James" in admin_users else "system-users"],
    )
    sarah = await hass.auth.async_create_user(
        "Sarah",
        group_ids=["system-admin" if "Sarah" in admin_users else "system-users"],
    )
    hass.states.async_set("calendar.james", "off", {"friendly_name": "James Calendar"})
    hass.states.async_set("calendar.sarah", "off", {"friendly_name": "Sarah Calendar"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={
            CONF_UNKNOWN_ADDRESS_AS: "Unknown Person",
        },
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="James: Dad",
                unique_id=james.id,
                data={
                    CONF_USER_ID: james.id,
                    CONF_ADDRESS_AS: "Dad",
                    CONF_ENTITIES: ["calendar.james"],
                },
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Sarah: Mum",
                unique_id=sarah.id,
                data={
                    CONF_USER_ID: sarah.id,
                    CONF_ADDRESS_AS: "Mum",
                    CONF_ENTITIES: ["calendar.sarah", "calendar.gone"],
                },
            ),
        ]
        + (
            [
                ConfigSubentryData(
                    subentry_type=SUBENTRY_ENTITY_LINK,
                    title="Demo unit (James)",
                    data={
                        CONF_USER_ID: james.id,
                        CONF_LINK_NAME: "Demo unit",
                        CONF_LINK_ALIASES: ["Lab station", "Test console"],
                        CONF_LINK_STATE_ENTITY: "binary_sensor.demo_unit_status",
                        CONF_LINK_ACTION_ENTITY: "button.demo_unit_action",
                        CONF_LINK_PRIVATE: False,
                    },
                )
            ]
            if linked
            else []
        ),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    if wrapper:
        await _add_wrapper(hass, deny)
    return james


async def _instance(
    hass: HomeAssistant,
    user_id: str | None,
    api_id: str = PERSON_API_ID,
    device_id: str | None = None,
) -> llm.APIInstance:
    context = llm.LLMContext(
        platform="test",
        context=Context(user_id=user_id),
        language="en",
        assistant="conversation",
        device_id=device_id,
    )
    return await llm.async_get_api(hass, api_id, context)


async def _prompt(hass: HomeAssistant, user_id: str | None) -> str:
    """The SPEAKING PERSON text, which the wrapper appends to the prompt."""
    entry = person_entry(hass)
    people = await async_configured_people(hass, entry)
    return await async_person_prompt(hass, entry, user_id, people)


async def _add_wrapper(
    hass: HomeAssistant, deny: bool = False, lines: str = "No."
) -> MockConfigEntry:
    """A loaded wrapper, which owns the denial settings and enables the tools."""
    wrapper = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_WRAPPER},
        options={
            CONF_WRAPPED_AGENT: "conversation.agent",
            CONF_DENY_UNKNOWN: deny,
            CONF_REFUSAL_LINES: lines,
        },
    )
    wrapper.add_to_hass(hass)
    wrapper.mock_state(hass, ConfigEntryState.LOADED)
    return wrapper


async def test_prompt_assigns_entities_to_each_person(hass: HomeAssistant) -> None:
    james = await _setup(hass)
    text = await _prompt(hass, james.id)
    assert (
        'answer exactly "Your form of address is Dad, and your name is James."' in text
    )
    assert "## ENTITY MAPPINGS" in text
    assert "### James (Dad) [current speaker]" in text
    assert "User Level: User" in text
    assert " - calendar.james: James Calendar" in text
    assert "### Sarah (Mum)" in text
    assert " - calendar.sarah: Sarah Calendar" in text
    assert " - calendar.gone" in text


async def test_prompt_includes_user_level_for_configured_speakers(
    hass: HomeAssistant,
) -> None:
    james = await _setup(hass, admin_users=("James",))

    text = await _prompt(hass, james.id)

    james_block = text.split("### James (Dad) [current speaker]", 1)[1].split(
        "\n\n### ", 1
    )[0]
    sarah_block = text.split("### Sarah (Mum)", 1)[1].split("\n\n### ", 1)[0]
    assert "User Level: Administrator" in james_block
    assert "User Level: User" in sarah_block

    unknown_text = await _prompt(hass, None)
    assert "User Level:" not in unknown_text


async def test_linked_device_is_injected_with_shared_status_and_action_name(
    hass: HomeAssistant,
) -> None:
    james = await _setup(hass, linked=True)
    text = await _prompt(hass, james.id)
    assert (
        "Linked devices:\n- Demo unit\n  - Aliases: Lab station, Test console\n  - Status entity: binary_sensor.demo_unit_status\n  - Action entity: button.demo_unit_action"
        in text
    )


async def test_legacy_address_as_settings_remain_supported(hass: HomeAssistant) -> None:
    james = await hass.auth.async_create_user("James", group_ids=["system-users"])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={CONF_LEGACY_UNKNOWN_ADDRESS_AS: "Guest"},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="James: Dad",
                unique_id=james.id,
                data={
                    CONF_USER_ID: james.id,
                    CONF_LEGACY_ADDRESS_AS: "Dad",
                    CONF_ENTITIES: [],
                },
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert "Address them as Dad." in await _prompt(hass, james.id)
    assert "Address them as Guest." in await _prompt(hass, None)


async def test_assigned_entity_aliases_reach_live_prompt(hass: HomeAssistant) -> None:
    james = await hass.auth.async_create_user("James", group_ids=["system-users"])
    hass.states.async_set("calendar.james", "off", {"friendly_name": "James Calendar"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="James",
                unique_id=james.id,
                data={
                    CONF_USER_ID: james.id,
                    CONF_ADDRESS_AS: "Dad",
                    CONF_ENTITIES: ["calendar.james"],
                    CONF_ENTITY_ALIASES: {
                        "calendar.james": ["work calendar", "appointments"]
                    },
                },
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    text = await _prompt(hass, james.id)
    assert "calendar.james: work calendar (other aliases: appointments)" in text
    assert "James Calendar" not in text


async def test_prompt_unknown_speaker_sees_people(hass: HomeAssistant) -> None:
    await _setup(hass)
    text = await _prompt(hass, None)
    assert "Address them as Unknown Person." in text
    assert "ENTITY MAPPINGS" not in text
    assert "calendar." not in text
    assert " - James (Dad)\n - Sarah (Mum)" in text


async def test_prompt_denied_speaker_sees_nothing(hass: HomeAssistant) -> None:
    await _setup(hass, deny=True)
    text = await _prompt(hass, None)
    assert "SECURITY LOCKDOWN" in text
    assert "calendar." not in text
    assert "Sarah" not in text


async def test_missing_address_as_falls_back_to_first_name(hass: HomeAssistant) -> None:
    tom = await hass.auth.async_create_user("Tom Jones", group_ids=["system-users"])
    ghost = await hass.auth.async_create_user("Ann", group_ids=["system-users"])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={CONF_UNKNOWN_ADDRESS_AS: "Unknown Person"},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Tom Jones",
                unique_id=tom.id,
                data={CONF_USER_ID: tom.id, CONF_ADDRESS_AS: "", CONF_ENTITIES: []},
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Ann: Aunt",
                unique_id=ghost.id,
                data={CONF_USER_ID: ghost.id, CONF_ADDRESS_AS: "Aunt"},
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    text = await _prompt(hass, tom.id)
    assert "Address them as Tom." in text
    assert 'answer exactly "Your name is Tom."' in text
    assert "Jones" not in text
    assert "### Tom [current speaker]" in text
    assert "### Ann (Aunt)" in text
    unknown = await _prompt(hass, None)
    assert " - Ann (Aunt)\n - Tom" in unknown
    assert "Jones" not in unknown


async def test_only_first_names_reach_the_prompt(hass: HomeAssistant) -> None:
    james = await hass.auth.async_create_user("James Smith", group_ids=["system-users"])
    sarah = await hass.auth.async_create_user(
        "Sarah Anne Jones", group_ids=["system-users"]
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={CONF_UNKNOWN_ADDRESS_AS: "Unknown Person"},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="James Smith: Dad",
                unique_id=james.id,
                data={
                    CONF_USER_ID: james.id,
                    CONF_ADDRESS_AS: "Dad",
                    CONF_ENTITIES: [],
                },
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_SPEAKER,
                title="Sarah Anne Jones: Mum",
                unique_id=sarah.id,
                data={
                    CONF_USER_ID: sarah.id,
                    CONF_ADDRESS_AS: "Mum",
                    CONF_ENTITIES: [],
                },
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for user_id in (james.id, sarah.id, None):
        text = await _prompt(hass, user_id)
        assert "Smith" not in text and "Jones" not in text and "Anne" not in text
    assert (
        'answer exactly "Your form of address is Dad, and your name is James."'
        in await _prompt(hass, james.id)
    )
    assert "### Sarah (Mum)" in await _prompt(hass, james.id)


async def test_person_api_tools_only_for_recognised_speakers(
    hass: HomeAssistant,
) -> None:
    james = await _setup(hass)
    instance = await _instance(hass, james.id)
    assert [t.name for t in instance.tools] == [
        "get_entity_state",
        "control_assigned_entity",
        "get_calendar_events",
        "search_calendar_events",
        "check_calendar_availability",
        "create_calendar_event",
        "update_calendar_event",
        "delete_calendar_event",
        "get_person_location",
        "get_person_location_history",
        "get_device_location",
        "get_todo_items",
        "add_todo_item",
        "update_todo_item",
        "remove_todo_item",
        "send_message_to_person",
    ]
    assert (await _instance(hass, None)).tools == []
    assert (await _instance(hass, "no-such-user")).tools == []
    assert instance.api.name == PERSON_API_NAME
    assert any(a.id == PERSON_API_ID for a in llm.async_get_apis(hass))


async def test_person_api_reads_options_live(hass: HomeAssistant) -> None:
    await _setup(hass)
    assert "SECURITY LOCKDOWN" not in await _prompt(hass, None)
    entry = wrapper_entry(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_DENY_UNKNOWN: True, CONF_REFUSAL_LINES: "Nope."},
    )
    text = await _prompt(hass, None)
    assert "SECURITY LOCKDOWN" in text
    assert '- "Nope."' in text


async def test_denied_speaker_gets_no_tools(hass: HomeAssistant) -> None:
    await _setup(hass, deny=True)
    stranger = await hass.auth.async_create_user("Eve", group_ids=["system-users"])
    assert (await _instance(hass, None)).tools == []
    assert (await _instance(hass, stranger.id)).tools == []


async def test_person_api_denies_user_who_is_not_listed(hass: HomeAssistant) -> None:
    await _setup(hass, deny=True)
    stranger = await hass.auth.async_create_user("Eve", group_ids=["system-users"])
    text = await _prompt(hass, stranger.id)
    assert "SECURITY LOCKDOWN" in text
    assert "Eve" not in text


async def test_person_api_default_refusal_lines_when_blank(hass: HomeAssistant) -> None:
    await _setup(hass, deny=True)
    entry = wrapper_entry(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_REFUSAL_LINES: " \n \n"}
    )
    expected_lines = [
        "That request cannot be completed.",
        "I'm unable to perform that action.",
        "That action is not permitted.",
        "I'm unable to proceed with that request.",
        "That operation is restricted.",
        "I cannot carry out that instruction.",
        "That request cannot be fulfilled.",
        "I'm unable to make that change.",
        "That action is not available.",
        "I cannot assist with that request.",
        "That operation cannot be performed.",
        "I'm unable to execute that command.",
        "That request is not permitted.",
        "I cannot proceed with that action.",
        "Access to that function is restricted.",
        "I'm unable to fulfil that instruction.",
        "That action cannot be authorised.",
        "I cannot provide access to that function.",
        "That command cannot be executed.",
        "I'm unable to comply with that request.",
    ]
    rendered_lines = "\n".join(f'- "{line}"' for line in expected_lines)
    assert rendered_lines in await _prompt(hass, None)


async def test_person_api_ignores_unknown_user_id(hass: HomeAssistant) -> None:
    await _setup(hass)
    text = await _prompt(hass, "no-such-user-id")
    assert "Address them as Unknown Person." in text


async def _device_text(hass: HomeAssistant, device_id: str | None) -> str:
    return device_prompt(hass, device_id)


async def test_device_text_without_device(hass: HomeAssistant) -> None:
    text = await _device_text(hass, None)
    assert text.startswith("## SPEAKING DEVICE")
    assert "is not known" in text


async def test_device_text_with_unregistered_device_id(hass: HomeAssistant) -> None:
    assert "id abc123." in await _device_text(hass, "abc123")


async def test_device_text_with_registered_device(hass: HomeAssistant) -> None:
    other = MockConfigEntry(domain="test")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("test", "kitchen")},
        name="Kitchen Satellite",
    )
    assert f"id {device.id} (Kitchen Satellite)" in await _device_text(hass, device.id)


async def test_device_text_includes_the_devices_area(hass: HomeAssistant) -> None:
    other = MockConfigEntry(domain="test")
    other.add_to_hass(hass)
    area = ar.async_get(hass).async_create("Lounge")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("test", "sat")},
        name="Lounge Satellite",
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    text = await _device_text(hass, device.id)
    assert f"id {device.id} (Lounge Satellite)" in text
    assert 'so "here" and "this room" mean the Lounge.' in text


async def test_device_text_without_an_area(hass: HomeAssistant) -> None:
    other = MockConfigEntry(domain="test")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("test", "x")}, name="Box"
    )
    assert "area" not in await _device_text(hass, device.id)


async def test_person_api_offers_nothing_without_a_wrapper(hass: HomeAssistant) -> None:
    james = await _setup(hass, wrapper=False)
    instance = await _instance(hass, james.id)
    assert instance.tools == []
    assert instance.api_prompt == NO_WRAPPER_NOTICE


async def test_person_api_prompt_is_only_a_pointer_with_a_wrapper(
    hass: HomeAssistant,
) -> None:
    james = await _setup(hass)
    instance = await _instance(hass, james.id)
    assert instance.api_prompt == WRAPPER_API_POINTER
    assert instance.tools


async def test_speaking_device_api_no_longer_exists(hass: HomeAssistant) -> None:
    await _setup(hass)
    assert {a.id for a in llm.async_get_apis(hass)} == {PERSON_API_ID}

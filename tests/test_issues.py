"""Tests for Repairs issues and following entity renames."""

from __future__ import annotations

import datetime

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.speaker_recognition_tools.const import (
    CONF_ENTITIES,
    CONF_ENTITY_ALIASES,
    CONF_LINK_ACTION_ENTITY,
    CONF_LINK_NAME,
    CONF_LINK_STATE_ENTITY,
    CONF_PRIVATE_ENTITIES,
    CONF_TOOL_TYPE,
    CONF_USER_ID,
    DOMAIN,
    SUBENTRY_ENTITY_LINK,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
)


async def _setup(hass: HomeAssistant, user_id: str, entities: list[str], **extra):
    subentries = [
        ConfigSubentryData(
            subentry_type=SUBENTRY_SPEAKER,
            title="Sam",
            unique_id=user_id,
            data={CONF_USER_ID: user_id, CONF_ENTITIES: entities, **extra},
        ),
        ConfigSubentryData(
            subentry_type=SUBENTRY_ENTITY_LINK,
            title="Demo unit",
            unique_id=None,
            data={
                CONF_USER_ID: user_id,
                CONF_LINK_NAME: "Demo unit",
                CONF_LINK_STATE_ENTITY: "binary_sensor.demo_status",
                CONF_LINK_ACTION_ENTITY: "button.demo_action",
            },
        ),
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        subentries_data=subentries,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _recheck(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + datetime.timedelta(seconds=5))
    await hass.async_block_till_done()


def _our_issues(hass: HomeAssistant) -> dict[str, ir.IssueEntry]:
    return {
        issue_id: issue
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN
    }


def _subentry(entry, subentry_type: str):
    return next(
        s for s in entry.subentries.values() if s.subentry_type == subentry_type
    )


async def test_missing_entities_raise_one_issue_per_person(hass: HomeAssistant):
    user = await hass.auth.async_create_user("Sam Sample")
    hass.states.async_set("binary_sensor.demo_status", "off")
    hass.states.async_set("button.demo_action", "unknown")
    hass.states.async_set("sensor.present", "1")
    await _setup(hass, user.id, ["sensor.present", "sensor.gone", "calendar.gone"])

    issues = _our_issues(hass)
    assert len(issues) == 1
    (issue,) = issues.values()
    assert issue.translation_key == "stale_entities"
    assert issue.translation_placeholders == {
        "name": "Sam",
        "entities": "calendar.gone, sensor.gone",
    }


async def test_issue_clears_when_the_entity_returns(hass: HomeAssistant):
    user = await hass.auth.async_create_user("Sam Sample")
    hass.states.async_set("binary_sensor.demo_status", "off")
    hass.states.async_set("button.demo_action", "unknown")
    await _setup(hass, user.id, ["sensor.later"])
    assert _our_issues(hass)

    er.async_get(hass).async_get_or_create("sensor", "test", "later_1")
    hass.states.async_set("sensor.later", "1")
    await _recheck(hass)
    assert not _our_issues(hass)


async def test_unavailable_registered_entity_is_not_reported(hass: HomeAssistant):
    user = await hass.auth.async_create_user("Sam Sample")
    registry = er.async_get(hass)
    for domain, uid in (
        ("sensor", "offline"),
        ("binary_sensor", "demo_status"),
        ("button", "demo_action"),
    ):
        registry.async_get_or_create(domain, "test", uid, suggested_object_id=uid)
    await _setup(hass, user.id, ["sensor.offline"])
    assert not _our_issues(hass)


async def test_linked_device_entities_are_checked(hass: HomeAssistant):
    user = await hass.auth.async_create_user("Sam Sample")
    hass.states.async_set("binary_sensor.demo_status", "off")
    await _setup(hass, user.id, [])
    (issue,) = _our_issues(hass).values()
    assert issue.translation_placeholders == {
        "name": "Demo unit",
        "entities": "button.demo_action",
    }


async def test_deleted_account_raises_an_issue(hass: HomeAssistant):
    await hass.auth.async_create_user("Owner Account")  # the first user is the owner
    user = await hass.auth.async_create_user("Sam Sample")
    hass.states.async_set("binary_sensor.demo_status", "off")
    hass.states.async_set("button.demo_action", "unknown")
    await _setup(hass, user.id, [])
    assert not _our_issues(hass)

    await hass.auth.async_remove_user(user)
    await _recheck(hass)
    (issue,) = _our_issues(hass).values()
    assert issue.translation_key == "missing_account"
    assert issue.translation_placeholders == {"name": "Sam"}


async def test_renamed_entity_is_followed_in_every_setting(hass: HomeAssistant):
    user = await hass.auth.async_create_user("Sam Sample")
    registry = er.async_get(hass)
    sensor = registry.async_get_or_create(
        "sensor", "test", "fuel", suggested_object_id="old_fuel"
    )
    action = registry.async_get_or_create(
        "button", "test", "act", suggested_object_id="demo_action"
    )
    registry.async_get_or_create(
        "binary_sensor", "test", "status", suggested_object_id="demo_status"
    )
    entry = await _setup(
        hass,
        user.id,
        [sensor.entity_id, "sensor.other"],
        **{
            CONF_PRIVATE_ENTITIES: [sensor.entity_id],
            CONF_ENTITY_ALIASES: {sensor.entity_id: ["Tank"]},
        },
    )
    hass.states.async_set("sensor.other", "1")

    registry.async_update_entity(sensor.entity_id, new_entity_id="sensor.new_fuel")
    registry.async_update_entity(action.entity_id, new_entity_id="button.new_action")
    await _recheck(hass)

    person = _subentry(entry, SUBENTRY_SPEAKER).data
    assert person[CONF_ENTITIES] == ["sensor.new_fuel", "sensor.other"]
    assert person[CONF_PRIVATE_ENTITIES] == ["sensor.new_fuel"]
    assert person[CONF_ENTITY_ALIASES] == {"sensor.new_fuel": ["Tank"]}
    link = _subentry(entry, SUBENTRY_ENTITY_LINK).data
    assert link[CONF_LINK_ACTION_ENTITY] == "button.new_action"
    assert not _our_issues(hass)


async def test_removing_the_entry_clears_its_issues(hass: HomeAssistant):
    user = await hass.auth.async_create_user("Sam Sample")
    entry = await _setup(hass, user.id, ["sensor.gone"])
    assert _our_issues(hass)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert not _our_issues(hass)

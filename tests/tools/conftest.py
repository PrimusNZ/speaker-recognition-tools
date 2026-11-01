"""Fixtures for the tool tests."""

from __future__ import annotations

import datetime

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speaker_recognition_tools.const import (
    CONF_ADDRESS_AS,
    CONF_DENY_UNKNOWN,
    CONF_ENTITIES,
    CONF_PRIVATE_ENTITIES,
    CONF_TOOL_TYPE,
    CONF_UNKNOWN_ADDRESS_AS,
    CONF_USER_ID,
    DOMAIN,
    SUBENTRY_SPEAKER,
    TOOL_TYPE_PERSON,
)
from tests.tools.helpers import (
    PEOPLE,
    Calendars,
)


@pytest.fixture
async def calendars(hass: HomeAssistant) -> Calendars:
    fake = Calendars()

    async def get_events(call: ServiceCall):
        entity_id = call.data["entity_id"]
        fake.reads.append(dict(call.data))
        if entity_id in fake.fail_on:
            raise HomeAssistantError("calendar offline")
        return {entity_id: {"events": [{"summary": f"event on {entity_id}"}]}}

    async def create_event(call: ServiceCall) -> None:
        if call.data["entity_id"] in fake.fail_on:
            raise HomeAssistantError("calendar is read only")
        fake.creates.append(dict(call.data))

    hass.services.async_register(
        "calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register("calendar", "create_event", create_event)
    return fake


@pytest.fixture
async def users(hass: HomeAssistant, calendars: Calendars):
    accounts = {
        name: await hass.auth.async_create_user(name, group_ids=["system-users"])
        for name in PEOPLE
    }
    subentries = [
        ConfigSubentryData(
            subentry_type=SUBENTRY_SPEAKER,
            title=name,
            unique_id=accounts[name].id,
            data={
                CONF_USER_ID: accounts[name].id,
                CONF_ADDRESS_AS: address_as,
                CONF_ENTITIES: entities,
                CONF_PRIVATE_ENTITIES: private,
            },
        )
        for name, (address_as, entities, private) in PEOPLE.items()
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TOOL_TYPE: TOOL_TYPE_PERSON},
        options={CONF_UNKNOWN_ADDRESS_AS: "Unknown Person", CONF_DENY_UNKNOWN: False},
        subentries_data=subentries,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return accounts


@pytest.fixture(autouse=True)
def _auckland_time():
    """Run every test in one known time zone, and put the old one back after."""
    previous = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(
        datetime.timezone(datetime.timedelta(hours=13), "Fixture/+13")
    )
    yield
    dt_util.set_default_time_zone(previous)

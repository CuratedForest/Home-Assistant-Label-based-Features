"""End-to-end setup + RestoreEntity tests."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.labeled_features.const import (
    CONF_AREAS_STATE_ENTITY_ID,
    CONF_ERROR_MODE_DEFAULT,
    CONF_FEATURES_STATE_ENTITY_ID,
    CONF_INSTANCE_NAME,
    CONF_LEADER_LABEL,
    CONF_SCRIPT_CALL_MODE_DEFAULT,
    DEFAULT_AREAS_STATE_ENTITY_ID,
    DEFAULT_FEATURES_STATE_ENTITY_ID,
    DEFAULT_LEADER_LABEL,
    DOMAIN,
    SERVICE_REPORT_ERROR,
)


async def _install(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="labeled_features",
        title="Labeled Features",
        data={
            CONF_INSTANCE_NAME: "Labeled Features",
            CONF_LEADER_LABEL: DEFAULT_LEADER_LABEL,
            CONF_FEATURES_STATE_ENTITY_ID: DEFAULT_FEATURES_STATE_ENTITY_ID,
            CONF_AREAS_STATE_ENTITY_ID: DEFAULT_AREAS_STATE_ENTITY_ID,
            CONF_ERROR_MODE_DEFAULT: "log",
            CONF_SCRIPT_CALL_MODE_DEFAULT: "Blocking",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_creates_both_sensors(hass: HomeAssistant) -> None:
    await _install(hass)
    features_state = hass.states.get(DEFAULT_FEATURES_STATE_ENTITY_ID)
    areas_state = hass.states.get(DEFAULT_AREAS_STATE_ENTITY_ID)
    assert features_state is not None
    assert areas_state is not None
    # feature_meta always populated.
    assert "Media Toggle" in features_state.attributes["feature_meta"]
    # label_map exposed even when empty.
    assert areas_state.attributes["label_map"] == {}


async def test_service_registered_after_setup(hass: HomeAssistant) -> None:
    await _install(hass)
    assert hass.services.has_service(DOMAIN, SERVICE_REPORT_ERROR)


async def test_manual_override_flows_through(hass: HomeAssistant) -> None:
    await _install(hass)
    hass.bus.async_fire(
        "labeled_feature_set",
        {
            "target_feature": "Night",
            "scope": "global",
            "scope_id": "",
            "enabled": True,
            "timestamp": 4242.0,
        },
    )
    await hass.async_block_till_done()
    state = hass.states.get(DEFAULT_FEATURES_STATE_ENTITY_ID)
    assert state is not None
    assert state.attributes["features"]["Night"]["global"][""]["enabled"] is True
    assert (
        state.attributes["features"]["Night"]["global"][""]["triggering_leader"] == ""
    )


async def test_snapshot_event_flows_through(hass: HomeAssistant) -> None:
    await _install(hass)
    hass.bus.async_fire(
        "labeled_feature_snapshot_set",
        {
            "snapshot_name": "sleep_timeout",
            "payload": {"media_player.bedroom": 0.45},
        },
    )
    await hass.async_block_till_done()
    state = hass.states.get(DEFAULT_FEATURES_STATE_ENTITY_ID)
    assert state.attributes["snapshots"] == {
        "sleep_timeout": {"media_player.bedroom": 0.45}
    }


async def test_unload_removes_service_when_last_entry(hass: HomeAssistant) -> None:
    entry = await _install(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, SERVICE_REPORT_ERROR)

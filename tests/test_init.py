"""Component-level tests for the Labeled Features integration.

End-to-end smoke coverage: setup, sensor entity ids, a leader tick,
manual override + snapshot events, label_map builds, and restore.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import (
    area_registry as ar,
    entity_registry as er,
    label_registry as lr,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.labeled_features.const import (
    AREAS_SENSOR_ENTITY_ID,
    DOMAIN,
    FEATURE_META,
    FEATURES_SENSOR_ENTITY_ID,
)

NIGHT_LEADER = "input_boolean.night_mode"


async def _setup_integration(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Labeled Features", data={}, unique_id=DOMAIN
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _create_night_leader(hass: HomeAssistant) -> None:
    """Register a night-mode leader entity with the required labels."""
    label_registry = lr.async_get(hass)
    feature_leader = label_registry.async_create("feature_leader")
    leader_night = label_registry.async_create("Leader: Night")

    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get_or_create(
        "input_boolean",
        "test",
        "night_mode",
        suggested_object_id="night_mode",
    )
    entity_registry.async_update_entity(
        entry.entity_id,
        labels={feature_leader.label_id, leader_night.label_id},
    )


async def test_setup_creates_sensors(hass: HomeAssistant) -> None:
    """Both sensors exist under the contractual entity ids."""
    await _setup_integration(hass)

    features_state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert features_state is not None
    assert features_state.state == "0"
    assert features_state.attributes["feature_meta"] == FEATURE_META
    assert features_state.attributes["leaders"] == {}
    assert features_state.attributes["features"] == {}
    assert features_state.attributes["snapshots"] == {}

    areas_state = hass.states.get(AREAS_SENSOR_ENTITY_ID)
    assert areas_state is not None
    assert areas_state.state == "0"
    assert areas_state.attributes["label_map"] == {}


async def test_leader_tick_updates_features(hass: HomeAssistant) -> None:
    """A leader state change flows through to the features attribute."""
    _create_night_leader(hass)
    hass.states.async_set(NIGHT_LEADER, "off")
    await _setup_integration(hass)

    hass.states.async_set(NIGHT_LEADER, "on")
    await hass.async_block_till_done()

    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert state.state == "1"
    entry = state.attributes["features"]["Night"]["global"][""]
    assert entry["enabled"] is True
    assert entry["mode"] == "leader"
    assert entry["triggering_leader"] == NIGHT_LEADER
    leader = state.attributes["leaders"][NIGHT_LEADER]
    assert leader["current_value"] == "on"

    hass.states.async_set(NIGHT_LEADER, "off")
    await hass.async_block_till_done()

    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    entry = state.attributes["features"]["Night"]["global"][""]
    assert entry["enabled"] is False
    leader = state.attributes["leaders"][NIGHT_LEADER]
    assert leader["current_value"] == "off"
    assert leader["previous_value"] == "on"


async def test_first_tick_without_real_old_state_is_gated(
    hass: HomeAssistant,
) -> None:
    """Boot-restore noise (no prior state) does not tick the sensor."""
    _create_night_leader(hass)
    await _setup_integration(hass)

    # First write has old_state=None → gated.
    hass.states.async_set(NIGHT_LEADER, "on")
    await hass.async_block_till_done()
    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert state.attributes["features"] == {}


async def test_manual_override_event(hass: HomeAssistant) -> None:
    """`labeled_feature_set` writes a manual entry into features."""
    await _setup_integration(hass)

    hass.bus.async_fire(
        "labeled_feature_set",
        {
            "target_feature": "Night",
            "scope": "global",
            "scope_id": "",
            "enabled": True,
            "timestamp": 1234.5,
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    entry = state.attributes["features"]["Night"]["global"][""]
    assert entry == {
        "enabled": True,
        "mode": "leader",
        "last_changed_timestamp": 1234.5,
        "triggering_leader": "",
    }

    # Manual entries survive subsequent ticks with no backing leader.
    hass.bus.async_fire(
        "labeled_feature_snapshot_set",
        {"snapshot_name": "x", "payload": {"a": 1}},
    )
    await hass.async_block_till_done()
    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert state.attributes["features"]["Night"]["global"][""]["enabled"] is True


async def test_snapshot_events(hass: HomeAssistant) -> None:
    """`labeled_feature_snapshot_set` merges and clears snapshots."""
    await _setup_integration(hass)

    hass.bus.async_fire(
        "labeled_feature_snapshot_set",
        {
            "snapshot_name": "sleep_timeout",
            "payload": {"media_player.bed": 0.45},
        },
    )
    await hass.async_block_till_done()
    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert state.attributes["snapshots"] == {
        "sleep_timeout": {"media_player.bed": 0.45}
    }

    hass.bus.async_fire(
        "labeled_feature_snapshot_set",
        {"snapshot_name": "sleep_timeout", "payload": {}},
    )
    await hass.async_block_till_done()
    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert state.attributes["snapshots"] == {}


async def test_area_provides_builds_label_map(hass: HomeAssistant) -> None:
    """An `Area Provides:` label on a gated area lands in label_map."""
    await _setup_integration(hass)

    label_registry = lr.async_get(hass)
    feature_leader = label_registry.async_create("feature_leader")
    provides = label_registry.async_create("Area Provides: Audio Mode")

    area_registry = ar.async_get(hass)
    kitchen = area_registry.async_create("Kitchen")
    area_registry.async_update(
        kitchen.id, labels={feature_leader.label_id, provides.label_id}
    )
    await hass.async_block_till_done()

    state = hass.states.get(AREAS_SENSOR_ENTITY_ID)
    assert state.state == "1"
    key = f"{kitchen.id}||Audio Mode"
    entry = state.attributes["label_map"][key]
    assert entry["scope"] == "area"
    assert entry["component"] == "select"
    assert entry["declaring_area_id"] == kitchen.id
    assert entry["label_data"]["scope_id"] == kitchen.id

    # Removing the Provides label retracts the entry.
    area_registry.async_update(kitchen.id, labels={feature_leader.label_id})
    await hass.async_block_till_done()
    state = hass.states.get(AREAS_SENSOR_ENTITY_ID)
    assert state.attributes["label_map"] == {}


async def test_restore_attributes_on_startup(hass: HomeAssistant) -> None:
    """Attributes restore across restarts (snapshots, features, leaders)."""
    restored_features = {
        "Night": {
            "global": {
                "": {
                    "enabled": True,
                    "mode": "leader",
                    "last_changed_timestamp": 111.0,
                    "triggering_leader": "",
                }
            }
        }
    }
    restored_snapshots = {"sleep_timeout": {"media_player.bed": 0.5}}
    mock_restore_cache(
        hass,
        [
            State(
                FEATURES_SENSOR_ENTITY_ID,
                "1",
                attributes={
                    "leaders": {},
                    "features": restored_features,
                    "snapshots": restored_snapshots,
                },
            )
        ],
    )

    await _setup_integration(hass)

    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert state.attributes["features"] == restored_features
    assert state.attributes["snapshots"] == restored_snapshots


async def test_areas_restore_publishes_before_boot_reconcile(
    hass: HomeAssistant,
) -> None:
    """During startup the restored label_map publishes first, then the
    STARTED reconcile emits a diffable restored→live transition (this is
    how the downstream automation retracts labels removed while HA was
    off)."""
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    from homeassistant.core import CoreState

    restored_map = {
        "kitchen||Audio Mode": {
            "scope_id": "kitchen",
            "label": "Audio Mode",
            "scope": "area",
            "component": "select",
            "declaring_area_id": "kitchen",
            "label_data": {
                "scope": "area",
                "scope_id": "kitchen",
                "component": "select",
                "declaring_area_id": "kitchen",
            },
        }
    }
    mock_restore_cache(
        hass,
        [
            State(
                AREAS_SENSOR_ENTITY_ID,
                "1",
                attributes={"label_map": restored_map},
            )
        ],
    )

    hass.set_state(CoreState.starting)
    await _setup_integration(hass)

    # Restored map is visible before the boot reconcile.
    state = hass.states.get(AREAS_SENSOR_ENTITY_ID)
    assert state.attributes["label_map"] == restored_map

    # Boot reconcile: the label was removed while "off" → retracted.
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    state = hass.states.get(AREAS_SENSOR_ENTITY_ID)
    assert state.attributes["label_map"] == {}


async def test_disable_option_gates_updates(hass: HomeAssistant) -> None:
    """The enable/disable option stops event processing."""
    _create_night_leader(hass)
    hass.states.async_set(NIGHT_LEADER, "off")
    entry = await _setup_integration(hass)

    hass.config_entries.async_update_entry(entry, options={"enabled": False})
    await hass.async_block_till_done()

    hass.states.async_set(NIGHT_LEADER, "on")
    await hass.async_block_till_done()
    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert state.state == "unavailable"


async def test_unload_entry(hass: HomeAssistant) -> None:
    """The entry unloads cleanly."""
    entry = await _setup_integration(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(FEATURES_SENSOR_ENTITY_ID).state == "unavailable"


async def test_handle_error_service_registered(hass: HomeAssistant) -> None:
    """The parity error-handling service exists and runs."""
    await _setup_integration(hass)
    assert hass.services.has_service(DOMAIN, "handle_error")
    await hass.services.async_call(
        DOMAIN,
        "handle_error",
        {"error_mode": "log", "message": "test message"},
        blocking=True,
    )


async def test_service_removed_on_unload(hass: HomeAssistant) -> None:
    """handle_error is removed when the last entry unloads."""
    entry = await _setup_integration(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, "handle_error")


async def test_snapshot_payload_size_cap(hass: HomeAssistant) -> None:
    """Oversized snapshot payloads are rejected."""
    await _setup_integration(hass)
    hass.bus.async_fire(
        "labeled_feature_snapshot_set",
        {"snapshot_name": "huge", "payload": {"blob": "x" * 20000}},
    )
    await hass.async_block_till_done()
    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert state.attributes["snapshots"] == {}


async def test_snapshot_count_cap(hass: HomeAssistant) -> None:
    """New snapshots beyond the cap are rejected; updates still pass."""
    await _setup_integration(hass)
    for index in range(50):
        hass.bus.async_fire(
            "labeled_feature_snapshot_set",
            {"snapshot_name": f"snap_{index}", "payload": {"i": index}},
        )
    await hass.async_block_till_done()
    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert len(state.attributes["snapshots"]) == 50

    # 51st distinct name is rejected.
    hass.bus.async_fire(
        "labeled_feature_snapshot_set",
        {"snapshot_name": "one_too_many", "payload": {"a": 1}},
    )
    await hass.async_block_till_done()
    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert "one_too_many" not in state.attributes["snapshots"]

    # Updating an existing snapshot still works at the cap.
    hass.bus.async_fire(
        "labeled_feature_snapshot_set",
        {"snapshot_name": "snap_0", "payload": {"i": 999}},
    )
    await hass.async_block_till_done()
    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert state.attributes["snapshots"]["snap_0"] == {"i": 999}


async def test_manual_override_field_length_cap(hass: HomeAssistant) -> None:
    """Garbage manual events with oversized fields are rejected."""
    await _setup_integration(hass)
    hass.bus.async_fire(
        "labeled_feature_set",
        {
            "target_feature": "N" * 300,
            "scope": "global",
            "scope_id": "",
            "enabled": True,
            "timestamp": 1.0,
        },
    )
    await hass.async_block_till_done()
    state = hass.states.get(FEATURES_SENSOR_ENTITY_ID)
    assert state.attributes["features"] == {}

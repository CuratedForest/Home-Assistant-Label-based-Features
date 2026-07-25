"""Integration tests for the two state sensors."""

from __future__ import annotations

from typing import Any

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.labeled_features.const import (
    CONF_LEADER_LABEL,
    CONF_MODE_OVERRIDES,
    DEFAULT_LEADER_LABEL,
    DOMAIN,
    EVENT_SET_FEATURE,
    EVENT_SET_SNAPSHOT,
    FEATURE_META,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant, callback

from .conftest import (
    create_area,
    create_floor,
    make_entry,
    register_entity,
    set_sensor_labels,
    setup_entry,
)

FEATURES_SENSOR = "sensor.labeled_features_state"
AREAS_SENSOR = "sensor.labeled_feature_areas_state"


def features(hass: HomeAssistant, entity_id: str = FEATURES_SENSOR) -> dict[str, Any]:
    """Return the `features` attribute."""
    return hass.states.get(entity_id).attributes["features"]


def leaders(hass: HomeAssistant, entity_id: str = FEATURES_SENSOR) -> dict[str, Any]:
    """Return the `leaders` attribute."""
    return hass.states.get(entity_id).attributes["leaders"]


def entry_for(
    hass: HomeAssistant, feature: str, scope: str, scope_id: str
) -> dict[str, Any]:
    """Return one features entry."""
    return features(hass)[feature][scope][scope_id]


async def async_set_state(
    hass: HomeAssistant, entity_id: str, state: str, attributes: dict | None = None
) -> None:
    """Set a state and let the coordinator process it."""
    hass.states.async_set(entity_id, state, attributes or {})
    await hass.async_block_till_done()


# ── entity ids and static surface ────────────────────────────────────────────


async def test_default_prefix_reproduces_legacy_entity_ids(
    hass: HomeAssistant, leader_label
) -> None:
    """The default prefix claims the legacy object ids."""
    await setup_entry(hass)
    assert hass.states.get(FEATURES_SENSOR) is not None
    assert hass.states.get(AREAS_SENSOR) is not None


async def test_custom_prefix(hass: HomeAssistant, leader_label) -> None:
    """A custom prefix moves both entity ids."""
    await setup_entry(hass, make_entry(prefix="lf_test", name="Test"))
    assert hass.states.get("sensor.lf_tests_state") is not None
    assert hass.states.get("sensor.lf_test_areas_state") is not None


async def test_feature_meta_and_units(hass: HomeAssistant, leader_label) -> None:
    """The static catalog and units match the legacy sensors."""
    await setup_entry(hass)
    state = hass.states.get(FEATURES_SENSOR)
    assert state.attributes["feature_meta"] == FEATURE_META
    assert state.attributes["unit_of_measurement"] == "leaders"
    assert state.attributes["state_class"] == "measurement"
    assert hass.states.get(AREAS_SENSOR).attributes["unit_of_measurement"] == "areas"


async def test_state_counts(hass: HomeAssistant, leader_label) -> None:
    """State is the leader count / gated area count."""
    register_entity(
        hass,
        "binary_sensor.front_door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="off",
    )
    create_area(hass, "Kitchen", labels=[DEFAULT_LEADER_LABEL])
    await setup_entry(hass)
    assert hass.states.get(FEATURES_SENSOR).state == "1"
    assert hass.states.get(AREAS_SENSOR).state == "1"


# ── leader-driven ticks ──────────────────────────────────────────────────────


async def test_global_leader_flip(hass: HomeAssistant, leader_label) -> None:
    """A boolean global leader writes and flips its triple."""
    register_entity(
        hass,
        "binary_sensor.front_door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="off",
    )
    await setup_entry(hass)
    assert features(hass) == {}

    await async_set_state(hass, "binary_sensor.front_door", "on")
    entry = entry_for(hass, "Open Door", "global", "")
    assert entry["enabled"] is True
    assert entry["mode"] == "leader"
    assert entry["triggering_leader"] == "binary_sensor.front_door"
    first_timestamp = entry["last_changed_timestamp"]

    await async_set_state(hass, "binary_sensor.front_door", "off")
    entry = entry_for(hass, "Open Door", "global", "")
    assert entry["enabled"] is False
    assert entry["last_changed_timestamp"] > first_timestamp


async def test_leader_tick_produces_exactly_one_state_write(
    hass: HomeAssistant, leader_label
) -> None:
    """The Leaders automation diffs from_state/to_state of `features`.

    Emitting several small writes where the template sensor emitted one would
    double-dispatch or drop a transition, so a tick must be a single write.
    """
    register_entity(
        hass,
        "binary_sensor.front_door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door", "Leader: Entry"],
        state="off",
    )
    await setup_entry(hass)

    writes: list[Any] = []

    @callback
    def _record(event) -> None:
        if event.data["entity_id"] == FEATURES_SENSOR:
            writes.append(event.data["new_state"])

    hass.bus.async_listen(EVENT_STATE_CHANGED, _record)

    await async_set_state(hass, "binary_sensor.front_door", "on")

    assert len(writes) == 1
    # Both features flip within that single write.
    assert (
        writes[0].attributes["features"]["Open Door"]["global"][""]["enabled"] is True
    )
    assert writes[0].attributes["features"]["Entry"]["global"][""]["enabled"] is True


async def test_area_scope_uses_the_leaders_area(
    hass: HomeAssistant, leader_label
) -> None:
    """Area-scoped triples key on the leader's area id."""
    area = create_area(hass, "TV Room")
    register_entity(
        hass,
        "sensor.tv_room_idle",
        labels=[DEFAULT_LEADER_LABEL, "Area Leader: Screen", "Area Screen Enable: 0"],
        area_id=area.id,
        state="5",
    )
    await setup_entry(hass)

    await async_set_state(hass, "sensor.tv_room_idle", "0")
    assert entry_for(hass, "Screen", "area", area.id)["enabled"] is True


async def test_floor_scope_resolves_through_the_area(
    hass: HomeAssistant, leader_label
) -> None:
    """Floor-scoped triples key on the floor of the leader's area."""
    floor = create_floor(hass, "First Floor")
    area = create_area(hass, "TV Room", floor_id=floor.floor_id)
    register_entity(
        hass,
        "input_select.house_mode",
        labels=[DEFAULT_LEADER_LABEL, "Floor Leader: Night"],
        area_id=area.id,
        state="Day",
    )
    await setup_entry(hass)

    await async_set_state(hass, "input_select.house_mode", "Night")
    assert entry_for(hass, "Night", "floor", floor.floor_id)["enabled"] is True


async def test_boot_restore_transition_is_ignored(
    hass: HomeAssistant, leader_label
) -> None:
    """Unknown -> real is not a user action and must not dispatch."""
    register_entity(
        hass,
        "binary_sensor.front_door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="unknown",
    )
    await setup_entry(hass)

    await async_set_state(hass, "binary_sensor.front_door", "on")
    assert features(hass) == {}

    await async_set_state(hass, "binary_sensor.front_door", "off")
    assert entry_for(hass, "Open Door", "global", "")["enabled"] is False


async def test_button_leader_bumps_timestamp_on_repeat_press(
    hass: HomeAssistant, leader_label
) -> None:
    """Two identical presses are two dispatches."""
    register_entity(
        hass,
        "event.somrig",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Night Buttons"],
        state="2026-01-01T00:00:00+00:00",
        attributes={"event_type": "1_short_release"},
    )
    await setup_entry(hass)

    await async_set_state(
        hass,
        "event.somrig",
        "2026-01-01T00:00:01+00:00",
        {"event_type": "1_short_release"},
    )
    first = entry_for(hass, "Night Buttons", "global", "")
    assert first["enabled"] is True

    await async_set_state(
        hass,
        "event.somrig",
        "2026-01-01T00:00:02+00:00",
        {"event_type": "1_short_release"},
    )
    second = entry_for(hass, "Night Buttons", "global", "")
    assert second["last_changed_timestamp"] > first["last_changed_timestamp"]


async def test_initial_press_is_skipped(hass: HomeAssistant, leader_label) -> None:
    """`*_initial_press` never becomes the tracked value."""
    register_entity(
        hass,
        "event.somrig",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Night Buttons"],
        state="2026-01-01T00:00:00+00:00",
        attributes={"event_type": "1_short_release"},
    )
    await setup_entry(hass)
    await async_set_state(
        hass,
        "event.somrig",
        "2026-01-01T00:00:01+00:00",
        {"event_type": "1_long_press"},
    )
    await async_set_state(
        hass,
        "event.somrig",
        "2026-01-01T00:00:02+00:00",
        {"event_type": "1_initial_press"},
    )
    assert leaders(hass)["event.somrig"]["current_value"] == "1_long_press"


async def test_leaders_attribute_tracks_previous_value(
    hass: HomeAssistant, leader_label
) -> None:
    """`leaders` exposes the substitution surface the scripts read."""
    register_entity(
        hass,
        "input_select.house_mode",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Night"],
        state="Day",
    )
    await setup_entry(hass)
    await async_set_state(hass, "input_select.house_mode", "Night")

    entry = leaders(hass)["input_select.house_mode"]
    assert entry["current_value"] == "Night"
    assert entry["previous_value"] == "Day"
    assert isinstance(entry["last_changed_timestamp"], float)


# ── modes ────────────────────────────────────────────────────────────────────


async def test_any_mode_via_sensor_label(hass: HomeAssistant, leader_label) -> None:
    """`Any` ORs across every leader of the triple."""
    register_entity(
        hass,
        "binary_sensor.door_a",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="on",
    )
    register_entity(
        hass,
        "binary_sensor.door_b",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="on",
    )
    await setup_entry(hass)
    set_sensor_labels(hass, FEATURES_SENSOR, ["Open Door Mode: Any"])

    # door_a closes, door_b is still open -> Any keeps the feature enabled.
    await async_set_state(hass, "binary_sensor.door_a", "off")
    entry = entry_for(hass, "Open Door", "global", "")
    assert entry["mode"] == "any"
    assert entry["enabled"] is True

    # Both closed -> disabled.
    await async_set_state(hass, "binary_sensor.door_b", "off")
    assert entry_for(hass, "Open Door", "global", "")["enabled"] is False


async def test_all_mode_via_option_override(hass: HomeAssistant, leader_label) -> None:
    """`All` ANDs across leaders, and options work as defaults."""
    register_entity(
        hass,
        "binary_sensor.door_a",
        labels=[
            DEFAULT_LEADER_LABEL,
            "Leader: Closed House",
            "Closed House Enable: off",
        ],
        state="on",
    )
    register_entity(
        hass,
        "binary_sensor.door_b",
        labels=[
            DEFAULT_LEADER_LABEL,
            "Leader: Closed House",
            "Closed House Enable: off",
        ],
        state="off",
    )
    await setup_entry(
        hass, make_entry(**{CONF_MODE_OVERRIDES: "Closed House Mode: All"})
    )

    await async_set_state(hass, "binary_sensor.door_a", "off")
    entry = entry_for(hass, "Closed House", "global", "")
    assert entry["mode"] == "all"
    assert entry["enabled"] is True

    await async_set_state(hass, "binary_sensor.door_b", "on")
    assert entry_for(hass, "Closed House", "global", "")["enabled"] is False


async def test_sensor_label_beats_option_override(
    hass: HomeAssistant, leader_label
) -> None:
    """Labels win over config-entry defaults."""
    register_entity(
        hass,
        "binary_sensor.door_a",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="off",
    )
    await setup_entry(hass, make_entry(**{CONF_MODE_OVERRIDES: "Open Door Mode: All"}))
    set_sensor_labels(hass, FEATURES_SENSOR, ["Open Door Mode: Any"])

    await async_set_state(hass, "binary_sensor.door_a", "on")
    assert entry_for(hass, "Open Door", "global", "")["mode"] == "any"


# ── manual write paths ───────────────────────────────────────────────────────


async def test_set_feature_event(hass: HomeAssistant, leader_label) -> None:
    """The compat event writes a manual override."""
    await setup_entry(hass)
    hass.bus.async_fire(
        EVENT_SET_FEATURE,
        {
            "target_feature": "Night",
            "scope": "global",
            "scope_id": "",
            "enabled": True,
            "timestamp": 123.0,
        },
    )
    await hass.async_block_till_done()

    assert entry_for(hass, "Night", "global", "") == {
        "enabled": True,
        "mode": "leader",
        "last_changed_timestamp": 123.0,
        "triggering_leader": "",
    }


async def test_set_feature_action(hass: HomeAssistant, leader_label) -> None:
    """The validated action writes the same shape."""
    await setup_entry(hass)
    await hass.services.async_call(
        DOMAIN,
        "set_feature",
        {
            "target_feature": "Night",
            "scope": "area",
            "scope_id": "bedroom_main",
            "enabled": True,
        },
        blocking=True,
    )
    entry = entry_for(hass, "Night", "area", "bedroom_main")
    assert entry["enabled"] is True
    assert entry["triggering_leader"] == ""


async def test_manual_entries_survive_reconcile(
    hass: HomeAssistant, leader_label
) -> None:
    """Manual overrides are exempt from the orphan drop."""
    await setup_entry(hass)
    hass.bus.async_fire(
        EVENT_SET_FEATURE,
        {"target_feature": "Night", "scope": "global", "scope_id": "", "enabled": True},
    )
    await hass.async_block_till_done()

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert entry_for(hass, "Night", "global", "")["enabled"] is True


async def test_set_feature_rejects_bad_scope(hass: HomeAssistant, leader_label) -> None:
    """An unknown scope is refused rather than written."""
    await setup_entry(hass)
    hass.bus.async_fire(
        EVENT_SET_FEATURE,
        {"target_feature": "Night", "scope": "planet", "enabled": True},
    )
    await hass.async_block_till_done()
    assert features(hass) == {}


async def test_snapshot_set_and_delete(hass: HomeAssistant, leader_label) -> None:
    """Snapshots merge on write and delete on an empty payload."""
    await setup_entry(hass)
    hass.bus.async_fire(
        EVENT_SET_SNAPSHOT,
        {
            "snapshot_name": "sleep_timeout",
            "payload": {"media_player.bedroom_main_audio": 0.45},
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(FEATURES_SENSOR).attributes["snapshots"] == {
        "sleep_timeout": {"media_player.bedroom_main_audio": 0.45}
    }

    hass.bus.async_fire(
        EVENT_SET_SNAPSHOT, {"snapshot_name": "sleep_timeout", "payload": {}}
    )
    await hass.async_block_till_done()
    assert hass.states.get(FEATURES_SENSOR).attributes["snapshots"] == {}


# ── orphan drop ──────────────────────────────────────────────────────────────


async def test_orphaned_triple_drops_on_reconcile(
    hass: HomeAssistant, leader_label
) -> None:
    """Removing the Leader label drops the triple."""
    entity = register_entity(
        hass,
        "binary_sensor.front_door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="off",
    )
    await setup_entry(hass)
    await async_set_state(hass, entity.entity_id, "on")
    assert "Open Door" in features(hass)

    register_entity(hass, "binary_sensor.front_door", labels=[DEFAULT_LEADER_LABEL])
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert features(hass) == {}


async def test_label_edit_does_not_seed_a_dispatchable_entry(
    hass: HomeAssistant, leader_label
) -> None:
    """Newly mapped triples wait for a real state change.

    Seeding here would look like a first-seed entry to the Leaders automation
    and dispatch followers purely because a label was edited.
    """
    await setup_entry(hass)
    register_entity(
        hass,
        "binary_sensor.front_door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="on",
    )
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert features(hass) == {}
    assert "binary_sensor.front_door" in leaders(hass)


# ── areas sensor ─────────────────────────────────────────────────────────────


async def test_label_map_is_published(hass: HomeAssistant, leader_label) -> None:
    """The areas sensor exposes the flat label_map registry."""
    area = create_area(
        hass, "Kitchen", labels=[DEFAULT_LEADER_LABEL, "Area Provides: Audio Mode"]
    )
    await setup_entry(hass)
    label_map = hass.states.get(AREAS_SENSOR).attributes["label_map"]
    assert set(label_map) == {f"{area.id}||Audio Mode"}


async def test_label_map_reconciles_after_start(
    hass: HomeAssistant, leader_label
) -> None:
    """A label added later shows up on the next reconcile."""
    await setup_entry(hass)
    assert hass.states.get(AREAS_SENSOR).attributes["label_map"] == {}

    area = create_area(
        hass, "Kitchen", labels=[DEFAULT_LEADER_LABEL, "Area Provides: Audio Mode"]
    )
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert (
        f"{area.id}||Audio Mode"
        in hass.states.get(AREAS_SENSOR).attributes["label_map"]
    )


# ── restore ──────────────────────────────────────────────────────────────────


async def test_attributes_restore_across_restart(
    hass: HomeAssistant, leader_label
) -> None:
    """Restored attributes are adopted before any recompute."""
    stored_features = {
        "Night": {
            "global": {
                "": {
                    "enabled": True,
                    "mode": "leader",
                    "last_changed_timestamp": 5.0,
                    "triggering_leader": "",
                }
            }
        }
    }
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                _state(
                    FEATURES_SENSOR,
                    "0",
                    {
                        "leaders": {
                            "binary_sensor.front_door": {
                                "current_value": "on",
                                "previous_value": "off",
                                "last_changed_timestamp": 1.0,
                            }
                        },
                        "features": stored_features,
                        "snapshots": {"sleep_timeout": {"a": 1}},
                    },
                ),
                {},
            ),
            (
                _state(AREAS_SENSOR, "0", {"label_map": {"kitchen||Audio Mode": {}}}),
                {},
            ),
        ),
    )

    await setup_entry(hass)

    state = hass.states.get(FEATURES_SENSOR)
    assert state.attributes["features"] == stored_features
    assert state.attributes["snapshots"] == {"sleep_timeout": {"a": 1}}
    # The restored leader is no longer labeled, so it drops on reconcile.
    assert state.attributes["leaders"] == {}


def _state(entity_id: str, state: str, attributes: dict[str, Any]):
    """Build a State for the restore cache."""
    from homeassistant.core import State

    return State(entity_id, state, attributes)


# ── multi-instance routing ───────────────────────────────────────────────────


async def test_untargeted_event_goes_to_one_instance(
    hass: HomeAssistant, leader_label
) -> None:
    """Only the owning instance consumes an untargeted payload."""
    register_entity(
        hass,
        "binary_sensor.front_door",
        labels=["test_leader", "Leader: Open Door"],
        state="off",
    )
    first = await setup_entry(hass)
    second = await setup_entry(
        hass,
        make_entry(prefix="lf_test", name="Test", **{CONF_LEADER_LABEL: "test_leader"}),
    )
    await async_set_state(hass, "binary_sensor.front_door", "on")

    hass.bus.async_fire(
        EVENT_SET_FEATURE,
        {"target_feature": "Open Door", "scope": "global", "enabled": False},
    )
    await hass.async_block_till_done()

    assert (
        features(hass, "sensor.lf_tests_state")["Open Door"]["global"][""][
            "triggering_leader"
        ]
        == ""
    )
    assert features(hass, FEATURES_SENSOR) == {}
    assert first.entry_id != second.entry_id


async def test_explicit_instance_targeting(hass: HomeAssistant, leader_label) -> None:
    """An explicit instance field overrides ownership routing."""
    await setup_entry(hass)
    await setup_entry(hass, make_entry(prefix="lf_test", name="Test"))

    hass.bus.async_fire(
        EVENT_SET_FEATURE,
        {
            "target_feature": "Night",
            "scope": "global",
            "enabled": True,
            "instance": "Test",
        },
    )
    await hass.async_block_till_done()

    assert "Night" in features(hass, "sensor.lf_tests_state")
    assert features(hass, FEATURES_SENSOR) == {}


async def test_unload_removes_entities_and_services(
    hass: HomeAssistant, leader_label
) -> None:
    """Unloading the last entry tears everything down."""
    entry = await setup_entry(hass)
    assert hass.services.has_service(DOMAIN, "set_feature")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert not hass.services.has_service(DOMAIN, "set_feature")
    assert hass.states.get(FEATURES_SENSOR).state == "unavailable"


async def test_options_update_reloads_the_entry(
    hass: HomeAssistant, leader_label
) -> None:
    """Changing the leader label re-resolves the leader set."""
    register_entity(
        hass,
        "binary_sensor.front_door",
        labels=["other_leader", "Leader: Open Door"],
        state="off",
    )
    entry: MockConfigEntry = await setup_entry(hass)
    assert hass.states.get(FEATURES_SENSOR).state == "0"

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_LEADER_LABEL: "other_leader"}
    )
    await hass.async_block_till_done()

    assert hass.states.get(FEATURES_SENSOR).state == "1"

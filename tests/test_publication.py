"""Regression tests for state publication and event routing.

Every write path must emit a real ``state_changed`` event:
``automation.labeled_feature_leaders`` triggers on the ``features`` attribute
and diffs ``from_state``/``to_state``, so a write that Home Assistant
suppresses (because the published attribute object was mutated in place and
therefore compares equal to the previous one) silently stops dispatching
followers. Asserting via ``hass.states.get()`` cannot catch that — it reads the
same aliased object — so these tests count bus events instead.
"""

from __future__ import annotations

from typing import Any

from custom_components.labeled_features.const import (
    CONF_LEADER_LABEL,
    DEFAULT_LEADER_LABEL,
    DOMAIN,
    EVENT_SET_FEATURE,
    EVENT_SET_SNAPSHOT,
)
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback

from .conftest import make_entry, register_entity, setup_entry

FEATURES_SENSOR = "sensor.labeled_features_state"
AREAS_SENSOR = "sensor.labeled_feature_areas_state"
TEST_FEATURES_SENSOR = "sensor.lf_tests_state"


class StateWrites:
    """Collect published states for one entity."""

    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        """Start listening."""
        self.entity_id = entity_id
        self.states: list[Any] = []
        hass.bus.async_listen(EVENT_STATE_CHANGED, self._record)

    @callback
    def _record(self, event: Event) -> None:
        if event.data["entity_id"] == self.entity_id:
            self.states.append(event.data["new_state"])

    def __len__(self) -> int:
        """Return the number of published writes."""
        return len(self.states)

    @property
    def last(self) -> Any:
        """Return the most recently published state."""
        return self.states[-1]


async def test_manual_set_feature_publishes_a_state_change(
    hass: HomeAssistant, leader_label
) -> None:
    """A manual override must be visible to the Leaders automation."""
    await setup_entry(hass)
    writes = StateWrites(hass, FEATURES_SENSOR)

    hass.bus.async_fire(
        EVENT_SET_FEATURE,
        {
            "target_feature": "Night",
            "scope": "global",
            "scope_id": "",
            "enabled": True,
        },
    )
    await hass.async_block_till_done()

    assert len(writes) == 1
    entry = writes.last.attributes["features"]["Night"]["global"][""]
    assert entry["enabled"] is True
    assert entry["triggering_leader"] == ""


async def test_repeated_manual_writes_each_publish(
    hass: HomeAssistant, leader_label
) -> None:
    """Flipping a manual override back and forth publishes both transitions."""
    await setup_entry(hass)
    writes = StateWrites(hass, FEATURES_SENSOR)

    for enabled in (True, False, True):
        hass.bus.async_fire(
            EVENT_SET_FEATURE,
            {
                "target_feature": "Night",
                "scope": "global",
                "scope_id": "",
                "enabled": enabled,
            },
        )
        await hass.async_block_till_done()

    assert len(writes) == 3
    assert [
        state.attributes["features"]["Night"]["global"][""]["enabled"]
        for state in writes.states
    ] == [True, False, True]


async def test_snapshot_write_and_delete_publish(
    hass: HomeAssistant, leader_label
) -> None:
    """Snapshots must reach the recorder so they survive a restart."""
    await setup_entry(hass)
    writes = StateWrites(hass, FEATURES_SENSOR)

    hass.bus.async_fire(
        EVENT_SET_SNAPSHOT,
        {"snapshot_name": "sleep_timeout", "payload": {"media_player.a": 0.45}},
    )
    await hass.async_block_till_done()
    assert len(writes) == 1
    assert writes.last.attributes["snapshots"] == {
        "sleep_timeout": {"media_player.a": 0.45}
    }

    hass.bus.async_fire(
        EVENT_SET_SNAPSHOT, {"snapshot_name": "sleep_timeout", "payload": {}}
    )
    await hass.async_block_till_done()
    assert len(writes) == 2
    assert writes.last.attributes["snapshots"] == {}


async def test_published_attributes_are_detached_snapshots(
    hass: HomeAssistant, leader_label
) -> None:
    """A published attribute must not alias the coordinator's working state."""
    entry = await setup_entry(hass)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    hass.bus.async_fire(
        EVENT_SET_FEATURE,
        {"target_feature": "Night", "scope": "global", "scope_id": "", "enabled": True},
    )
    await hass.async_block_till_done()

    published = hass.states.get(FEATURES_SENSOR).attributes["features"]
    assert published == coordinator.features
    assert published is not coordinator.features
    assert (
        published["Night"]["global"][""]
        is not coordinator.features["Night"]["global"][""]
    )


async def test_leaders_only_change_publishes(hass: HomeAssistant, leader_label) -> None:
    """A tick that only moves `previous_value` still publishes."""
    register_entity(
        hass,
        "event.somrig",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Buttons"],
        state="2026-01-01T00:00:00+00:00",
        attributes={"event_type": "1_short_release"},
    )
    await setup_entry(hass)
    writes = StateWrites(hass, FEATURES_SENSOR)

    hass.states.async_set(
        "event.somrig",
        "2026-01-01T00:00:01+00:00",
        {"event_type": "2_short_release"},
    )
    await hass.async_block_till_done()

    assert len(writes) == 1
    assert writes.last.attributes["leaders"]["event.somrig"]["current_value"] == (
        "2_short_release"
    )


async def test_label_map_change_publishes(hass: HomeAssistant, leader_label) -> None:
    """The Areas automation needs a real `label_map` transition."""
    from .conftest import create_area

    await setup_entry(hass)
    writes = StateWrites(hass, AREAS_SENSOR)

    area = create_area(
        hass, "Kitchen", labels=[DEFAULT_LEADER_LABEL, "Area Provides: Audio Mode"]
    )
    hass.bus.async_fire("homeassistant_started")
    await hass.async_block_till_done()

    assert len(writes) >= 1
    assert f"{area.id}||Audio Mode" in writes.last.attributes["label_map"]


# ── routing ──────────────────────────────────────────────────────────────────


async def test_ambiguous_ownership_drops_the_event(
    hass: HomeAssistant, leader_label
) -> None:
    """Two instances sharing a leader label must not silently pick one.

    This is the migration scenario: a test instance created first with the same
    leader label would otherwise swallow production's manual overrides.
    """
    register_entity(
        hass,
        "binary_sensor.door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="off",
    )
    await setup_entry(hass, make_entry(prefix="lf_test", name="Test"))
    await setup_entry(hass, make_entry(prefix="labeled_feature", name="Prod"))
    hass.states.async_set("binary_sensor.door", "on")
    await hass.async_block_till_done()

    hass.bus.async_fire(
        EVENT_SET_FEATURE,
        {
            "target_feature": "Open Door",
            "scope": "global",
            "scope_id": "",
            "enabled": False,
        },
    )
    await hass.async_block_till_done()

    for entity_id in (FEATURES_SENSOR, TEST_FEATURES_SENSOR):
        entry = hass.states.get(entity_id).attributes["features"]["Open Door"][
            "global"
        ][""]
        assert entry["triggering_leader"] == "binary_sensor.door"
        assert entry["enabled"] is True


async def test_ambiguous_event_is_targetable(hass: HomeAssistant, leader_label) -> None:
    """An explicit `instance` resolves the ambiguity."""
    register_entity(
        hass,
        "binary_sensor.door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="off",
    )
    await setup_entry(hass, make_entry(prefix="lf_test", name="Test"))
    await setup_entry(hass, make_entry(prefix="labeled_feature", name="Prod"))
    hass.states.async_set("binary_sensor.door", "on")
    await hass.async_block_till_done()

    hass.bus.async_fire(
        EVENT_SET_FEATURE,
        {
            "target_feature": "Open Door",
            "scope": "global",
            "scope_id": "",
            "enabled": False,
            "instance": "Prod",
        },
    )
    await hass.async_block_till_done()

    prod = hass.states.get(FEATURES_SENSOR).attributes["features"]["Open Door"][
        "global"
    ][""]
    test = hass.states.get(TEST_FEATURES_SENSOR).attributes["features"]["Open Door"][
        "global"
    ][""]
    assert prod["triggering_leader"] == ""
    assert test["triggering_leader"] == "binary_sensor.door"


async def test_unowned_event_prefers_the_default_prefix_instance(
    hass: HomeAssistant, leader_label
) -> None:
    """A manual-only feature goes to the production (default prefix) instance."""
    await setup_entry(
        hass,
        make_entry(prefix="lf_test", name="Test", **{CONF_LEADER_LABEL: "test_leader"}),
    )
    await setup_entry(hass, make_entry(prefix="labeled_feature", name="Prod"))

    hass.bus.async_fire(
        EVENT_SET_FEATURE,
        {"target_feature": "Night", "scope": "global", "scope_id": "", "enabled": True},
    )
    await hass.async_block_till_done()

    assert "Night" in hass.states.get(FEATURES_SENSOR).attributes["features"]
    assert hass.states.get(TEST_FEATURES_SENSOR).attributes["features"] == {}


async def test_reload_is_repeatable(hass: HomeAssistant, leader_label) -> None:
    """Options changes reload the entry; the platform must keep finding state."""
    entry = await setup_entry(hass)
    for label in ("other_leader", "third_leader"):
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_LEADER_LABEL: label}
        )
        await hass.async_block_till_done()
        assert hass.states.get(FEATURES_SENSOR).state == "0"

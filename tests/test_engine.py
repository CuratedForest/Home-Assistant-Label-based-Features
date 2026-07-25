"""Unit tests for the pure evaluation engine.

Covers the behavioral-parity checklist from the Part 1 plan — each
subtle behavior downstream YAML depends on gets a test here.
"""

from __future__ import annotations

import pytest

from custom_components.labeled_features import engine
from custom_components.labeled_features.const import FEATURE_META


def _live(states: dict[str, str]):
    """Live-state getter over a plain dict ('unknown' when missing)."""

    def getter(entity_id: str) -> str:
        return states.get(entity_id, "unknown")

    return getter


def _seed(states: dict[str, str], ts: float = 100.0):
    """Seed getter over a plain dict (('unknown', 0.0) when missing)."""

    def getter(entity_id: str) -> tuple[str, float]:
        if entity_id not in states:
            return "unknown", 0.0
        return states[entity_id], ts

    return getter


# ── eval_leader ──────────────────────────────────────────────────────


def test_default_truth_state_equals_feature_name() -> None:
    """State == feature name (case-sensitive) counts as enabled."""
    assert engine.eval_leader(
        ["Leader: Night"],
        "",
        "Night",
        state="Night",
        cv="Night",
        prev_cv="",
        domain="input_select",
    )
    # Case-sensitive: "night" does not match.
    assert not engine.eval_leader(
        ["Leader: Night"],
        "",
        "Night",
        state="night",
        cv="night",
        prev_cv="",
        domain="input_select",
    )


@pytest.mark.parametrize(
    "state", ["on", "true", "home", "open", "detected", "active", "unlocked", "ON"]
)
def test_default_truth_generic_truthy(state: str) -> None:
    """Generic truthy set is compared case-insensitively."""
    assert engine.eval_leader(
        [], "", "Fan", state=state, cv=state, prev_cv="", domain="switch"
    )


def test_default_truth_momentary_domains_always_true() -> None:
    """event/button leaders always evaluate to enabled=True."""
    assert engine.eval_leader(
        [],
        "Area ",
        "Buttons",
        state="2026-01-01T00:00:00+00:00",
        cv="1_short_release",
        prev_cv="",
        domain="event",
    )
    assert engine.eval_leader(
        [], "", "Press", state="whatever", cv="x", prev_cv="", domain="button"
    )


def test_enable_disable_labels() -> None:
    """Enable/Disable labels pin the truth function to the live state."""
    labels = ["Area Media Playing Enable: playing"]
    kwargs = {"cv": "playing", "prev_cv": "", "domain": "media_player"}
    assert engine.eval_leader(
        labels, "Area ", "Media Playing", state="playing", **kwargs
    )
    assert not engine.eval_leader(
        labels, "Area ", "Media Playing", state="paused", **kwargs
    )

    # Disable-only: enabled unless state matches the disable value.
    dis = ["Screen Disable: standby"]
    assert not engine.eval_leader(
        dis, "", "Screen", state="standby", cv="", prev_cv="", domain="sensor"
    )
    assert engine.eval_leader(
        dis, "", "Screen", state="HDMI1", cv="", prev_cv="", domain="sensor"
    )

    # Both: enable match wins only when disable does not match.
    both = ["Screen Enable: HDMI1", "Screen Disable: standby"]
    assert engine.eval_leader(
        both, "", "Screen", state="HDMI1", cv="", prev_cv="", domain="sensor"
    )
    assert not engine.eval_leader(
        both, "", "Screen", state="standby", cv="", prev_cv="", domain="sensor"
    )
    assert not engine.eval_leader(
        both, "", "Screen", state="other", cv="", prev_cv="", domain="sensor"
    )


def test_direction_takes_precedence_over_enable() -> None:
    """Increasing/Decreasing wins over Enable:/Disable: labels."""
    labels = ["Area Idle Decreasing: True", "Area Idle Enable: 50"]
    # Decreasing 60 -> 40: enabled regardless of the Enable label.
    assert engine.eval_leader(
        labels,
        "Area ",
        "Idle",
        state="40",
        cv="40",
        prev_cv="60",
        domain="sensor",
    )
    # Increasing movement: not enabled.
    assert not engine.eval_leader(
        labels,
        "Area ",
        "Idle",
        state="50",
        cv="50",
        prev_cv="40",
        domain="sensor",
    )


def test_direction_non_numeric_or_first_update_is_false() -> None:
    """Non-numeric values or missing previous → enabled=False."""
    labels = ["Idle Increasing: True"]
    assert not engine.eval_leader(
        labels, "", "Idle", state="abc", cv="abc", prev_cv="1", domain="sensor"
    )
    assert not engine.eval_leader(
        labels, "", "Idle", state="2", cv="2", prev_cv="", domain="sensor"
    )


def test_direction_both_labels_or() -> None:
    """Both direction labels present → OR of the two."""
    labels = ["Idle Increasing: True", "Idle Decreasing: True"]
    assert engine.eval_leader(
        labels, "", "Idle", state="2", cv="2", prev_cv="1", domain="sensor"
    )
    assert engine.eval_leader(
        labels, "", "Idle", state="1", cv="1", prev_cv="2", domain="sensor"
    )
    assert not engine.eval_leader(
        labels, "", "Idle", state="1", cv="1", prev_cv="1", domain="sensor"
    )


def test_invert_applies_after_all_rules() -> None:
    """Invert flips Direction, Enable/Disable, and default results."""
    labels = ["Idle Decreasing: True", "Idle Invert: True"]
    assert not engine.eval_leader(
        labels, "", "Idle", state="1", cv="1", prev_cv="2", domain="sensor"
    )
    assert engine.eval_leader(
        ["Night Invert: True"],
        "",
        "Night",
        state="off",
        cv="off",
        prev_cv="",
        domain="switch",
    )


# ── build_triples / resolve_modes ────────────────────────────────────


def test_build_triples_scopes_and_dedup() -> None:
    labels_by_eid = {
        "binary_sensor.front_door": ["feature_leader", "Leader: Night"],
        "sensor.tv_idle": ["feature_leader", "Area Leader: Screen"],
        "switch.fan_mode": ["feature_leader", "Floor Leader: Fan"],
    }
    ctx = {
        "binary_sensor.front_door": {"area_id": "hall", "floor_id": "first"},
        "sensor.tv_idle": {"area_id": "tv_room", "floor_id": "first"},
        "switch.fan_mode": {"area_id": "bedroom", "floor_id": "second"},
    }
    triples, errors = engine.build_triples(labels_by_eid, ctx)
    assert errors == []
    assert triples == {
        ("Night", "global", ""): ["binary_sensor.front_door"],
        ("Screen", "area", "tv_room"): ["sensor.tv_idle"],
        ("Fan", "floor", "second"): ["switch.fan_mode"],
    }


def test_build_triples_unresolved_scope_is_skipped_with_error() -> None:
    """Area/floor-scoped leaders without an area/floor are skipped."""
    triples, errors = engine.build_triples(
        {"sensor.orphan": ["Area Leader: Screen", "Floor Leader: Fan"]},
        {"sensor.orphan": {"area_id": "", "floor_id": ""}},
    )
    assert triples == {}
    assert len(errors) == 2
    assert all(err["key"] == "unresolved_scope" for err in errors)


def test_resolve_modes_from_sensor_labels() -> None:
    keys = [
        ("Night", "floor", "first"),
        ("Screen", "area", "tv_room"),
        ("Night", "global", ""),
    ]
    sensor_labels = [
        "Floor Night Mode: All",
        "Area Screen Mode: Any",
    ]
    modes = engine.resolve_modes(keys, sensor_labels)
    assert modes[("Night", "floor", "first")] == "all"
    assert modes[("Screen", "area", "tv_room")] == "any"
    assert modes[("Night", "global", "")] == "leader"  # default


# ── update_features ──────────────────────────────────────────────────


def _night_triples() -> dict:
    return {("Night", "global", ""): ["switch.night"]}


def test_features_basic_flip_and_timestamp() -> None:
    labels = {"switch.night": ["Leader: Night"]}
    features = engine.update_features(
        {},
        {},
        _night_triples(),
        {},
        labels,
        _live({"switch.night": "on"}),
        changed_eid="switch.night",
        cv_raw="on",
        changed_ts=10.0,
    )
    entry = features["Night"]["global"][""]
    assert entry == {
        "enabled": True,
        "mode": "leader",
        "last_changed_timestamp": 10.0,
        "triggering_leader": "switch.night",
    }

    # Same value again (no flip): timestamp does NOT bump.
    features2 = engine.update_features(
        features,
        {"switch.night": {"current_value": "on"}},
        _night_triples(),
        {},
        labels,
        _live({"switch.night": "on"}),
        changed_eid="switch.night",
        cv_raw="on",
        changed_ts=20.0,
    )
    assert features2["Night"]["global"][""]["last_changed_timestamp"] == 10.0

    # Flip off: timestamp bumps.
    features3 = engine.update_features(
        features2,
        {"switch.night": {"current_value": "on"}},
        _night_triples(),
        {},
        labels,
        _live({"switch.night": "off"}),
        changed_eid="switch.night",
        cv_raw="off",
        changed_ts=30.0,
    )
    entry3 = features3["Night"]["global"][""]
    assert entry3["enabled"] is False
    assert entry3["last_changed_timestamp"] == 30.0


def test_features_button_leader_bumps_timestamp_without_flip() -> None:
    """event/button leaders bump the ts on every accepted press."""
    triples = {("Buttons", "area", "tv_room"): ["event.remote"]}
    labels = {"event.remote": ["Area Leader: Buttons"]}
    live = _live({"event.remote": "2026-01-01T00:00:00+00:00"})

    features = engine.update_features(
        {},
        {},
        triples,
        {},
        labels,
        live,
        changed_eid="event.remote",
        cv_raw="1_short_release",
        changed_ts=10.0,
    )
    features2 = engine.update_features(
        features,
        {},
        triples,
        {},
        labels,
        live,
        changed_eid="event.remote",
        cv_raw="1_short_release",
        changed_ts=20.0,
    )
    entry = features2["Buttons"]["area"]["tv_room"]
    assert entry["enabled"] is True  # momentary domains are always True
    assert entry["last_changed_timestamp"] == 20.0


def test_features_skips_initial_press_and_unreal_values() -> None:
    triples = {("Buttons", "area", "tv_room"): ["event.remote"]}
    labels = {"event.remote": ["Area Leader: Buttons"]}
    live = _live({"event.remote": "x"})
    for skip_value in ("dots_1_initial_press", "unknown", "Unavailable", "none"):
        features = engine.update_features(
            {},
            {},
            triples,
            {},
            labels,
            live,
            changed_eid="event.remote",
            cv_raw=skip_value,
            changed_ts=10.0,
        )
        assert features == {}


def test_features_mode_any_and_all_fold_across_leaders() -> None:
    triples = {
        ("Closed House", "global", ""): [
            "binary_sensor.door_a",
            "binary_sensor.door_b",
        ]
    }
    labels = {
        "binary_sensor.door_a": [
            "Leader: Closed House",
            "Closed House Invert: True",
        ],
        "binary_sensor.door_b": [
            "Leader: Closed House",
            "Closed House Invert: True",
        ],
    }
    # door_a just closed (off→inverted True); door_b still open (on→False).
    live = _live({"binary_sensor.door_a": "off", "binary_sensor.door_b": "on"})

    all_mode = {("Closed House", "global", ""): "all"}
    features = engine.update_features(
        {},
        {},
        triples,
        all_mode,
        labels,
        live,
        changed_eid="binary_sensor.door_a",
        cv_raw="off",
        changed_ts=10.0,
    )
    assert features["Closed House"]["global"][""]["enabled"] is False

    any_mode = {("Closed House", "global", ""): "any"}
    features = engine.update_features(
        {},
        {},
        triples,
        any_mode,
        labels,
        live,
        changed_eid="binary_sensor.door_a",
        cv_raw="off",
        changed_ts=10.0,
    )
    assert features["Closed House"]["global"][""]["enabled"] is True

    # leader mode: only the changed leader counts.
    features = engine.update_features(
        {},
        {},
        triples,
        {},
        labels,
        live,
        changed_eid="binary_sensor.door_a",
        cv_raw="off",
        changed_ts=10.0,
    )
    assert features["Closed House"]["global"][""]["enabled"] is True
    assert features["Closed House"]["global"][""]["mode"] == "leader"


def test_features_orphan_drop_except_manual() -> None:
    prev = {
        "Night": {
            "global": {
                "": {
                    "enabled": True,
                    "mode": "leader",
                    "last_changed_timestamp": 1.0,
                    "triggering_leader": "switch.gone",
                }
            }
        },
        "Party": {
            "area": {
                "kitchen": {
                    "enabled": True,
                    "mode": "leader",
                    "last_changed_timestamp": 2.0,
                    "triggering_leader": "",  # manual override — exempt
                }
            }
        },
    }
    features = engine.update_features(
        prev,
        {},
        {},
        {},
        {},
        _live({}),
    )
    assert "Night" not in features
    assert features["Party"]["area"]["kitchen"]["enabled"] is True


def test_features_manual_override_preserves_mode_and_is_sticky() -> None:
    prev = {
        "Night": {
            "global": {
                "": {
                    "enabled": False,
                    "mode": "all",
                    "last_changed_timestamp": 1.0,
                    "triggering_leader": "switch.night",
                }
            }
        },
    }
    features = engine.update_features(
        prev,
        {},
        _night_triples(),
        {},
        {},
        _live({}),
        manual={
            "target_feature": "Night",
            "scope": "global",
            "scope_id": "",
            "enabled": True,
            "timestamp": 50.0,
        },
    )
    entry = features["Night"]["global"][""]
    assert entry == {
        "enabled": True,
        "mode": "all",  # preserved from the existing entry
        "last_changed_timestamp": 50.0,
        "triggering_leader": "",
    }

    # New manual entry with no prior mode defaults to 'leader'.
    features2 = engine.update_features(
        {},
        {},
        {},
        {},
        {},
        _live({}),
        manual={
            "target_feature": "Party",
            "scope": "area",
            "scope_id": "kitchen",
            "enabled": True,
            "timestamp": 60.0,
        },
    )
    assert features2["Party"]["area"]["kitchen"]["mode"] == "leader"


def test_features_manual_invalid_scope_ignored() -> None:
    features = engine.update_features(
        {},
        {},
        {},
        {},
        {},
        _live({}),
        manual={
            "target_feature": "Night",
            "scope": "bogus",
            "scope_id": "",
            "enabled": True,
            "timestamp": 60.0,
        },
    )
    assert features == {}


def test_features_defensive_against_legacy_non_mapping_values() -> None:
    """Legacy snapshots with stringy values don't crash the rebuild."""
    prev = {
        "Night": "not-a-mapping",
        "Screen": {"area": "still-not-a-mapping"},
        "Fan": {"floor": {"first": "nope"}},
    }
    features = engine.update_features(prev, {}, {}, {}, {}, _live({}))
    # 'Fan' entry coerces to {} → manual (no triggering_leader) → kept.
    assert features == {"Fan": {"floor": {"first": {}}}}


def test_features_direction_uses_trigger_values_not_live_state() -> None:
    """Direction compares the trigger cv against the stored previous."""
    triples = {("Screen", "area", "tv_room"): ["sensor.idle"]}
    labels = {"sensor.idle": ["Area Leader: Screen", "Area Screen Decreasing: True"]}
    prev_leaders = {
        "sensor.idle": {
            "current_value": "60",
            "previous_value": "70",
            "last_changed_timestamp": 5.0,
        }
    }
    features = engine.update_features(
        {},
        prev_leaders,
        triples,
        {},
        labels,
        _live({"sensor.idle": "40"}),
        changed_eid="sensor.idle",
        cv_raw="40",
        changed_ts=10.0,
    )
    assert features["Screen"]["area"]["tv_room"]["enabled"] is True


# ── update_leaders ───────────────────────────────────────────────────


def test_leaders_seed_carry_and_drop() -> None:
    states = {"switch.a": "on", "switch.b": "off"}
    leaders = engine.update_leaders(
        {"switch.gone": {"current_value": "on"}},
        ["switch.a", "switch.b"],
        seed_getter=_seed(states, ts=42.0),
    )
    assert "switch.gone" not in leaders  # orphan drops
    assert leaders["switch.a"] == {
        "current_value": "on",
        "previous_value": "",
        "last_changed_timestamp": 42.0,
    }


def test_leaders_changed_chains_previous_value() -> None:
    prev = {
        "switch.a": {
            "current_value": "off",
            "previous_value": "on",
            "last_changed_timestamp": 1.0,
        }
    }
    leaders = engine.update_leaders(
        prev,
        ["switch.a"],
        changed_eid="switch.a",
        cv_raw="on",
        changed_ts=10.0,
        seed_getter=_seed({}),
    )
    assert leaders["switch.a"] == {
        "current_value": "on",
        "previous_value": "off",
        "last_changed_timestamp": 10.0,
    }

    # Same value re-emitted: previous_value stays the older previous.
    leaders2 = engine.update_leaders(
        leaders,
        ["switch.a"],
        changed_eid="switch.a",
        cv_raw="on",
        changed_ts=20.0,
        seed_getter=_seed({}),
    )
    assert leaders2["switch.a"]["previous_value"] == "off"


def test_leaders_skip_values_keep_prior_value_and_timestamp() -> None:
    prev = {
        "event.btn": {
            "current_value": "1_short_release",
            "previous_value": "2_long_press",
            "last_changed_timestamp": 5.0,
        }
    }
    for skip_value in ("dots_1_initial_press", "unknown", "unavailable"):
        leaders = engine.update_leaders(
            prev,
            ["event.btn"],
            changed_eid="event.btn",
            cv_raw=skip_value,
            changed_ts=99.0,
            seed_getter=_seed({}),
        )
        assert leaders["event.btn"] == {
            "current_value": "1_short_release",
            "previous_value": "2_long_press",
            "last_changed_timestamp": 5.0,
        }


def test_leaders_previous_value_sanitizes_skip_values() -> None:
    prev = {
        "event.btn": {
            "current_value": "unknown",
            "previous_value": "",
            "last_changed_timestamp": 1.0,
        }
    }
    leaders = engine.update_leaders(
        prev,
        ["event.btn"],
        changed_eid="event.btn",
        cv_raw="1_short_release",
        changed_ts=10.0,
        seed_getter=_seed({}),
    )
    assert leaders["event.btn"]["previous_value"] == ""


# ── update_snapshots ─────────────────────────────────────────────────


def test_snapshots_merge_delete_passthrough() -> None:
    prev = {"sleep_timeout": {"media_player.bed": 0.45}}

    # Non-snapshot tick: carry through unchanged.
    assert engine.update_snapshots(prev) == prev
    assert engine.update_snapshots(prev, "", {"x": 1}) == prev

    # Set a new snapshot alongside.
    result = engine.update_snapshots(prev, "audio_mood", {"a": 1})
    assert result == {
        "sleep_timeout": {"media_player.bed": 0.45},
        "audio_mood": {"a": 1},
    }

    # Empty payload deletes.
    assert engine.update_snapshots(prev, "sleep_timeout", {}) == {}
    # Non-mapping payload deletes too.
    assert engine.update_snapshots(prev, "sleep_timeout", "junk") == {}


# ── build_label_map ──────────────────────────────────────────────────


def test_label_map_entry_shape_and_default_component() -> None:
    label_map, errors = engine.build_label_map(
        [
            {
                "area_id": "kitchen",
                "floor_id": "first",
                "labels": ["feature_leader", "Area Provides: Audio Mode"],
            },
        ]
    )
    assert errors == []
    assert label_map == {
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


def test_label_map_component_override_and_modifier_filtering() -> None:
    label_map, _ = engine.build_label_map(
        [
            {
                "area_id": "root_zone",
                "floor_id": "",
                "labels": [
                    "Area Provides: Probe",
                    "Area Provides Probe Component: number",
                    "Area Provides Probe Min: 0",  # modifier — never a feature
                    "Area Provides Probe Max: 100",
                    "Area Provides Probe Device Class: pressure",
                ],
            },
        ]
    )
    assert set(label_map) == {"root_zone||Probe"}
    assert label_map["root_zone||Probe"]["component"] == "number"


def test_label_map_floor_dedupe_first_wins() -> None:
    label_map, _ = engine.build_label_map(
        [
            {
                "area_id": "kitchen",
                "floor_id": "first",
                "labels": ["Floor Provides: Audio Mode"],
            },
            {
                "area_id": "living_room",
                "floor_id": "first",
                "labels": ["Floor Provides: Audio Mode"],
            },
        ]
    )
    assert set(label_map) == {"first||Audio Mode"}
    entry = label_map["first||Audio Mode"]
    assert entry["scope"] == "floor"
    assert entry["declaring_area_id"] == "kitchen"  # first declaration wins


def test_label_map_bare_provides_is_none_scope() -> None:
    label_map, _ = engine.build_label_map(
        [
            {
                "area_id": "office",
                "floor_id": "first",
                "labels": ["Provides: House Mode"],
            },
        ]
    )
    entry = label_map["office||House Mode"]
    assert entry["scope"] == "none"
    assert entry["scope_id"] == "office"


def test_label_map_floor_scope_without_floor_errors() -> None:
    label_map, errors = engine.build_label_map(
        [
            {
                "area_id": "garage",
                "floor_id": "",
                "labels": ["Floor Provides: Audio Mode"],
            },
        ]
    )
    assert label_map == {}
    assert len(errors) == 1
    assert errors[0]["key"] == "unresolved_scope"


# ── feature_meta catalog ─────────────────────────────────────────────


def test_feature_meta_catalog_parity() -> None:
    """The catalog must match the legacy template sensor exactly."""
    assert len(FEATURE_META) == 17
    media = [k for k, v in FEATURE_META.items() if v["domain_label"] == "Media Player"]
    assert len(media) == 9
    assert FEATURE_META["Volume Up"] == {
        "domain": "media_player",
        "kind": "volume_up",
        "domain_label": "Media Player",
    }
    assert FEATURE_META["Lights Down"] == {
        "domain": "light",
        "kind": "light_down",
        "domain_label": "Light",
    }
    assert FEATURE_META["Fan Off"] == {
        "domain": "fan",
        "kind": "fan_off",
        "domain_label": "Fan",
    }
    for meta in FEATURE_META.values():
        assert set(meta) == {"domain", "kind", "domain_label"}

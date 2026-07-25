"""Unit tests for the pure feature logic."""

from __future__ import annotations

import pytest

from custom_components.labeled_features.features import (
    LeaderInfo,
    Triple,
    build_feature_entry,
    build_leader_entry,
    build_manual_entry,
    build_triple_map,
    carry_forward,
    current_value_for,
    evaluate_leader,
    fold,
    is_skip_value,
    resolve_mode,
    seed_leader_entry,
    triple_from_key,
)


def leader(**kwargs) -> LeaderInfo:
    """Build a LeaderInfo with sane defaults."""
    kwargs.setdefault("entity_id", "binary_sensor.front_door")
    kwargs.setdefault("state", "off")
    kwargs.setdefault("labels", [])
    kwargs.setdefault("current_value", kwargs["state"])
    kwargs.setdefault("previous_value", "")
    return LeaderInfo(**kwargs)


# ── default truth function ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("on", True),
        ("ON", True),
        ("true", True),
        ("home", True),
        ("open", True),
        ("detected", True),
        ("active", True),
        ("unlocked", True),
        ("off", False),
        ("closed", False),
        ("unknown", False),
    ],
)
def test_default_truth_generic_truthy(state: str, expected: bool) -> None:
    """Generic truthy states are matched case-insensitively."""
    triple = Triple("Night", "global", "")
    assert evaluate_leader(leader(state=state), triple) is expected


def test_default_truth_state_equals_feature_is_case_sensitive() -> None:
    """`state == <Feature>` is the option-style default and is case-sensitive."""
    triple = Triple("Night", "global", "")
    assert evaluate_leader(
        leader(entity_id="input_select.house_mode", state="Night"), triple
    )
    assert not evaluate_leader(
        leader(entity_id="input_select.house_mode", state="night"), triple
    )
    assert not evaluate_leader(
        leader(entity_id="input_select.house_mode", state="Day"), triple
    )


@pytest.mark.parametrize("domain", ["event", "button"])
def test_event_and_button_domains_always_fire(domain: str) -> None:
    """Domains with no persistent state always evaluate to True."""
    triple = Triple("Night Buttons", "area", "tv_room")
    info = leader(entity_id=f"{domain}.somrig", state="2026-01-01T00:00:00+00:00")
    assert evaluate_leader(info, triple) is True


# ── Enable / Disable ────────────────────────────────────────────────────────


def test_enable_label_pins_the_truth_function() -> None:
    """`<F> Enable: <v>` compares against the entity state."""
    triple = Triple("Media Playing", "area", "bedroom_main")
    labels = ["Area Media Playing Enable: playing"]
    assert evaluate_leader(
        leader(entity_id="media_player.a", state="playing", labels=labels), triple
    )
    assert not evaluate_leader(
        leader(entity_id="media_player.a", state="paused", labels=labels), triple
    )


def test_disable_label_alone_inverts_the_match() -> None:
    """A lone Disable label means "anything but this value is enabled"."""
    triple = Triple("Screen", "area", "tv_room")
    labels = ["Area Screen Disable: standby"]
    assert not evaluate_leader(
        leader(entity_id="media_player.tv", state="standby", labels=labels), triple
    )
    assert evaluate_leader(
        leader(entity_id="media_player.tv", state="HDMI1", labels=labels), triple
    )


def test_enable_and_disable_together() -> None:
    """With both labels, Enable must match and Disable must not."""
    triple = Triple("Screen", "global", "")
    labels = ["Screen Enable: HDMI1", "Screen Disable: standby"]
    assert evaluate_leader(leader(state="HDMI1", labels=labels), triple)
    assert not evaluate_leader(leader(state="standby", labels=labels), triple)
    assert not evaluate_leader(leader(state="HDMI2", labels=labels), triple)


def test_enable_disable_ignored_without_scope_prefix() -> None:
    """Optional labels must carry the grouping label's scope prefix."""
    triple = Triple("Screen", "area", "tv_room")
    # Unprefixed label does not apply to an area-scoped triple, so the default
    # truth function runs instead.
    labels = ["Screen Enable: HDMI1"]
    assert not evaluate_leader(leader(state="HDMI1", labels=labels), triple)


# ── direction ────────────────────────────────────────────────────────────────


def test_increasing_and_decreasing() -> None:
    """Direction compares current against previous numerically."""
    triple = Triple("Idle", "area", "office")
    inc = ["Area Idle Increasing: True"]
    dec = ["Area Idle Decreasing: True"]

    def rising(labels: list[str]) -> LeaderInfo:
        return leader(
            entity_id="sensor.idle",
            state="5",
            current_value="5",
            previous_value="3",
            labels=labels,
        )

    def falling(labels: list[str]) -> LeaderInfo:
        return leader(
            entity_id="sensor.idle",
            state="3",
            current_value="3",
            previous_value="5",
            labels=labels,
        )

    assert evaluate_leader(rising(inc), triple)
    assert not evaluate_leader(falling(inc), triple)
    assert evaluate_leader(falling(dec), triple)
    assert not evaluate_leader(rising(dec), triple)


def test_direction_first_update_and_non_numeric_are_false() -> None:
    """No previous value, or non-numeric values, evaluate to False."""
    triple = Triple("Idle", "global", "")
    labels = ["Idle Increasing: True"]
    assert not evaluate_leader(
        leader(entity_id="sensor.idle", state="5", current_value="5", labels=labels),
        triple,
    )
    assert not evaluate_leader(
        leader(
            entity_id="sensor.idle",
            state="high",
            current_value="high",
            previous_value="low",
            labels=labels,
        ),
        triple,
    )


def test_direction_takes_precedence_over_enable() -> None:
    """Direction wins over Enable/Disable labels."""
    triple = Triple("Idle", "global", "")
    info = leader(
        entity_id="sensor.idle",
        state="5",
        current_value="5",
        previous_value="9",
        labels=["Idle Increasing: True", "Idle Enable: 5"],
    )
    # Direction says decreasing -> False, even though Enable: 5 would match.
    assert evaluate_leader(info, triple) is False


def test_invert_applies_after_everything() -> None:
    """Invert flips the final result."""
    triple = Triple("Night", "global", "")
    assert not evaluate_leader(
        leader(state="on", labels=["Night Invert: True"]), triple
    )
    assert evaluate_leader(leader(state="off", labels=["Night Invert: True"]), triple)


# ── leaders attribute ────────────────────────────────────────────────────────


def test_current_value_for_event_domain_uses_event_type() -> None:
    """Event entities expose the meaningful value as an attribute."""
    assert (
        current_value_for(
            "event.somrig", "2026-01-01T00:00:00+00:00", {"event_type": "1_long_press"}
        )
        == "1_long_press"
    )
    assert current_value_for("binary_sensor.a", "on", {}) == "on"


@pytest.mark.parametrize(
    "value", ["1_initial_press", "unknown", "unavailable", "None", "none"]
)
def test_skip_values(value: str) -> None:
    """Initial presses and unreal states are skip values."""
    assert is_skip_value(value)


def test_build_leader_entry_tracks_previous_value() -> None:
    """A real change moves current into previous."""
    previous = {
        "current_value": "off",
        "previous_value": "on",
        "last_changed_timestamp": 100.0,
    }
    entry = build_leader_entry(previous, "on", 200.0)
    assert entry == {
        "current_value": "on",
        "previous_value": "off",
        "last_changed_timestamp": 200.0,
    }


def test_build_leader_entry_repeat_value_keeps_previous() -> None:
    """The same value twice keeps the stored previous value."""
    previous = {
        "current_value": "1_short_release",
        "previous_value": "2_short_release",
        "last_changed_timestamp": 100.0,
    }
    entry = build_leader_entry(previous, "1_short_release", 200.0)
    assert entry["previous_value"] == "2_short_release"
    assert entry["last_changed_timestamp"] == 200.0


def test_build_leader_entry_skip_value_carries_forward() -> None:
    """Skip values do not overwrite the tracked value or timestamp."""
    previous = {
        "current_value": "1_long_press",
        "previous_value": "",
        "last_changed_timestamp": 100.0,
    }
    entry = build_leader_entry(previous, "1_initial_press", 200.0)
    assert entry == {
        "current_value": "1_long_press",
        "previous_value": "",
        "last_changed_timestamp": 100.0,
    }


def test_build_leader_entry_blanks_skip_ish_previous() -> None:
    """A skip-ish previous value is blanked rather than surfaced."""
    previous = {
        "current_value": "unknown",
        "previous_value": "",
        "last_changed_timestamp": 1.0,
    }
    entry = build_leader_entry(previous, "on", 2.0)
    assert entry["previous_value"] == ""


def test_seed_leader_entry() -> None:
    """Newly labeled leaders start with an empty previous value."""
    assert seed_leader_entry("on", 5.0) == {
        "current_value": "on",
        "previous_value": "",
        "last_changed_timestamp": 5.0,
    }


# ── triple map ───────────────────────────────────────────────────────────────


def test_build_triple_map_scopes() -> None:
    """Grouping labels map to the right scope and scope_id."""
    leaders = [
        leader(
            entity_id="binary_sensor.door",
            labels=["Area Leader: Fan", "Floor Leader: Night", "Leader: Away"],
            area_id="tv_room",
            floor_id="first_floor",
        )
    ]
    triples = build_triple_map(leaders)
    assert set(triples) == {
        "Fan||area||tv_room",
        "Night||floor||first_floor",
        "Away||global||",
    }
    assert triples["Fan||area||tv_room"] == ["binary_sensor.door"]


def test_build_triple_map_skips_unresolvable_scopes() -> None:
    """Area/floor scoped labels need a resolvable id."""
    leaders = [
        leader(
            entity_id="binary_sensor.door",
            labels=["Area Leader: Fan", "Floor Leader: Night", "Leader: Away"],
        )
    ]
    assert set(build_triple_map(leaders)) == {"Away||global||"}


def test_build_triple_map_groups_multiple_leaders() -> None:
    """Two leaders of the same triple are collected together."""
    leaders = [
        leader(entity_id="binary_sensor.a", labels=["Leader: Open Door"]),
        leader(entity_id="binary_sensor.b", labels=["Leader: Open Door"]),
    ]
    assert build_triple_map(leaders)["Open Door||global||"] == [
        "binary_sensor.a",
        "binary_sensor.b",
    ]


def test_follower_labels_are_not_leader_triples() -> None:
    """Follower labels never create triples."""
    leaders = [leader(entity_id="light.a", labels=["Area Follower: Night"])]
    assert build_triple_map(leaders) == {}


def test_triple_key_round_trip() -> None:
    """Triple keys survive a round trip, including empty scope ids."""
    triple = Triple("Night", "global", "")
    assert triple_from_key(triple.key) == triple


# ── mode resolution ─────────────────────────────────────────────────────────


def test_resolve_mode_precedence() -> None:
    """Sensor labels beat option overrides, which beat the entry default."""
    triple = Triple("Night", "floor", "first_floor")
    assert (
        resolve_mode(
            triple, ["Floor Night Mode: All"], {"Floor Night": "any"}, "leader"
        )
        == "all"
    )
    assert resolve_mode(triple, [], {"Floor Night": "any"}, "leader") == "any"
    assert resolve_mode(triple, [], {}, "all") == "all"
    assert resolve_mode(triple, [], {}, "") == "leader"


def test_resolve_mode_ignores_wrong_scope_and_bad_values() -> None:
    """Scope prefix and mode spelling are both significant."""
    triple = Triple("Night", "floor", "first_floor")
    assert resolve_mode(triple, ["Area Night Mode: All"], {}, "leader") == "leader"
    assert resolve_mode(triple, ["Floor Night Mode: all"], {}, "leader") == "leader"


@pytest.mark.parametrize(
    ("mode", "values", "expected"),
    [
        ("any", [False, True], True),
        ("any", [False, False], False),
        ("all", [True, True], True),
        ("all", [True, False], False),
        ("leader", [True], True),
        ("leader", [False], False),
        ("any", [], False),
    ],
)
def test_fold(mode: str, values: list[bool], expected: bool) -> None:
    """Folding matches the documented Any/All semantics."""
    assert fold(mode, values) is expected


# ── features entries ────────────────────────────────────────────────────────


def test_feature_entry_bumps_timestamp_only_on_flip() -> None:
    """A steady value keeps its previous timestamp."""
    previous = {
        "enabled": True,
        "mode": "leader",
        "last_changed_timestamp": 100.0,
        "triggering_leader": "binary_sensor.a",
    }
    same = build_feature_entry(previous, True, "leader", 200.0, "binary_sensor.a")
    assert same["last_changed_timestamp"] == 100.0
    flipped = build_feature_entry(previous, False, "leader", 200.0, "binary_sensor.a")
    assert flipped["last_changed_timestamp"] == 200.0


def test_feature_entry_always_bumps_for_button_leaders() -> None:
    """Every accepted button press is a distinct dispatch."""
    previous = {
        "enabled": True,
        "mode": "leader",
        "last_changed_timestamp": 100.0,
        "triggering_leader": "event.somrig",
    }
    entry = build_feature_entry(previous, True, "leader", 200.0, "event.somrig")
    assert entry["last_changed_timestamp"] == 200.0


def test_feature_entry_first_seed_bumps() -> None:
    """A brand new entry stamps the current timestamp."""
    entry = build_feature_entry(None, False, "leader", 200.0, "binary_sensor.a")
    assert entry == {
        "enabled": False,
        "mode": "leader",
        "last_changed_timestamp": 200.0,
        "triggering_leader": "binary_sensor.a",
    }


def test_manual_entry_preserves_mode_and_blanks_leader() -> None:
    """Manual overrides keep the mode and carry an empty triggering leader."""
    previous = {
        "enabled": False,
        "mode": "all",
        "last_changed_timestamp": 1.0,
        "triggering_leader": "binary_sensor.a",
    }
    entry = build_manual_entry(previous, True, 2.0)
    assert entry == {
        "enabled": True,
        "mode": "all",
        "last_changed_timestamp": 2.0,
        "triggering_leader": "",
    }
    assert build_manual_entry(None, True, 2.0)["mode"] == "leader"


def test_carry_forward_drops_orphans_but_keeps_manual() -> None:
    """Orphaned leader entries drop; manual entries are exempt."""
    features = {
        "Night": {
            "global": {
                "": {
                    "enabled": True,
                    "mode": "leader",
                    "last_changed_timestamp": 1.0,
                    "triggering_leader": "binary_sensor.gone",
                }
            }
        },
        "Manual Only": {
            "global": {
                "": {
                    "enabled": True,
                    "mode": "leader",
                    "last_changed_timestamp": 1.0,
                    "triggering_leader": "",
                }
            }
        },
        "Screen": {
            "area": {
                "tv_room": {
                    "enabled": False,
                    "mode": "leader",
                    "last_changed_timestamp": 1.0,
                    "triggering_leader": "sensor.idle",
                }
            }
        },
    }
    result = carry_forward(features, {"Screen||area||tv_room": ["sensor.idle"]})
    assert set(result) == {"Manual Only", "Screen"}


def test_carry_forward_tolerates_legacy_shapes() -> None:
    """Non-mapping values from an old schema are ignored, not fatal."""
    assert carry_forward({"Night": "garbage"}, {}) == {}
    assert carry_forward("garbage", {}) == {}

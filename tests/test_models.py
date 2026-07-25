"""Round-trip tests for the models module."""

from __future__ import annotations

from custom_components.labeled_features.models import (
    FeatureEntry,
    LabeledFeaturesStateData,
    LabelMapEntry,
    LeaderEntry,
)


def test_leader_entry_roundtrip() -> None:
    original = LeaderEntry(
        current_value="on", previous_value="off", last_changed_timestamp=123.45
    )
    restored = LeaderEntry.from_dict(original.to_dict())
    assert restored == original


def test_feature_entry_roundtrip() -> None:
    original = FeatureEntry(
        enabled=True,
        mode="any",
        last_changed_timestamp=999.0,
        triggering_leader="sensor.foo",
    )
    restored = FeatureEntry.from_dict(original.to_dict())
    assert restored == original


def test_label_map_entry_shape() -> None:
    entry = LabelMapEntry(
        scope_id="kitchen",
        label="Audio Mode",
        scope="area",
        component="select",
        declaring_area_id="kitchen",
    )
    payload = entry.to_dict()
    assert payload["scope_id"] == "kitchen"
    assert payload["label"] == "Audio Mode"
    assert payload["scope"] == "area"
    assert payload["component"] == "select"
    assert payload["declaring_area_id"] == "kitchen"
    # Nested label_data preserves everything for the automation.
    assert payload["label_data"] == {
        "scope": "area",
        "scope_id": "kitchen",
        "component": "select",
        "declaring_area_id": "kitchen",
    }


def test_state_data_restore_round_trip() -> None:
    data = LabeledFeaturesStateData()
    data.leaders["sensor.a"] = LeaderEntry(
        current_value="on", previous_value="off", last_changed_timestamp=1.0
    )
    data.features["Night"] = {
        "global": {"": FeatureEntry(enabled=True, mode="leader", last_changed_timestamp=2.0)}
    }
    data.snapshots["sleep_timeout"] = {"media_player.bedroom": 0.45}

    payload = data.to_restore()
    restored = LabeledFeaturesStateData()
    restored.apply_restore(payload)

    assert restored.leaders == data.leaders
    assert restored.features["Night"]["global"][""] == data.features["Night"]["global"][""]
    assert restored.snapshots == data.snapshots


def test_state_data_restore_handles_missing_and_malformed() -> None:
    data = LabeledFeaturesStateData()
    # None payload — no-op.
    data.apply_restore(None)
    # Wrong types get coerced away rather than crashing.
    data.apply_restore({"leaders": "not-a-dict", "features": [1, 2], "snapshots": None})
    assert data.leaders == {}
    assert data.features == {}
    assert data.snapshots == {}

"""Tests for the features-state coordinator.

Split into three concerns:
- _eval_leader truth-function table.
- Manual-override + snapshot event handling (independent of registries).
- End-to-end state_changed dispatch against a real registry fixture.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    label_registry as lr,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.labeled_features.const import (
    CONF_AREAS_STATE_ENTITY_ID,
    CONF_ERROR_MODE_DEFAULT,
    CONF_FEATURES_STATE_ENTITY_ID,
    CONF_INSTANCE_NAME,
    CONF_LEADER_LABEL,
    CONF_SCRIPT_CALL_MODE_DEFAULT,
    DEFAULT_LEADER_LABEL,
    DOMAIN,
    EVENT_LABELED_FEATURE_SET,
)
from custom_components.labeled_features.coordinator.features import (
    LabeledFeaturesStateCoordinator,
)


def _make_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_INSTANCE_NAME: "Labeled Features",
            CONF_LEADER_LABEL: DEFAULT_LEADER_LABEL,
            CONF_FEATURES_STATE_ENTITY_ID: "sensor.labeled_features_state",
            CONF_AREAS_STATE_ENTITY_ID: "sensor.labeled_feature_areas_state",
            CONF_ERROR_MODE_DEFAULT: "log",
            CONF_SCRIPT_CALL_MODE_DEFAULT: "Blocking",
        },
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def coord(hass: HomeAssistant) -> LabeledFeaturesStateCoordinator:
    return LabeledFeaturesStateCoordinator(hass, _make_entry(hass))


# ── _eval_leader table ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "labels,domain,state_value,current,previous,expected",
    [
        # Default truth — button/event domain always true.
        ([], "button", "unused", "unused", "", True),
        ([], "event", "unused", "unused", "", True),
        # Default truth — state == feature name.
        ([], "input_select", "Night", "Night", "", True),
        # Default truth — state in truthy set.
        ([], "binary_sensor", "on", "on", "", True),
        ([], "binary_sensor", "off", "off", "", False),
        # Enable label overrides default truth.
        (["Night Enable: cool"], "input_select", "cool", "cool", "", True),
        (["Night Enable: cool"], "input_select", "warm", "warm", "", False),
        # Disable label — matches → false, no match → true (subtle!).
        (["Night Disable: cool"], "input_select", "cool", "cool", "", False),
        (["Night Disable: cool"], "input_select", "warm", "warm", "", True),
        # Enable + Disable: enable wins, disable overrides.
        (["Night Enable: cool", "Night Disable: warm"], "input_select", "cool", "cool", "", True),
        # Increasing direction.
        (["Volume Increasing: True"], "sensor", "5", "5", "3", True),
        (["Volume Increasing: True"], "sensor", "5", "5", "5", False),
        (["Volume Increasing: True"], "sensor", "1", "1", "3", False),
        # Decreasing direction.
        (["Volume Decreasing: True"], "sensor", "1", "1", "3", True),
        (["Volume Decreasing: True"], "sensor", "3", "3", "1", False),
        # Both directions — OR.
        (
            ["Volume Increasing: True", "Volume Decreasing: True"],
            "sensor",
            "1",
            "1",
            "3",
            True,
        ),
        # Non-numeric current → not enabled even with direction.
        (["Volume Increasing: True"], "sensor", "abc", "abc", "1", False),
        # Invert after default truth.
        (["Night Invert: True"], "input_select", "Night", "Night", "", False),
        (["Night Invert: True"], "input_select", "Day", "Day", "", True),
    ],
)
def test_eval_leader_table(
    hass: HomeAssistant,
    coord: LabeledFeaturesStateCoordinator,
    labels: list[str],
    domain: str,
    state_value: str,
    current: str,
    previous: str,
    expected: bool,
) -> None:
    fname = labels[0].split(" ")[0] if labels else "Night"
    # Coerce feature name to first label's leading word for direction /
    # enable / disable / invert cases (they all start with the feature
    # name). Default-truth rows use "Night" explicitly.
    if labels and labels[0].split()[0] not in ("Volume", "Night"):
        fname = "Night"
    if not labels:
        fname = "Night"
    else:
        fname = labels[0].split()[0]

    entity_id = f"{domain}.test_leader"
    hass.states.async_set(entity_id, state_value)

    with patch(
        "custom_components.labeled_features.coordinator.features.entity_labels",
        return_value=labels,
    ):
        result = coord._eval_leader(entity_id, "", fname, current, previous)
    assert result is expected


# ── Manual override event ──────────────────────────────────────────────


async def test_manual_override_writes_feature_entry(
    hass: HomeAssistant, coord: LabeledFeaturesStateCoordinator
) -> None:
    hass.bus.async_fire(
        EVENT_LABELED_FEATURE_SET,
        {
            "target_feature": "Night",
            "scope": "global",
            "scope_id": "",
            "enabled": True,
            "timestamp": 1234.5,
        },
    )
    await hass.async_block_till_done()
    # Handler is registered via async_subscribe only in setup; call directly.
    coord._apply_manual_override(
        {
            "target_feature": "Night",
            "scope": "global",
            "scope_id": "",
            "enabled": True,
            "timestamp": 1234.5,
        }
    )
    assert coord.data.features["Night"]["global"][""].enabled is True
    assert coord.data.features["Night"]["global"][""].triggering_leader == ""
    assert coord.data.features["Night"]["global"][""].last_changed_timestamp == 1234.5


async def test_manual_override_preserves_existing_mode(
    coord: LabeledFeaturesStateCoordinator,
) -> None:
    coord._apply_manual_override(
        {"target_feature": "Night", "scope": "global", "scope_id": "", "enabled": True}
    )
    # Simulate a mode set from an earlier leader tick.
    coord.data.features["Night"]["global"][""].mode = "any"
    coord._apply_manual_override(
        {"target_feature": "Night", "scope": "global", "scope_id": "", "enabled": False}
    )
    assert coord.data.features["Night"]["global"][""].mode == "any"


async def test_manual_override_bad_scope_ignored(
    coord: LabeledFeaturesStateCoordinator,
) -> None:
    coord._apply_manual_override(
        {"target_feature": "Night", "scope": "not-a-scope", "enabled": True}
    )
    assert "Night" not in coord.data.features


# ── Snapshot event ─────────────────────────────────────────────────────


async def test_snapshot_write_and_delete(
    coord: LabeledFeaturesStateCoordinator,
) -> None:
    coord._apply_snapshot(
        {"snapshot_name": "sleep_timeout", "payload": {"media_player.bedroom": 0.45}}
    )
    assert coord.data.snapshots["sleep_timeout"] == {"media_player.bedroom": 0.45}
    coord._apply_snapshot({"snapshot_name": "sleep_timeout", "payload": {}})
    assert "sleep_timeout" not in coord.data.snapshots


async def test_snapshot_missing_name_ignored(
    coord: LabeledFeaturesStateCoordinator,
) -> None:
    coord._apply_snapshot({"snapshot_name": "", "payload": {"a": 1}})
    assert coord.data.snapshots == {}


# ── Triple index and orphan drop ───────────────────────────────────────


def _setup_leader_entity(
    hass: HomeAssistant,
    *,
    entity_id: str,
    labels: list[str],
    area_id: str | None = None,
) -> None:
    lbl_reg = lr.async_get(hass)
    label_ids: set[str] = set()
    for name in labels:
        existing = lbl_reg.async_get_label_by_name(name)
        entry = existing if existing is not None else lbl_reg.async_create(name=name)
        label_ids.add(entry.label_id)
    ent_reg = er.async_get(hass)
    # Register the entity minimally.
    if ent_reg.async_get(entity_id) is None:
        ent_reg.async_get_or_create(
            entity_id.split(".", 1)[0],
            "test",
            entity_id.split(".", 1)[1],
            suggested_object_id=entity_id.split(".", 1)[1],
        )
    ent_reg.async_update_entity(entity_id, labels=label_ids, area_id=area_id)


async def test_entity_labels_excludes_device_labels(
    hass: HomeAssistant,
) -> None:
    """Regression: `entity_labels` must NOT union device labels.

    HA's `labels(<entity_id>)` template helper returns only the entity's
    own labels. If we included the device's labels, a `Leader:` label on
    the device would silently promote every entity on that device to a
    leader, producing a strictly larger `features` output than the
    Jinja source-of-truth.
    """

    from homeassistant.helpers import device_registry as dr

    from custom_components.labeled_features.registry_helpers import entity_labels

    mock_entry = MockConfigEntry(domain="labeled_features_test", data={})
    mock_entry.add_to_hass(hass)

    lbl_reg = lr.async_get(hass)
    ent_only = lbl_reg.async_create(name="entity_only")
    dev_only = lbl_reg.async_create(name="device_only")

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=mock_entry.entry_id,
        identifiers={("test", "abc")},
    )
    dev_reg.async_update_device(device.id, labels={dev_only.label_id})

    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create(
        domain="sensor",
        platform="test",
        unique_id="via_device",
        device_id=device.id,
    )
    ent_reg.async_update_entity(entry.entity_id, labels={ent_only.label_id})

    labels = entity_labels(hass, entry.entity_id)
    assert "entity_only" in labels
    assert "device_only" not in labels


async def test_triple_index_area_and_global_and_orphan_drop(
    hass: HomeAssistant, coord: LabeledFeaturesStateCoordinator
) -> None:
    area_reg = ar.async_get(hass)
    kitchen = area_reg.async_create("Kitchen")
    _setup_leader_entity(
        hass,
        entity_id="binary_sensor.kitchen_leader",
        labels=["feature_leader", "Area Leader: Screen"],
        area_id=kitchen.id,
    )
    _setup_leader_entity(
        hass,
        entity_id="binary_sensor.global_leader",
        labels=["feature_leader", "Leader: Night"],
    )

    triples = coord._build_triple_index()
    assert ("Screen", "area", kitchen.id) in triples
    assert ("Night", "global", "") in triples

    # Seed an orphan feature entry and confirm reconcile drops it.
    from custom_components.labeled_features.models import FeatureEntry

    coord.data.features.setdefault("Ghost", {}).setdefault("area", {})["nowhere"] = (
        FeatureEntry(enabled=True, mode="leader", triggering_leader="binary_sensor.ghost")
    )
    coord._reconcile_leaders_and_orphans()
    assert "Ghost" not in coord.data.features


async def test_orphan_drop_preserves_manual_entries(
    coord: LabeledFeaturesStateCoordinator,
) -> None:
    coord._apply_manual_override(
        {"target_feature": "Night", "scope": "global", "scope_id": "", "enabled": True}
    )
    # No leader mapped anywhere.
    coord._drop_orphans(triple_map={})
    assert "Night" in coord.data.features
    assert coord.data.features["Night"]["global"][""].triggering_leader == ""

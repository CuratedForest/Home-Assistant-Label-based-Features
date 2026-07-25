"""Tests for the areas-state coordinator's label_map compute."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    floor_registry as fr,
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
)
from custom_components.labeled_features.coordinator.areas import (
    LabeledFeatureAreasStateCoordinator,
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
def coord(hass: HomeAssistant) -> LabeledFeatureAreasStateCoordinator:
    entry = _make_entry(hass)
    return LabeledFeatureAreasStateCoordinator(hass, entry)


def _apply_labels(hass: HomeAssistant, area_id: str, names: list[str]) -> None:
    lbl_reg = lr.async_get(hass)
    label_ids: set[str] = set()
    for name in names:
        existing = lbl_reg.async_get_label_by_name(name)
        entry = existing if existing is not None else lbl_reg.async_create(name=name)
        label_ids.add(entry.label_id)
    area_reg = ar.async_get(hass)
    area_reg.async_update(area_id, labels=label_ids)


async def test_empty_registry_returns_empty(
    hass: HomeAssistant, coord: LabeledFeatureAreasStateCoordinator
) -> None:
    assert coord._compute_sync() == {}


async def test_area_provides_creates_entry(
    hass: HomeAssistant, coord: LabeledFeatureAreasStateCoordinator
) -> None:
    area_reg = ar.async_get(hass)
    area = area_reg.async_create("Kitchen")
    _apply_labels(hass, area.id, ["feature_leader", "Area Provides: Audio Mode"])

    result = coord._compute_sync()
    key = f"{area.id}||Audio Mode"
    assert key in result
    assert result[key]["scope"] == "area"
    assert result[key]["scope_id"] == area.id
    assert result[key]["component"] == "select"
    assert result[key]["declaring_area_id"] == area.id


async def test_floor_provides_uses_floor_scope_id(
    hass: HomeAssistant, coord: LabeledFeatureAreasStateCoordinator
) -> None:
    fr_reg = fr.async_get(hass)
    floor = fr_reg.async_create("First Floor")
    area_reg = ar.async_get(hass)
    area = area_reg.async_create("Living Room")
    area_reg.async_update(area.id, floor_id=floor.floor_id)
    _apply_labels(hass, area.id, ["feature_leader", "Floor Provides: Audio Mode"])

    result = coord._compute_sync()
    key = f"{floor.floor_id}||Audio Mode"
    assert key in result
    assert result[key]["scope"] == "floor"
    assert result[key]["scope_id"] == floor.floor_id
    assert result[key]["declaring_area_id"] == area.id


async def test_bare_provides_uses_area_scope_id_and_none_scope(
    hass: HomeAssistant, coord: LabeledFeatureAreasStateCoordinator
) -> None:
    area_reg = ar.async_get(hass)
    area = area_reg.async_create("Kitchen")
    _apply_labels(hass, area.id, ["feature_leader", "Provides: Audio Mode"])

    result = coord._compute_sync()
    key = f"{area.id}||Audio Mode"
    assert key in result
    assert result[key]["scope"] == "none"
    assert result[key]["scope_id"] == area.id


async def test_component_override_applies(
    hass: HomeAssistant, coord: LabeledFeatureAreasStateCoordinator
) -> None:
    area_reg = ar.async_get(hass)
    area = area_reg.async_create("Grow Room")
    _apply_labels(
        hass,
        area.id,
        [
            "feature_leader",
            "Area Provides: Root Zone",
            "Area Provides Root Zone Component: number",
        ],
    )

    result = coord._compute_sync()
    key = f"{area.id}||Root Zone"
    assert result[key]["component"] == "number"


async def test_modifier_labels_are_ignored(
    hass: HomeAssistant, coord: LabeledFeatureAreasStateCoordinator
) -> None:
    area_reg = ar.async_get(hass)
    area = area_reg.async_create("Grow Room")
    _apply_labels(
        hass,
        area.id,
        [
            "feature_leader",
            "Area Provides: Audio Mode",
            # These would look like Provides labels for a naive matcher;
            # they should NOT become their own entries because they are
            # modifier labels for the Audio Mode entry.
            "Area Provides: Audio Mode Component: number",
            "Area Provides: Audio Mode Icon: mdi:foo",
        ],
    )

    result = coord._compute_sync()
    # Only the base label produced an entry.
    keys = [k for k in result if "Audio Mode" in k]
    assert keys == [f"{area.id}||Audio Mode"]


async def test_area_without_leader_label_ignored(
    hass: HomeAssistant, coord: LabeledFeatureAreasStateCoordinator
) -> None:
    area_reg = ar.async_get(hass)
    area = area_reg.async_create("Ungated")
    _apply_labels(hass, area.id, ["Area Provides: Audio Mode"])
    assert coord._compute_sync() == {}


async def test_floor_scope_dedupe_across_areas(
    hass: HomeAssistant, coord: LabeledFeatureAreasStateCoordinator
) -> None:
    fr_reg = fr.async_get(hass)
    floor = fr_reg.async_create("First Floor")
    area_reg = ar.async_get(hass)
    area_a = area_reg.async_create("Living Room")
    area_b = area_reg.async_create("Kitchen")
    area_reg.async_update(area_a.id, floor_id=floor.floor_id)
    area_reg.async_update(area_b.id, floor_id=floor.floor_id)
    _apply_labels(hass, area_a.id, ["feature_leader", "Floor Provides: Audio Mode"])
    _apply_labels(hass, area_b.id, ["feature_leader", "Floor Provides: Audio Mode"])

    result = coord._compute_sync()
    matching = [k for k in result if k.endswith("||Audio Mode")]
    assert len(matching) == 1
    assert matching[0] == f"{floor.floor_id}||Audio Mode"


async def test_floor_scope_without_floor_dropped(
    hass: HomeAssistant, coord: LabeledFeatureAreasStateCoordinator
) -> None:
    area_reg = ar.async_get(hass)
    area = area_reg.async_create("Floating")
    # No floor assigned.
    _apply_labels(hass, area.id, ["feature_leader", "Floor Provides: Audio Mode"])
    result = coord._compute_sync()
    assert result == {}


async def test_custom_leader_label_isolates_instances(
    hass: HomeAssistant,
) -> None:
    entry_prod = MockConfigEntry(
        domain=DOMAIN,
        unique_id="prod",
        data={
            CONF_INSTANCE_NAME: "Prod",
            CONF_LEADER_LABEL: "feature_leader",
            CONF_FEATURES_STATE_ENTITY_ID: "sensor.labeled_features_state",
            CONF_AREAS_STATE_ENTITY_ID: "sensor.labeled_feature_areas_state",
            CONF_ERROR_MODE_DEFAULT: "log",
            CONF_SCRIPT_CALL_MODE_DEFAULT: "Blocking",
        },
    )
    entry_prod.add_to_hass(hass)
    entry_test = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test",
        data={
            CONF_INSTANCE_NAME: "Test",
            CONF_LEADER_LABEL: "feature_leader_test",
            CONF_FEATURES_STATE_ENTITY_ID: "sensor.labeled_features_state_test",
            CONF_AREAS_STATE_ENTITY_ID: "sensor.labeled_feature_areas_state_test",
            CONF_ERROR_MODE_DEFAULT: "log",
            CONF_SCRIPT_CALL_MODE_DEFAULT: "Blocking",
        },
    )
    entry_test.add_to_hass(hass)
    coord_prod = LabeledFeatureAreasStateCoordinator(hass, entry_prod)
    coord_test = LabeledFeatureAreasStateCoordinator(hass, entry_test)

    area_reg = ar.async_get(hass)
    area = area_reg.async_create("Kitchen")
    _apply_labels(hass, area.id, ["feature_leader", "Area Provides: Audio Mode"])
    prod_result = coord_prod._compute_sync()
    test_result = coord_test._compute_sync()
    assert list(prod_result.keys()) == [f"{area.id}||Audio Mode"]
    assert test_result == {}

"""Tests for the registry/label helpers.

These mirror the Home Assistant template functions the legacy sensors used, so
they are contract-critical: `labels()` must not inherit device labels, while
`area_id()` must fall back to the device's area.
"""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.labeled_features.labels import (
    Registries,
    area_floor_id,
    entity_area_id,
    entity_floor_id,
    entity_label_names,
    label_areas,
    label_entities,
    parse_grouping_label,
    parse_provides_label,
    resolve_label_id,
    scoped_feature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import create_area, create_floor, label_ids, register_entity


async def test_labels_are_not_inherited_from_devices(hass: HomeAssistant) -> None:
    """Device labels never leak onto the entity's label set."""
    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("test", "abc")},
    )
    dr.async_get(hass).async_update_device(
        device.id, labels=label_ids(hass, ["Device Only"])
    )
    entity = er.async_get(hass).async_get_or_create(
        domain="binary_sensor",
        platform="test",
        unique_id="door",
        device_id=device.id,
    )
    er.async_get(hass).async_update_entity(
        entity.entity_id, labels=label_ids(hass, ["Leader: Open Door"])
    )

    regs = Registries.async_get(hass)
    assert entity_label_names(regs, entity.entity_id) == ["Leader: Open Door"]


async def test_area_falls_back_to_the_device_area(hass: HomeAssistant) -> None:
    """The recommended setup puts the area on the device."""
    floor = create_floor(hass, "First Floor")
    area = create_area(hass, "TV Room", floor_id=floor.floor_id)

    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("test", "abc")},
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    entity = er.async_get(hass).async_get_or_create(
        domain="binary_sensor",
        platform="test",
        unique_id="door",
        device_id=device.id,
    )

    regs = Registries.async_get(hass)
    assert entity_area_id(regs, entity.entity_id) == area.id
    assert entity_floor_id(regs, entity.entity_id) == floor.floor_id


async def test_entity_area_overrides_the_device_area(hass: HomeAssistant) -> None:
    """An explicit entity area wins."""
    device_area = create_area(hass, "TV Room")
    entity_area = create_area(hass, "Office")

    entry = MockConfigEntry(domain="test")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("test", "abc")},
    )
    dr.async_get(hass).async_update_device(device.id, area_id=device_area.id)
    created = er.async_get(hass).async_get_or_create(
        domain="binary_sensor",
        platform="test",
        unique_id="door",
        device_id=device.id,
    )
    er.async_get(hass).async_update_entity(created.entity_id, area_id=entity_area.id)

    regs = Registries.async_get(hass)
    assert entity_area_id(regs, created.entity_id) == entity_area.id


async def test_missing_entity_and_area_resolve_to_empty(hass: HomeAssistant) -> None:
    """Unknown ids never raise."""
    regs = Registries.async_get(hass)
    assert entity_area_id(regs, "binary_sensor.nope") == ""
    assert entity_floor_id(regs, "binary_sensor.nope") == ""
    assert area_floor_id(regs, "") == ""
    assert area_floor_id(regs, "nope") == ""
    assert entity_label_names(regs, "binary_sensor.nope") == []


async def test_label_lookup_accepts_ids_and_names(hass: HomeAssistant) -> None:
    """Label lookup matches the template helpers' id-or-name behavior.

    The documented label is named `Feature Leader`, which Home Assistant slugs
    to the `feature_leader` label id the legacy YAML passed to
    `label_entities()`. Both spellings must resolve to the same label so an
    existing setup keeps working after the default changed to the label name.
    """
    register_entity(hass, "binary_sensor.door", labels=["Feature Leader"])
    create_area(hass, "Kitchen", labels=["Feature Leader"])
    regs = Registries.async_get(hass)

    assert resolve_label_id(regs, "Feature Leader") == "feature_leader"
    assert resolve_label_id(regs, "feature_leader") == "feature_leader"
    for lookup in ("Feature Leader", "feature_leader"):
        assert label_entities(regs, lookup) == ["binary_sensor.door"]
        assert len(label_areas(regs, lookup)) == 1
    assert label_entities(regs, "does_not_exist") == []
    assert label_areas(regs, "does_not_exist") == []
    assert resolve_label_id(regs, "") is None


def test_parse_grouping_label() -> None:
    """Grouping labels parse into scope + feature, by role."""
    assert parse_grouping_label("Area Leader: Fan", "Leader") == ("area", "Fan")
    assert parse_grouping_label("Floor Leader: Night", "Leader") == ("floor", "Night")
    assert parse_grouping_label("Leader: Away", "Leader") == ("global", "Away")
    assert parse_grouping_label("Area Follower: Fan", "Leader") is None
    assert parse_grouping_label("Area Follower: Fan", "Follower") == ("area", "Fan")
    assert parse_grouping_label("Leader:", "Leader") is None
    assert parse_grouping_label("Something else", "Leader") is None
    # Feature names may contain spaces and colons after the first one.
    assert parse_grouping_label("Area Leader: Media Playing", "Leader") == (
        "area",
        "Media Playing",
    )


def test_parse_provides_label() -> None:
    """Provides labels keep the raw prefix for the caller to map."""
    assert parse_provides_label("Area Provides: Audio Mode") == ("Area", "Audio Mode")
    assert parse_provides_label("Floor Provides: Audio Mode") == (
        "Floor",
        "Audio Mode",
    )
    assert parse_provides_label("Provides: Shoot Zone") == ("", "Shoot Zone")
    assert parse_provides_label("Provides Option: Audio Mode") is None
    assert parse_provides_label("Area Leader: Fan") is None


def test_scoped_feature() -> None:
    """Scoped feature keys carry the label prefix."""
    assert scoped_feature("area", "Night") == "Area Night"
    assert scoped_feature("floor", "Night") == "Floor Night"
    assert scoped_feature("global", "Night") == "Night"
    assert scoped_feature("none", "Night") == "Night"

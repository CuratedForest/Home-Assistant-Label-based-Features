"""Tests for the areas label_map builder."""

from __future__ import annotations

from custom_components.labeled_features.areas import (
    build_label_map,
    is_modifier_label_value,
)
from custom_components.labeled_features.const import DEFAULT_LEADER_LABEL
from custom_components.labeled_features.labels import Registries
from homeassistant.core import HomeAssistant

from .conftest import create_area, create_floor


def label_map(hass: HomeAssistant) -> dict:
    """Build the label map with the default leader label."""
    return build_label_map(Registries.async_get(hass), DEFAULT_LEADER_LABEL)


async def test_area_scope(hass: HomeAssistant) -> None:
    """`Area Provides:` yields area scope keyed on the declaring area."""
    area = create_area(
        hass, "Kitchen", labels=[DEFAULT_LEADER_LABEL, "Area Provides: Audio Mode"]
    )
    result = label_map(hass)
    key = f"{area.id}||Audio Mode"
    assert set(result) == {key}
    assert result[key] == {
        "scope_id": area.id,
        "label": "Audio Mode",
        "scope": "area",
        "component": "select",
        "declaring_area_id": area.id,
        "label_data": {
            "scope": "area",
            "scope_id": area.id,
            "component": "select",
            "declaring_area_id": area.id,
        },
    }


async def test_bare_provides_is_none_scope_on_the_declaring_area(
    hass: HomeAssistant,
) -> None:
    """The bare form lives in the area but consumes the global pool."""
    area = create_area(
        hass, "Kitchen", labels=[DEFAULT_LEADER_LABEL, "Provides: Shoot Zone"]
    )
    entry = label_map(hass)[f"{area.id}||Shoot Zone"]
    assert entry["scope"] == "none"
    assert entry["scope_id"] == area.id


async def test_floor_scope_dedupes_by_floor(hass: HomeAssistant) -> None:
    """One floor-wide entity, not one per area."""
    floor = create_floor(hass, "First Floor")
    create_area(
        hass,
        "Kitchen",
        labels=[DEFAULT_LEADER_LABEL, "Floor Provides: Audio Mode"],
        floor_id=floor.floor_id,
    )
    create_area(
        hass,
        "Dining Room",
        labels=[DEFAULT_LEADER_LABEL, "Floor Provides: Audio Mode"],
        floor_id=floor.floor_id,
    )
    result = label_map(hass)
    assert set(result) == {f"{floor.floor_id}||Audio Mode"}
    assert result[f"{floor.floor_id}||Audio Mode"]["scope"] == "floor"


async def test_floor_scope_without_a_floor_is_skipped(hass: HomeAssistant) -> None:
    """A floor-scoped declaration on a floorless area cannot resolve."""
    create_area(
        hass, "Kitchen", labels=[DEFAULT_LEADER_LABEL, "Floor Provides: Audio Mode"]
    )
    assert label_map(hass) == {}


async def test_component_override(hass: HomeAssistant) -> None:
    """A sibling Component label overrides the default `select`."""
    area = create_area(
        hass,
        "Root Area",
        labels=[
            DEFAULT_LEADER_LABEL,
            "Area Provides: Tracked PSI",
            "Area Provides Tracked PSI Component: number",
        ],
    )
    entry = label_map(hass)[f"{area.id}||Tracked PSI"]
    assert entry["component"] == "number"
    assert entry["label_data"]["component"] == "number"


async def test_component_override_requires_matching_scope_prefix(
    hass: HomeAssistant,
) -> None:
    """An unscoped Component label does not apply to an area-scoped feature."""
    area = create_area(
        hass,
        "Root Area",
        labels=[
            DEFAULT_LEADER_LABEL,
            "Area Provides: Tracked PSI",
            "Provides Tracked PSI Component: number",
        ],
    )
    assert label_map(hass)[f"{area.id}||Tracked PSI"]["component"] == "select"


async def test_modifier_labels_are_not_features(hass: HomeAssistant) -> None:
    """Modifier labels must not register as features of their own."""
    area = create_area(
        hass,
        "Kitchen",
        labels=[
            DEFAULT_LEADER_LABEL,
            "Area Provides: Audio Mode",
            "Area Provides Audio Mode Component: number",
            "Area Provides Audio Mode Min: 0",
            "Area Provides Audio Mode Max: 100",
            "Area Provides Audio Mode Step: 0.1",
            "Area Provides Audio Mode Unit: kPa",
            "Area Provides Audio Mode Icon: mdi:foo",
            "Area Provides Audio Mode Initial: All",
            "Area Provides Audio Mode Device Class: pressure",
            "Area Provides Audio Mode Mode: box",
            "Area Provides Audio Mode Static: yes",
        ],
    )
    assert set(label_map(hass)) == {f"{area.id}||Audio Mode"}


async def test_only_gated_areas_are_scanned(hass: HomeAssistant) -> None:
    """Areas without the leader label are ignored entirely."""
    create_area(hass, "Kitchen", labels=["Area Provides: Audio Mode"])
    assert label_map(hass) == {}


async def test_unrelated_labels_ignored(hass: HomeAssistant) -> None:
    """Non-Provides labels on a gated area do not produce entries."""
    create_area(
        hass,
        "Kitchen",
        labels=[DEFAULT_LEADER_LABEL, "Area Leader: Night", "Error Mode: log"],
    )
    assert label_map(hass) == {}


def test_is_modifier_label_value() -> None:
    """The modifier detector matches every documented keyword."""
    assert is_modifier_label_value("Audio Mode Component: select")
    assert is_modifier_label_value("Audio Mode Device Class: pressure")
    assert not is_modifier_label_value("Audio Mode")
    assert not is_modifier_label_value("Shoot Zone")

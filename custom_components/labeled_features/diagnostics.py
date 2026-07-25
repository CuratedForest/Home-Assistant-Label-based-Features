"""Diagnostics support for the Labeled Features integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import LabeledFeaturesCoordinator
from .labels import Registries, label_areas, label_entities


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Everything here is local metadata (labels, areas, floors, feature state), so
    nothing needs redacting.
    """
    coordinator: LabeledFeaturesCoordinator = hass.data[DOMAIN][entry.entry_id]
    regs = Registries.async_get(hass)
    leader_ids = label_entities(regs, coordinator.leader_label)

    return {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "resolved_config": coordinator.config_attribute,
        "entities": {
            "features_state": coordinator.features_entity_id,
            "areas_state": coordinator.areas_entity_id,
        },
        "leader_entity_ids": leader_ids,
        "gated_area_ids": label_areas(regs, coordinator.leader_label),
        "triple_map": coordinator.triple_map_snapshot(),
        "attributes": {
            "leaders": coordinator.leaders,
            "features": coordinator.features,
            "snapshots": coordinator.snapshots,
            "label_map": coordinator.label_map,
        },
    }

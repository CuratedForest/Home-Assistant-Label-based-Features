"""Sensor entities for Labeled Features.

Two sensors that replace the trigger-based template sensors:
- sensor.labeled_features_state (features/leaders/snapshots)
- sensor.labeled_feature_areas_state (label_map)
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AREAS_SENSOR_STEM,
    FEATURES_SENSOR_STEM,
    LABEL_FEATURE_LEADER,
)
from .coordinator import (
    LabeledFeatureAreasCoordinator,
    LabeledFeaturesCoordinator,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Labeled Features sensors."""
    features_coordinator: LabeledFeaturesCoordinator = (
        hass.data["labeled_features"]["features_coordinator"]
    )
    areas_coordinator: LabeledFeatureAreasCoordinator = (
        hass.data["labeled_features"]["areas_coordinator"]
    )

    async_add_entities([
        LabeledFeaturesStateSensor(features_coordinator),
        LabeledFeatureAreasStateSensor(areas_coordinator),
    ])


class LabeledFeaturesStateSensor(SensorEntity):
    """Sensor that exposes the Labeled Features State.

    Replaces sensor.labeled_features_state template sensor.
    State = count of feature_leader entities.
    Attributes = feature_meta, leaders, features, snapshots.
    """

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "leaders"
    _attr_has_entity_name = True
    _attr_name = "Labeled Features State"
    _attr_unique_id = FEATURES_SENSOR_STEM

    def __init__(self, coordinator: LabeledFeaturesCoordinator) -> None:
        self._coordinator = coordinator
        self.entity_id = f"sensor.{FEATURES_SENSOR_STEM}"

    @property
    def available(self) -> bool:
        return not self._coordinator.is_disabled

    @property
    def state(self):
        return len(self._coordinator._leader_set)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        from ..label_based_features.const import FEATURE_META
        return {
            "feature_meta": FEATURE_META,
            "leaders": self._coordinator.leaders,
            "features": self._coordinator.features,
            "snapshots": self._coordinator.snapshots,
        }


class LabeledFeatureAreasStateSensor(SensorEntity):
    """Sensor that exposes the Labeled Feature Areas State.

    Replaces sensor.labeled_feature_areas_state template sensor.
    State = count of feature_leader areas.
    Attributes = label_map.
    """

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "areas"
    _attr_has_entity_name = True
    _attr_name = "Labeled Feature Areas State"
    _attr_unique_id = AREAS_SENSOR_STEM

    def __init__(self, coordinator: LabeledFeatureAreasCoordinator) -> None:
        self._coordinator = coordinator
        self.entity_id = f"sensor.{AREAS_SENSOR_STEM}"

    @property
    def available(self) -> bool:
        return not self._coordinator.is_disabled

    @property
    def state(self):
        try:
            return len(
                self._coordinator.hass.helpers.area.label_areas(
                    LABEL_FEATURE_LEADER
                )
            )
        except Exception:
            return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"label_map": self._coordinator.label_map}

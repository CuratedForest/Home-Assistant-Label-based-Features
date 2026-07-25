"""Sensor entities for Labeled Features.

Drop-in replacements for the two legacy trigger-based template sensors.
Entity ids and attribute schemas are contractual — the Labeled Feature
Leaders / Areas automations and every ``labeled_feature_*`` script read
them:

- ``sensor.labeled_features_state`` — state = count of entities labeled
  ``feature_leader``; attributes ``feature_meta`` / ``leaders`` /
  ``features`` / ``snapshots``.
- ``sensor.labeled_feature_areas_state`` — state = count of areas
  labeled ``feature_leader``; attribute ``label_map``.

Both entities restore their attributes on startup (mirroring trigger
template restore) and then reconcile against the live registries when
Home Assistant has started.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    AREAS_SENSOR_ENTITY_ID,
    AREAS_SENSOR_STEM,
    DOMAIN,
    FEATURE_META,
    FEATURES_SENSOR_ENTITY_ID,
    FEATURES_SENSOR_STEM,
)
from .coordinator import (
    LabeledFeatureAreasCoordinator,
    LabeledFeaturesCoordinator,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Labeled Features sensors."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    features_coordinator: LabeledFeaturesCoordinator = data["features_coordinator"]
    areas_coordinator: LabeledFeatureAreasCoordinator = data["areas_coordinator"]

    async_add_entities(
        [
            LabeledFeaturesStateSensor(features_coordinator),
            LabeledFeatureAreasStateSensor(areas_coordinator),
        ]
    )


class _RestoringCoordinatorSensor(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Shared restore + availability plumbing."""

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _expected_entity_id = ""

    async def async_added_to_hass(self) -> None:
        """Restore last attributes into the coordinator, then subscribe."""
        await super().async_added_to_hass()
        self._check_entity_id_collision()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self.coordinator.async_restore_attributes(last_state.attributes)

    def _check_entity_id_collision(self) -> None:
        """Fail loudly if the contractual entity id was not available.

        If the legacy template sensor still owns the expected entity id
        when this entity is first registered, HA silently allocates a
        ``_2`` suffix and persists it under our unique_id — every
        downstream automation/script then reads the stale sensor. Raise
        a repair issue so the misconfiguration is visible.
        """
        expected = self._expected_entity_id
        if not expected or self.entity_id == expected:
            ir.async_delete_issue(self.hass, DOMAIN, f"entity_id_collision_{expected}")
            return
        _LOGGER.error(
            "Entity id collision: expected %s but got %s. Remove the legacy "
            "template sensor that owns %s, then delete this entity from the "
            "entity registry and reload the integration — downstream "
            "automations and scripts read %s and will not see this entity",
            expected,
            self.entity_id,
            expected,
            expected,
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"entity_id_collision_{expected}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="entity_id_collision",
            translation_placeholders={
                "expected": expected,
                "actual": self.entity_id,
            },
        )

    @property
    def available(self) -> bool:
        return super().available and not self.coordinator.is_disabled


class LabeledFeaturesStateSensor(_RestoringCoordinatorSensor):
    """``sensor.labeled_features_state``."""

    _attr_native_unit_of_measurement = "leaders"
    _attr_name = "Labeled Features State"
    _attr_unique_id = FEATURES_SENSOR_STEM
    _expected_entity_id = FEATURES_SENSOR_ENTITY_ID

    def __init__(self, coordinator: LabeledFeaturesCoordinator) -> None:
        super().__init__(coordinator)
        self.entity_id = FEATURES_SENSOR_ENTITY_ID

    @property
    def native_value(self) -> int:
        return self.coordinator.data.get("leader_count", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "feature_meta": FEATURE_META,
            "leaders": data.get("leaders", {}),
            "features": data.get("features", {}),
            "snapshots": data.get("snapshots", {}),
        }


class LabeledFeatureAreasStateSensor(_RestoringCoordinatorSensor):
    """``sensor.labeled_feature_areas_state``."""

    _attr_native_unit_of_measurement = "areas"
    _attr_name = "Labeled Feature Areas State"
    _attr_unique_id = AREAS_SENSOR_STEM
    _expected_entity_id = AREAS_SENSOR_ENTITY_ID

    def __init__(self, coordinator: LabeledFeatureAreasCoordinator) -> None:
        super().__init__(coordinator)
        self.entity_id = AREAS_SENSOR_ENTITY_ID

    @property
    def native_value(self) -> int:
        return self.coordinator.data.get("area_count", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"label_map": self.coordinator.data.get("label_map", {})}

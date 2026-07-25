"""Sensor platform for the Labeled Features integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    ATTR_CONFIG,
    ATTR_FEATURE_META,
    ATTR_FEATURES,
    ATTR_LABEL_MAP,
    ATTR_LEADERS,
    ATTR_SNAPSHOTS,
    DOMAIN,
    FEATURE_META,
)
from .coordinator import LabeledFeaturesCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the two state sensors for a config entry."""
    coordinator: LabeledFeaturesCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            LabeledFeaturesStateSensor(coordinator),
            LabeledFeatureAreasStateSensor(coordinator),
        ]
    )


class LabeledFeaturesBaseSensor(SensorEntity, RestoreEntity):
    """Shared plumbing for both state sensors."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: LabeledFeaturesCoordinator) -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._count = 0

    @property
    def available(self) -> bool:
        """The sensors are always available; they are pure metadata views."""
        return True

    @property
    def native_value(self) -> int:
        """Return the tracked count."""
        return self._count

    @callback
    def _handle_update(self) -> None:
        """Recompute the state value and push exactly one state write."""
        self._count = self._compute_count()
        self.async_write_ha_state()

    def _compute_count(self) -> int:
        raise NotImplementedError


class LabeledFeaturesStateSensor(LabeledFeaturesBaseSensor):
    """``sensor.<prefix>s_state`` — the Labeled Features State sensor."""

    _attr_name = "Labeled Features State"
    _attr_native_unit_of_measurement = "leaders"

    def __init__(self, coordinator: LabeledFeaturesCoordinator) -> None:
        """Initialize the features state sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_features_state"
        self._attr_suggested_object_id = f"{coordinator.prefix}s_state"

    @property
    def suggested_object_id(self) -> str | None:
        """Return the object id derived from the configured slug prefix."""
        return self._attr_suggested_object_id

    def _compute_count(self) -> int:
        return self.coordinator.leader_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the downstream attribute contract.

        The mutable working state is never exposed directly: the coordinator
        publishes a detached snapshot on every write so Home Assistant's
        shallow attribute comparison can actually see the change.
        """
        return {
            ATTR_FEATURE_META: FEATURE_META,
            **self.coordinator.published_features_attributes,
            ATTR_CONFIG: self.coordinator.config_attribute,
        }

    async def async_added_to_hass(self) -> None:
        """Restore attributes and subscribe to coordinator updates."""
        await super().async_added_to_hass()
        self.coordinator.features_entity_id = self.entity_id

        if (last_state := await self.async_get_last_state()) is not None:
            self.coordinator.async_restore_features(
                last_state.attributes.get(ATTR_LEADERS),
                last_state.attributes.get(ATTR_FEATURES),
                last_state.attributes.get(ATTR_SNAPSHOTS),
            )
            try:
                self._count = int(last_state.state)
            except (TypeError, ValueError):
                self._count = 0

        self.async_on_remove(
            self.coordinator.async_add_features_listener(self._handle_update)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Forget our entity id."""
        if self.coordinator.features_entity_id == self.entity_id:
            self.coordinator.features_entity_id = None
        await super().async_will_remove_from_hass()


class LabeledFeatureAreasStateSensor(LabeledFeaturesBaseSensor):
    """``sensor.<prefix>_areas_state`` — the Labeled Feature Areas State sensor."""

    _attr_name = "Labeled Feature Areas State"
    _attr_native_unit_of_measurement = "areas"

    def __init__(self, coordinator: LabeledFeaturesCoordinator) -> None:
        """Initialize the areas state sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_areas_state"
        self._attr_suggested_object_id = f"{coordinator.prefix}_areas_state"

    @property
    def suggested_object_id(self) -> str | None:
        """Return the object id derived from the configured slug prefix."""
        return self._attr_suggested_object_id

    def _compute_count(self) -> int:
        return self.coordinator.gated_area_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the ``label_map`` trigger surface."""
        return {ATTR_LABEL_MAP: self.coordinator.published_label_map}

    async def async_added_to_hass(self) -> None:
        """Restore ``label_map`` and subscribe to coordinator updates."""
        await super().async_added_to_hass()
        self.coordinator.areas_entity_id = self.entity_id

        if (last_state := await self.async_get_last_state()) is not None:
            self.coordinator.async_restore_label_map(
                last_state.attributes.get(ATTR_LABEL_MAP)
            )
            try:
                self._count = int(last_state.state)
            except (TypeError, ValueError):
                self._count = 0

        self.async_on_remove(
            self.coordinator.async_add_areas_listener(self._handle_update)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Forget our entity id."""
        if self.coordinator.areas_entity_id == self.entity_id:
            self.coordinator.areas_entity_id = None
        await super().async_will_remove_from_hass()

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import LabeledFeaturesCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: LabeledFeaturesCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            LabeledFeaturesStateSensor(entry, coordinator),
            LabeledFeatureAreasStateSensor(entry, coordinator),
        ]
    )


class LabeledFeaturesStateSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "leaders"
    _attr_icon = "mdi:label-variant"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: LabeledFeaturesCoordinator,
    ) -> None:
        slug = entry.data["instance_name"].lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_labeled_features_state"
        self._attr_name = f"{entry.data['instance_name']} Labeled Features State"
        self.entity_id = f"sensor.{slug}_labeled_features_state"
        self._coordinator = coordinator
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self._coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        self._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_native_value = len(self._coordinator.leaders)
        self._attr_extra_state_attributes = {
            "feature_meta": self._coordinator.feature_meta,
            "leaders": self._coordinator.leaders,
            "features": self._coordinator.features,
            "snapshots": self._coordinator.snapshots,
        }
        self.async_write_ha_state()


class LabeledFeatureAreasStateSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "areas"
    _attr_icon = "mdi:floor-plan"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: LabeledFeaturesCoordinator,
    ) -> None:
        slug = entry.data["instance_name"].lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_labeled_feature_areas_state"
        self._attr_name = f"{entry.data['instance_name']} Labeled Feature Areas State"
        self.entity_id = f"sensor.{slug}_labeled_feature_areas_state"
        self._coordinator = coordinator
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self._coordinator.async_add_listener(
            self._handle_coordinator_update
        )
        self._handle_coordinator_update()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        label_map = self._coordinator.label_map
        unique_areas: set[str] = set()
        for entry_data in label_map.values():
            sid = entry_data.get("scope_id", "")
            if sid:
                unique_areas.add(sid)

        self._attr_native_value = len(unique_areas)
        self._attr_extra_state_attributes = {
            "label_map": label_map,
        }
        self.async_write_ha_state()

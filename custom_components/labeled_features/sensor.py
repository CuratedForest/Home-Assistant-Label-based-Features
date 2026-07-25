"""Sensor entities for the Labeled Features integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_AREAS_STATE_ENTITY_ID,
    CONF_FEATURES_STATE_ENTITY_ID,
    CONF_INSTANCE_NAME,
    DATA_ENTRIES,
    DEFAULT_AREAS_STATE_ENTITY_ID,
    DEFAULT_FEATURES_STATE_ENTITY_ID,
    DEFAULT_INSTANCE_NAME,
    DOMAIN,
)
from .coordinator import (
    LabeledFeatureAreasStateCoordinator,
    LabeledFeaturesStateCoordinator,
)

_LOGGER = logging.getLogger(__name__)


class _LabeledFeaturesRestoreData(ExtraStoredData):
    """RestoreEntity payload for the features-state sensor."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def as_dict(self) -> dict[str, Any]:
        return self._payload


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the two sensors owned by a config entry."""

    domain_data = hass.data.setdefault(DOMAIN, {}).setdefault(DATA_ENTRIES, {})
    entry_data = domain_data.get(entry.entry_id)
    if entry_data is None:
        _LOGGER.error(
            "Cannot set up sensors: no runtime data for entry %s", entry.entry_id
        )
        return

    features_coord: LabeledFeaturesStateCoordinator = entry_data["features"]
    areas_coord: LabeledFeatureAreasStateCoordinator = entry_data["areas"]
    merged = {**entry.data, **entry.options}
    instance_name = (
        merged.get(CONF_INSTANCE_NAME) or DEFAULT_INSTANCE_NAME
    ).strip()

    async_add_entities(
        [
            LabeledFeaturesStateSensor(
                coordinator=features_coord,
                entry_id=entry.entry_id,
                instance_name=instance_name,
                requested_entity_id=(
                    merged.get(CONF_FEATURES_STATE_ENTITY_ID)
                    or DEFAULT_FEATURES_STATE_ENTITY_ID
                ),
            ),
            LabeledFeatureAreasStateSensor(
                coordinator=areas_coord,
                entry_id=entry.entry_id,
                instance_name=instance_name,
                requested_entity_id=(
                    merged.get(CONF_AREAS_STATE_ENTITY_ID)
                    or DEFAULT_AREAS_STATE_ENTITY_ID
                ),
            ),
        ]
    )


class _BaseLabeledFeaturesSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = False

    def __init__(
        self,
        *,
        coordinator,
        entry_id: str,
        instance_name: str,
        requested_entity_id: str,
        suffix: str,
        default_entity_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{suffix}"
        self._attr_name = f"{instance_name} {suffix.replace('_', ' ').title()}"
        # Passing `entity_id` in the constructor is the supported way to
        # request a specific slug; HA will still de-duplicate if the ID
        # is already taken (appending `_2`) — config-flow validation
        # catches that up-front.
        self.entity_id = requested_entity_id or default_entity_id


class LabeledFeaturesStateSensor(_BaseLabeledFeaturesSensor, RestoreEntity):
    """sensor.labeled_features_state — exposes feature_meta, leaders, features, snapshots."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "leaders"
    _attr_icon = "mdi:tag-multiple"

    def __init__(
        self,
        *,
        coordinator: LabeledFeaturesStateCoordinator,
        entry_id: str,
        instance_name: str,
        requested_entity_id: str,
    ) -> None:
        super().__init__(
            coordinator=coordinator,
            entry_id=entry_id,
            instance_name=instance_name,
            requested_entity_id=requested_entity_id,
            suffix="features_state",
            default_entity_id=DEFAULT_FEATURES_STATE_ENTITY_ID,
        )
        self._coordinator = coordinator
        # Memoisation for `extra_state_attributes`. `data_version` bumps
        # on every coordinator mutation; when it doesn't move, we return
        # the previously-serialised snapshot instead of walking the
        # dataclass tree again on every attribute read.
        self._attrs_cache: dict[str, Any] | None = None
        self._attrs_cache_version: int = -1

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore leaders / features / snapshots before the coordinator
        # emits its first tick so the initial state carries history.
        stored = await self.async_get_last_extra_data()
        if stored is not None:
            payload = stored.as_dict() or {}
            self._coordinator.apply_restore(payload)
        # Force a coordinator-triggered notification so listeners pick
        # up the restored data even without a real event yet.
        self._coordinator.async_set_updated_data(self._coordinator.data)

    @property
    def extra_restore_state_data(self) -> _LabeledFeaturesRestoreData:
        return _LabeledFeaturesRestoreData(self._coordinator.data.to_restore())

    @property
    def native_value(self) -> int:
        return self._coordinator.data.leader_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        version = self._coordinator.data_version
        if self._attrs_cache is not None and version == self._attrs_cache_version:
            return self._attrs_cache
        data = self._coordinator.data
        serialised: dict[str, Any] = {
            "feature_meta": data.feature_meta,
            "leaders": data.leaders_as_dict(),
            "features": data.features_as_dict(),
            "snapshots": data.snapshots,
        }
        self._attrs_cache = serialised
        self._attrs_cache_version = version
        return serialised


class LabeledFeatureAreasStateSensor(_BaseLabeledFeaturesSensor):
    """sensor.labeled_feature_areas_state — exposes `label_map`."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "areas"
    _attr_icon = "mdi:floor-plan"

    def __init__(
        self,
        *,
        coordinator: LabeledFeatureAreasStateCoordinator,
        entry_id: str,
        instance_name: str,
        requested_entity_id: str,
    ) -> None:
        super().__init__(
            coordinator=coordinator,
            entry_id=entry_id,
            instance_name=instance_name,
            requested_entity_id=requested_entity_id,
            suffix="areas_state",
            default_entity_id=DEFAULT_AREAS_STATE_ENTITY_ID,
        )
        self._coordinator = coordinator

    @property
    def native_value(self) -> int:
        return self._coordinator.leader_area_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"label_map": self._coordinator.data or {}}

    @callback
    def _handle_coordinator_update(self) -> None:
        # Coordinator emits `data` as a dict — no transformation needed.
        super()._handle_coordinator_update()

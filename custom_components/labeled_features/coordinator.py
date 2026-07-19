"""Coordinator for Labeled Features state management.

Uses the pure engine.py functions for evaluation. The coordinator
handles registry access and event listeners, feeding data to the
engine and storing results.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from ..label_based_features import engine
from .const import (
    EVENT_LABELED_FEATURE_SET,
    EVENT_LABELED_FEATURE_SNAPSHOT_SET,
    FEATURES_SENSOR_STEM,
    LABEL_FEATURE_LEADER,
    SCOPES,
)
from .error_handler import ErrorStop, handle_error

_LOGGER = logging.getLogger(__name__)


def _resolve_label_id(hass: HomeAssistant, name_or_id: str) -> str | None:
    """Resolve a label name or id to its label_id."""
    registry = lr.async_get(hass)
    if registry.async_get_label(name_or_id):
        return name_or_id
    for label in registry.async_list_labels():
        if label.name == name_or_id:
            return label.label_id
    return None


def _labeled_leader_entity_ids(hass: HomeAssistant) -> list[str]:
    """Entities carrying the feature_leader label."""
    label_id = _resolve_label_id(hass, LABEL_FEATURE_LEADER)
    if label_id is None:
        return []
    registry = er.async_get(hass)
    return [entry.entity_id for entry in er.async_entries_for_label(registry, label_id)]


def _entity_label_names(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Label NAMES on an entity registry entry."""
    entity_entry = er.async_get(hass).async_get(entity_id)
    if entity_entry is None:
        return []
    registry = lr.async_get(hass)
    names: list[str] = []
    for label_id in entity_entry.labels:
        label = registry.async_get_label(label_id)
        if label is not None and label.name:
            names.append(label.name)
    return names


def _entity_area_floor(hass: HomeAssistant, entity_id: str) -> tuple[str, str]:
    """Resolve an entity's area_id and its floor_id."""
    entity_entry = er.async_get(hass).async_get(entity_id)
    area_id = ""
    if entity_entry is not None:
        if entity_entry.area_id:
            area_id = entity_entry.area_id
        elif entity_entry.device_id:
            device = dr.async_get(hass).async_get(entity_entry.device_id)
            if device is not None and device.area_id:
                area_id = device.area_id
    floor_id = ""
    if area_id:
        area = ar.async_get(hass).async_get_area(area_id)
        if area is not None and area.floor_id:
            floor_id = area.floor_id
    return area_id, floor_id


def _gated_areas(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Areas carrying the feature_leader label, with label names."""
    label_id = _resolve_label_id(hass, LABEL_FEATURE_LEADER)
    if label_id is None:
        return []
    label_registry = lr.async_get(hass)
    gated: list[dict[str, Any]] = []
    for area in ar.async_entries_for_label(ar.async_get(hass), label_id):
        label_names: list[str] = []
        for lid in area.labels:
            label = label_registry.async_get_label(lid)
            if label is not None and label.name:
                label_names.append(label.name)
        gated.append({
            "area_id": area.id,
            "floor_id": area.floor_id or "",
            "labels": label_names,
        })
    return gated


def _leader_value_from_state(state: Any) -> str:
    """Leader value accessor: event.* entities use event_type attribute."""
    if state is None:
        return ""
    if state.entity_id.split(".")[0] == "event":
        event_type = state.attributes.get("event_type")
        if event_type is not None:
            return str(event_type)
    return str(state.state)


def _state_timestamp(state: Any) -> float:
    """last_changed timestamp with dt_util fallback."""
    if state is not None and state.last_changed is not None:
        return state.last_changed.timestamp()
    return dt_util.utcnow().timestamp()


class LabeledFeaturesCoordinator:
    """Coordinator for Labeled Feature State.

    Manages features, leaders, and snapshots state using the pure
    engine.py functions for evaluation.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._listeners: list[Callable] = []
        self._disabled = False
        self._leader_set: set[str] = set()

        # State storage
        self.leaders: dict = {}
        self.features: dict = {}
        self.snapshots: dict = {}

    @property
    def is_disabled(self) -> bool:
        return self._disabled

    @is_disabled.setter
    def is_disabled(self, value: bool) -> None:
        self._disabled = value

    async def async_setup(self) -> None:
        """Set up event listeners."""
        self._listeners.append(
            self.hass.bus.async_listen(
                "state_changed",
                self._on_state_changed,
            )
        )
        self._listeners.append(
            self.hass.bus.async_listen(
                "label_registry_updated",
                self._on_registry_updated,
            )
        )
        self._listeners.append(
            self.hass.bus.async_listen(
                "area_registry_updated",
                self._on_registry_updated,
            )
        )
        self._listeners.append(
            self.hass.bus.async_listen(
                "floor_registry_updated",
                self._on_registry_updated,
            )
        )
        self._listeners.append(
            self.hass.bus.async_listen(
                "homeassistant_start",
                self._on_start,
            )
        )
        self._listeners.append(
            self.hass.bus.async_listen(
                EVENT_LABELED_FEATURE_SET,
                self._on_labeled_feature_set,
            )
        )
        self._listeners.append(
            self.hass.bus.async_listen(
                EVENT_LABELED_FEATURE_SNAPSHOT_SET,
                self._on_labeled_feature_snapshot_set,
            )
        )

    async def async_shutdown(self) -> None:
        """Remove event listeners."""
        for listener in self._listeners:
            listener()
        self._listeners.clear()

    def _refresh_leader_set(self) -> None:
        """Update the leader set from registry."""
        labeled = _labeled_leader_entity_ids(self.hass)
        self._leader_set = set(labeled)

    @callback
    def _on_state_changed(self, event: Event) -> None:
        """Handle state_changed for feature_leader entities."""
        if self._disabled:
            return

        entity_id = event.data.get("entity_id", "")
        if entity_id not in self._leader_set:
            return

        old_state = event.data.get("old_state")
        # Gate: reject events with no real prior state
        if old_state is None:
            return
        old_state_str = old_state.state if old_state else ""
        if old_state_str.lower() in ("unknown", "unavailable", "none"):
            return

        new_state = event.data.get("new_state")
        self._recompute(
            changed_eid=entity_id,
            cv_raw=_leader_value_from_state(new_state),
            changed_ts=_state_timestamp(new_state),
        )

    @callback
    def _on_registry_updated(self, event: Event) -> None:
        """Handle registry updates - just refresh leader set."""
        self._refresh_leader_set()

    @callback
    def _on_start(self, event: Event) -> None:
        """Handle startup - rebuild all state."""
        if self._disabled:
            return
        self._recompute()

    @callback
    def _on_labeled_feature_set(self, event: Event) -> None:
        """Handle manual feature override events."""
        if self._disabled:
            return

        data = event.data
        target_feature = (data.get("target_feature") or "").strip()
        scope = (data.get("scope") or "").lower().strip()
        scope_id = str(data.get("scope_id") or "")
        enabled = bool(data.get("enabled", False))
        timestamp = float(data.get("timestamp") or dt_util.utcnow().timestamp())

        if not target_feature or scope not in SCOPES:
            return

        self._recompute(manual={
            "target_feature": target_feature,
            "scope": scope,
            "scope_id": scope_id,
            "enabled": enabled,
            "timestamp": timestamp,
        })

    @callback
    def _on_labeled_feature_snapshot_set(self, event: Event) -> None:
        """Handle snapshot set events."""
        if self._disabled:
            return

        data = event.data
        snapshot_name = (data.get("snapshot_name") or "").strip()
        payload_raw = data.get("payload")

        self._recompute(
            snapshot_name=snapshot_name,
            snapshot_payload=payload_raw,
        )

    def _get_live_state(self, entity_id: str) -> str:
        """Get live state for an entity ('unknown' when missing)."""
        state = self.hass.states.get(entity_id)
        return state.state if state is not None else "unknown"

    def _seed_info(self, entity_id: str) -> tuple[str, float]:
        """Seed value + timestamp for a newly-seen leader."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return "unknown", 0.0
        return state.state, state.last_changed.timestamp()

    def _recompute(
        self,
        *,
        changed_eid: str | None = None,
        cv_raw: str | None = None,
        changed_ts: float | None = None,
        manual: dict | None = None,
        snapshot_name: str | None = None,
        snapshot_payload: Any = None,
    ) -> None:
        """Recompute all state using engine.py functions."""
        hass = self.hass

        # Gather labeled leaders
        labeled_ids = _labeled_leader_entity_ids(hass)
        labeled_leaders = {
            eid: _entity_label_names(hass, eid) for eid in labeled_ids
        }
        self._leader_set = set(labeled_ids)

        # Build entity context
        entity_ctx: dict[str, dict[str, str]] = {}
        for eid in labeled_ids:
            area_id, floor_id = _entity_area_floor(hass, eid)
            entity_ctx[eid] = {"area_id": area_id, "floor_id": floor_id}

        # Build triples and modes
        triples, errors = engine.build_triples(
            labeled_leaders, [], entity_ctx
        )
        sensor_labels = _entity_label_names(hass, f"sensor.{FEATURES_SENSOR_STEM}")
        modes = engine.resolve_modes(triples.keys(), sensor_labels)

        # Compute new state
        new_features = engine.update_features(
            self.features,
            self.leaders,
            triples,
            modes,
            self._get_live_state,
            changed_eid=changed_eid,
            cv_raw=cv_raw,
            changed_ts=changed_ts,
            manual=manual,
        )
        new_leaders = engine.update_leaders(
            self.leaders,
            labeled_ids,
            changed_eid,
            cv_raw,
            changed_ts,
            self._seed_info,
        )
        new_snapshots = engine.update_snapshots(
            self.snapshots, snapshot_name, snapshot_payload
        )

        self.leaders = new_leaders
        self.features = new_features
        self.snapshots = new_snapshots

        # Report errors
        for error in errors:
            key = error.get("key", "generic")
            _LOGGER.warning(
                "[%s] %s", key, error.get("message", "unknown")
            )


class LabeledFeatureAreasCoordinator:
    """Coordinator for Labeled Feature Areas State.

    Manages the label_map state using the pure engine.py functions.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._listeners: list[Callable] = []
        self._disabled = False
        self.label_map: dict = {}

    @property
    def is_disabled(self) -> bool:
        return self._disabled

    @is_disabled.setter
    def is_disabled(self, value: bool) -> None:
        self._disabled = value

    async def async_setup(self) -> None:
        """Set up event listeners."""
        self._listeners.append(
            self.hass.bus.async_listen(
                "label_registry_updated",
                self._on_registry_updated,
            )
        )
        self._listeners.append(
            self.hass.bus.async_listen(
                "area_registry_updated",
                self._on_registry_updated,
            )
        )
        self._listeners.append(
            self.hass.bus.async_listen(
                "floor_registry_updated",
                self._on_registry_updated,
            )
        )
        self._listeners.append(
            self.hass.bus.async_listen(
                "homeassistant_start",
                self._on_start,
            )
        )

    async def async_shutdown(self) -> None:
        """Remove event listeners."""
        for listener in self._listeners:
            listener()
        self._listeners.clear()

    @callback
    def _on_registry_updated(self, event: Event) -> None:
        """Handle registry updates."""
        if self._disabled:
            return
        self._recompute()

    @callback
    def _on_start(self, event: Event) -> None:
        """Handle startup."""
        if self._disabled:
            return
        self._recompute()

    def _recompute(self) -> None:
        """Rebuild label_map from registries."""
        gated = _gated_areas(self.hass)
        label_map, errors = engine.build_label_map(gated)
        self.label_map = label_map

        for error in errors:
            key = error.get("key", "generic")
            _LOGGER.warning(
                "[%s] %s", key, error.get("message", "unknown")
            )

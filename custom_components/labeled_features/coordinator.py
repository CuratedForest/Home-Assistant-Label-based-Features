"""Coordinators for Labeled Features state management.

Registry / event plumbing only — all evaluation logic lives in the pure
``engine`` module. Two coordinators:

- :class:`LabeledFeaturesCoordinator` — maintains the ``leaders`` /
  ``features`` / ``snapshots`` state behind
  ``sensor.labeled_features_state``.
- :class:`LabeledFeatureAreasCoordinator` — maintains the ``label_map``
  state behind ``sensor.labeled_feature_areas_state``.

Both push updates to their entities via the DataUpdateCoordinator
pattern (no polling).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
)
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    label_registry as lr,
    restore_state,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import engine
from .const import (
    AREAS_SENSOR_ENTITY_ID,
    DOMAIN,
    ERROR_LOG,
    ERROR_MODES,
    EVENT_LABELED_FEATURE_SET,
    EVENT_LABELED_FEATURE_SNAPSHOT_SET,
    FEATURES_SENSOR_ENTITY_ID,
    LABEL_FEATURE_LEADER,
    MAX_EVENT_FIELD_LENGTH,
    MAX_MANUAL_FEATURES,
    MAX_SNAPSHOT_PAYLOAD_CHARS,
    MAX_SNAPSHOTS,
    SCOPES,
    UNREAL_STATES,
)
from .error_handler import report_error

_LOGGER = logging.getLogger(__name__)

# Registry events that can change which entities/areas are gated or how
# their labels resolve.
_REGISTRY_EVENTS = (
    "label_registry_updated",
    "area_registry_updated",
    "floor_registry_updated",
)


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
    """Entity ids carrying the ``feature_leader`` label."""
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
    """Resolve an entity's area_id (entity override, else device) and floor."""
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
    """Areas carrying the ``feature_leader`` label, with label names."""
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
        gated.append(
            {
                "area_id": area.id,
                "floor_id": area.floor_id or "",
                "labels": label_names,
            }
        )
    return gated


def _leader_value_from_state(state: Any) -> str:
    """Leader value accessor: ``event.*`` entities use event_type.

    For event-domain entities ``state`` is the ISO timestamp of the
    last event; the actual event name lives in the ``event_type``
    attribute. Downstream consumers (button classifiers, shorthand
    labels) depend on this accessor.
    """
    if state is None:
        return ""
    if state.entity_id.split(".")[0] == "event":
        event_type = state.attributes.get("event_type")
        if event_type is not None:
            return str(event_type)
    return str(state.state)


def _state_timestamp(state: Any) -> float:
    """last_changed timestamp with a now() fallback."""
    if state is not None and state.last_changed is not None:
        return state.last_changed.timestamp()
    return dt_util.utcnow().timestamp()


class _BaseCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Shared plumbing: listener bookkeeping, restore, error routing."""

    _error_source = "Labeled Features"
    _sensor_entity_id = ""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, name: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=name,
            update_interval=None,
        )
        self._unsubs: list[Callable[[], None]] = []
        self._disabled = False
        self._reported_errors: set[str] = set()

    @property
    def is_disabled(self) -> bool:
        return self._disabled

    @is_disabled.setter
    def is_disabled(self, value: bool) -> None:
        self._disabled = value
        self.async_update_listeners()

    async def async_shutdown(self) -> None:
        """Remove event listeners."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await super().async_shutdown()

    @callback
    def async_restore_attributes(self, attributes: Mapping[str, Any]) -> None:
        """Seed coordinator state from restored sensor attributes."""
        raise NotImplementedError

    async def _async_restore_last_attributes(self) -> None:
        """Restore the sensor's last stored attributes into this coordinator.

        Runs in ``async_setup`` BEFORE any event listener is registered
        or any recompute happens, so restored state (snapshots, manual
        overrides, previous-value chains, label_map) cannot be raced
        away by an early event tick. The entity-side ``RestoreEntity``
        call remains as a no-op fallback.
        """
        restore_data = restore_state.async_get(self.hass)
        stored = restore_data.last_states.get(self._sensor_entity_id)
        if stored is not None and stored.state is not None:
            self.async_restore_attributes(stored.state.attributes)

    def _resolved_error_mode(self) -> str:
        """Default error tier from an ``Error Mode:`` label on the sensor."""
        for label in _entity_label_names(self.hass, self._sensor_entity_id):
            if label.lower().startswith("error mode: "):
                mode = label.rsplit(": ", 1)[-1].strip().lower()
                if mode in ERROR_MODES:
                    return mode
        return ERROR_LOG

    @callback
    def _report(self, message: str) -> None:
        """Report a single coordinator-level error via the resolved tier."""
        report_error(
            self.hass,
            self._resolved_error_mode(),
            message,
            source=self._error_source,
            raise_on_stop=False,
        )

    @callback
    def _route_errors(self, errors: list[dict[str, str]], error_mode: str) -> None:
        """Report engine error records, deduplicated across recomputes.

        The legacy templates skipped these conditions silently; the
        component surfaces each distinct message once (per occurrence
        streak) through the configured error tier.
        """
        current = {error.get("message", "") for error in errors}
        for error in errors:
            message = error.get("message", "")
            if message and message not in self._reported_errors:
                report_error(
                    self.hass,
                    error_mode,
                    message,
                    source=self._error_source,
                    raise_on_stop=False,
                )
        self._reported_errors = current


class LabeledFeaturesCoordinator(_BaseCoordinator):
    """Coordinator for ``sensor.labeled_features_state``.

    Data payload: ``{"leader_count", "leaders", "features",
    "snapshots"}``.
    """

    _error_source = "Labeled Features State"
    _sensor_entity_id = FEATURES_SENSOR_ENTITY_ID

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(hass, config_entry, f"{DOMAIN}_features")
        self._leader_set: set[str] = set()
        self.leaders: dict[str, Any] = {}
        self.features: dict[str, Any] = {}
        self.snapshots: dict[str, Any] = {}
        self._restored = False
        self._computed = False
        self.async_set_updated_data(self._data_payload())

    async def async_setup(self) -> None:
        """Restore prior state, then register event listeners."""
        self._refresh_leader_set()
        # Restore BEFORE any listener can trigger a recompute, so an
        # early leader tick cannot discard snapshots / manual overrides.
        await self._async_restore_last_attributes()
        # Publish a correct leader count immediately; attributes stay
        # restored/empty until the first tick (template-sensor parity).
        self.async_set_updated_data(self._data_payload())
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_STATE_CHANGED,
                self._on_state_changed,
                event_filter=self._state_event_filter,
            )
        )
        for event_type in ("entity_registry_updated", *_REGISTRY_EVENTS):
            self._unsubs.append(
                self.hass.bus.async_listen(event_type, self._on_registry_updated)
            )
        self._unsubs.append(
            self.hass.bus.async_listen(EVENT_HOMEASSISTANT_STARTED, self._on_started)
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_LABELED_FEATURE_SET, self._on_labeled_feature_set
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_LABELED_FEATURE_SNAPSHOT_SET,
                self._on_labeled_feature_snapshot_set,
            )
        )

    # ── Restore ──────────────────────────────────────────────────────
    @callback
    def async_restore_attributes(self, attributes: Mapping[str, Any]) -> None:
        """Seed state from the sensor's last recorded attributes.

        Mirrors the trigger-based template sensor's recorder restore —
        manual overrides, snapshots, and the leaders automation's
        ``from_state`` diff all depend on this surviving a restart.
        Ignored once a live recompute has already run.
        """
        if self._restored or self._computed:
            return
        self._restored = True
        leaders = attributes.get("leaders")
        features = attributes.get("features")
        snapshots = attributes.get("snapshots")
        if isinstance(leaders, Mapping):
            self.leaders = dict(leaders)
        if isinstance(features, Mapping):
            self.features = dict(features)
        if isinstance(snapshots, Mapping):
            self.snapshots = dict(snapshots)
        self.async_set_updated_data(self._data_payload())

    # ── Event handlers ───────────────────────────────────────────────
    @callback
    def _state_event_filter(self, event_data: Mapping[str, Any]) -> bool:
        """Cheap synchronous gate for the state_changed firehose.

        Mirrors the legacy template's ``conditions:`` gate: only
        currently-labeled leaders pass, and only when there is a real
        prior state (blocks boot-restore / reconnect noise).
        """
        if self._disabled:
            return False
        if event_data.get("entity_id") not in self._leader_set:
            return False
        old_state = event_data.get("old_state")
        if old_state is None:
            return False
        return str(old_state.state).lower() not in UNREAL_STATES

    @callback
    def _on_state_changed(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        entity_id = event.data.get("entity_id", "")
        self._recompute(
            changed_eid=entity_id,
            cv_raw=_leader_value_from_state(new_state),
            changed_ts=_state_timestamp(new_state),
        )

    @callback
    def _on_registry_updated(self, event: Event) -> None:
        """Registry mutation — refresh the leader gate set only.

        Parity note: the legacy template did NOT re-render on registry
        events; orphaned entries linger until the next leader-driven
        tick. Only the gate set is refreshed here so newly-labeled
        leaders fire immediately.
        """
        self._refresh_leader_set()

    @callback
    def _on_started(self, _event: Event) -> None:
        """Reconcile restored state against the live registry on boot."""
        if self._disabled:
            return
        self._recompute()

    @callback
    def _on_labeled_feature_set(self, event: Event) -> None:
        """Manual override path (`Set Feature` catalog entry)."""
        if self._disabled:
            return
        data = event.data
        target_feature = str(data.get("target_feature") or "").strip()
        scope = str(data.get("scope") or "").lower().strip()
        scope_id = str(data.get("scope_id") or "")
        if not target_feature or scope not in SCOPES:
            return
        if (
            len(target_feature) > MAX_EVENT_FIELD_LENGTH
            or len(scope_id) > MAX_EVENT_FIELD_LENGTH
        ):
            self._report(
                "labeled_feature_set rejected: target_feature/scope_id "
                f"exceeds {MAX_EVENT_FIELD_LENGTH} characters."
            )
            return
        # Cap unbounded growth from garbage events: manual entries have
        # no expiry path, so refuse NEW manual keys past the cap
        # (updates to existing entries always pass).
        existing = self.features.get(target_feature, {})
        exists = (
            isinstance(existing, Mapping)
            and isinstance(existing.get(scope), Mapping)
            and scope_id in existing[scope]
        )
        if not exists and self._manual_entry_count() >= MAX_MANUAL_FEATURES:
            self._report(
                "labeled_feature_set rejected: manual feature entry cap "
                f"({MAX_MANUAL_FEATURES}) reached for new entry "
                f"'{target_feature}'."
            )
            return
        try:
            timestamp = float(data.get("timestamp") or dt_util.utcnow().timestamp())
        except (TypeError, ValueError):
            timestamp = dt_util.utcnow().timestamp()
        self._recompute(
            manual={
                "target_feature": target_feature,
                "scope": scope,
                "scope_id": scope_id,
                "enabled": bool(data.get("enabled", False)),
                "timestamp": timestamp,
            }
        )

    @callback
    def _on_labeled_feature_snapshot_set(self, event: Event) -> None:
        """Persisted-state path (`Set Snapshot` catalog entry)."""
        if self._disabled:
            return
        snapshot_name = str(event.data.get("snapshot_name") or "").strip()
        if not snapshot_name:
            return
        payload = event.data.get("payload")
        is_set = isinstance(payload, Mapping) and len(payload) > 0
        if is_set and len(str(payload)) > MAX_SNAPSHOT_PAYLOAD_CHARS:
            self._report(
                f"Snapshot '{snapshot_name}' rejected: payload exceeds "
                f"{MAX_SNAPSHOT_PAYLOAD_CHARS} characters."
            )
            return
        if (
            is_set
            and snapshot_name not in self.snapshots
            and len(self.snapshots) >= MAX_SNAPSHOTS
        ):
            self._report(
                f"Snapshot '{snapshot_name}' rejected: snapshot cap "
                f"({MAX_SNAPSHOTS}) reached."
            )
            return
        self._recompute(
            snapshot_name=snapshot_name,
            snapshot_payload=payload,
        )

    # ── Helpers ──────────────────────────────────────────────────────
    @callback
    def _refresh_leader_set(self) -> None:
        self._leader_set = set(_labeled_leader_entity_ids(self.hass))

    def _manual_entry_count(self) -> int:
        """Count manual (triggering_leader == '') feature entries."""
        count = 0
        for scopes_map in self.features.values():
            if not isinstance(scopes_map, Mapping):
                continue
            for sids in scopes_map.values():
                if not isinstance(sids, Mapping):
                    continue
                for entry in sids.values():
                    if (
                        isinstance(entry, Mapping)
                        and entry.get("triggering_leader", "") == ""
                    ):
                        count += 1
        return count

    def _get_live_state(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.state if state is not None else "unknown"

    def _seed_info(self, entity_id: str) -> tuple[str, float]:
        """Seed value + timestamp for a newly-seen leader."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return "unknown", 0.0
        return state.state, state.last_changed.timestamp()

    def _data_payload(self) -> dict[str, Any]:
        return {
            "leader_count": len(self._leader_set),
            "leaders": self.leaders,
            "features": self.features,
            "snapshots": self.snapshots,
        }

    # ── Core recompute ───────────────────────────────────────────────
    @callback
    def _recompute(
        self,
        *,
        changed_eid: str | None = None,
        cv_raw: str | None = None,
        changed_ts: float | None = None,
        manual: dict[str, Any] | None = None,
        snapshot_name: str | None = None,
        snapshot_payload: Any = None,
    ) -> None:
        """Recompute leaders/features/snapshots via the pure engine."""
        hass = self.hass

        labeled_ids = _labeled_leader_entity_ids(hass)
        self._leader_set = set(labeled_ids)
        labels_by_eid = {eid: _entity_label_names(hass, eid) for eid in labeled_ids}
        entity_ctx: dict[str, dict[str, str]] = {}
        for eid in labeled_ids:
            area_id, floor_id = _entity_area_floor(hass, eid)
            entity_ctx[eid] = {"area_id": area_id, "floor_id": floor_id}

        triples, errors = engine.build_triples(labels_by_eid, entity_ctx)
        sensor_labels = _entity_label_names(hass, FEATURES_SENSOR_ENTITY_ID)
        modes = engine.resolve_modes(triples.keys(), sensor_labels)

        # `features` must read the PREVIOUS leaders map (the changed
        # leader's previous_value chain), so compute it first.
        new_features = engine.update_features(
            self.features,
            self.leaders,
            triples,
            modes,
            labels_by_eid,
            self._get_live_state,
            changed_eid=changed_eid,
            cv_raw=cv_raw,
            changed_ts=changed_ts,
            manual=manual,
        )
        new_leaders = engine.update_leaders(
            self.leaders,
            labeled_ids,
            changed_eid=changed_eid,
            cv_raw=cv_raw,
            changed_ts=changed_ts,
            seed_getter=self._seed_info,
        )
        new_snapshots = engine.update_snapshots(
            self.snapshots, snapshot_name, snapshot_payload
        )

        self.leaders = new_leaders
        self.features = new_features
        self.snapshots = new_snapshots
        self._computed = True

        self._route_errors(errors, self._resolved_error_mode())
        self.async_set_updated_data(self._data_payload())


class LabeledFeatureAreasCoordinator(_BaseCoordinator):
    """Coordinator for ``sensor.labeled_feature_areas_state``.

    Data payload: ``{"area_count", "label_map"}``.
    """

    _error_source = "Labeled Feature Areas State"
    _sensor_entity_id = AREAS_SENSOR_ENTITY_ID

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(hass, config_entry, f"{DOMAIN}_areas")
        self.label_map: dict[str, Any] = {}
        self._area_count = 0
        self._restored = False
        self._computed = False
        self.async_set_updated_data(self._data_payload())

    async def async_setup(self) -> None:
        """Restore prior state, then register event listeners.

        During HA startup the initial recompute is deferred to
        ``EVENT_HOMEASSISTANT_STARTED`` so the restored ``label_map``
        publishes first — the downstream areas automation diffs the
        restored→live transition to retract Provides labels removed
        while HA was off. On a config-entry reload (HA already
        running) the recompute happens immediately.
        """
        await self._async_restore_last_attributes()
        for event_type in _REGISTRY_EVENTS:
            self._unsubs.append(
                self.hass.bus.async_listen(event_type, self._on_registry_updated)
            )
        self._unsubs.append(
            self.hass.bus.async_listen(EVENT_HOMEASSISTANT_STARTED, self._on_started)
        )
        if self.hass.state is CoreState.running:
            self._recompute()

    @callback
    def async_restore_attributes(self, attributes: Mapping[str, Any]) -> None:
        """Seed label_map from the last recorded attributes."""
        if self._restored or self._computed:
            return
        self._restored = True
        label_map = attributes.get("label_map")
        if isinstance(label_map, Mapping):
            self.label_map = dict(label_map)
            self.async_set_updated_data(self._data_payload())

    @callback
    def _on_registry_updated(self, _event: Event) -> None:
        if self._disabled:
            return
        self._recompute()

    @callback
    def _on_started(self, _event: Event) -> None:
        """Re-publish the current expected map on boot (idempotent)."""
        if self._disabled:
            return
        self._recompute()

    def _data_payload(self) -> dict[str, Any]:
        return {"area_count": self._area_count, "label_map": self.label_map}

    @callback
    def _recompute(self) -> None:
        """Rebuild label_map from the registries."""
        gated = _gated_areas(self.hass)
        label_map, errors = engine.build_label_map(gated)
        self._route_errors(errors, self._resolved_error_mode())

        area_count = len(gated)
        changed = label_map != self.label_map or area_count != self._area_count
        self.label_map = label_map
        self._area_count = area_count
        self._computed = True
        # Only push when something actually changed — the downstream
        # automation diffs from_state/to_state, so no-op writes are noise.
        if changed:
            self.async_set_updated_data(self._data_payload())

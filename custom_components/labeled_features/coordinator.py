"""Per-config-entry state machine for the Labeled Features integration."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.area_registry import EVENT_AREA_REGISTRY_UPDATED
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.entity_registry import EVENT_ENTITY_REGISTRY_UPDATED
from homeassistant.helpers.floor_registry import EVENT_FLOOR_REGISTRY_UPDATED
from homeassistant.helpers.label_registry import EVENT_LABEL_REGISTRY_UPDATED
from homeassistant.util import dt as dt_util

from .areas import build_label_map
from .const import (
    ATTR_FEATURES,
    ATTR_LEADERS,
    ATTR_SNAPSHOTS,
    CONF_DEFAULT_ERROR_MODE,
    CONF_DEFAULT_MODE,
    CONF_DEFAULT_SCRIPT_CALL_MODE,
    CONF_LEADER_LABEL,
    CONF_MODE_OVERRIDES,
    CONF_PREFIX,
    CONF_SCRIPT_CALL_MODE_OVERRIDES,
    DEFAULT_ERROR_MODE,
    DEFAULT_LEADER_LABEL,
    DEFAULT_MODE,
    DEFAULT_PREFIX,
    DEFAULT_SCRIPT_CALL_MODE,
    EVENT_SET_FEATURE,
    EVENT_SET_SNAPSHOT,
    MODE_LEADER,
    REGISTRY_DEBOUNCE_SECONDS,
    SCOPE_AREA,
    SCOPE_FLOOR,
)
from .errors import LabeledFeatureStop, async_handle_error, resolve_error_mode
from .features import (
    LeaderInfo,
    Triple,
    build_feature_entry,
    build_leader_entry,
    build_manual_entry,
    build_triple_map,
    carry_forward,
    current_value_for,
    evaluate_leader,
    fold,
    get_entry,
    is_skip_value,
    is_unreal,
    resolve_mode,
    seed_leader_entry,
    set_entry,
    triple_from_key,
    valid_feature_scope,
)
from .labels import (
    Registries,
    entity_area_id,
    entity_floor_id,
    entity_label_names,
    label_areas,
    label_entities,
)

_LOGGER = logging.getLogger(__package__)

ERROR_SOURCE = "Labeled Features"


def parse_overrides(
    raw: str | None, keyword: str, allowed: dict[str, str]
) -> dict[str, str]:
    """Parse newline-separated ``<Scoped Feature> <keyword>: <value>`` overrides.

    Returns a mapping of scoped feature name (``''`` for the bare, instance-wide
    form) to the normalized value. Unparsable lines are skipped; the config flow
    validates user input up front with :func:`validate_overrides`.
    """
    result: dict[str, str] = {}
    for scoped, value in _iter_override_lines(raw, keyword, allowed):
        result[scoped] = value
    return result


def validate_overrides(
    raw: str | None, keyword: str, allowed: dict[str, str]
) -> list[str]:
    """Return the list of lines that failed to parse."""
    invalid: list[str] = []
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _parse_override_line(stripped, keyword, allowed) is None:
            invalid.append(stripped)
    return invalid


def _iter_override_lines(raw: str | None, keyword: str, allowed: dict[str, str]):
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (parsed := _parse_override_line(stripped, keyword, allowed)) is not None:
            yield parsed


def _parse_override_line(
    line: str, keyword: str, allowed: dict[str, str]
) -> tuple[str, str] | None:
    """Parse one override line into ``(scoped_feature, value)``."""
    marker = f"{keyword}:"
    if marker not in line:
        return None
    head, _, tail = line.partition(marker)
    value = tail.strip()
    if value not in allowed:
        return None
    return head.strip(), allowed[value]


def snapshot_tree(value: Any) -> Any:
    """Return a detached copy of a plain mapping/sequence tree.

    Home Assistant compares state attributes shallowly, so a published
    attribute must never share an object with the coordinator's working state.
    Cheaper and safer than ``copy.deepcopy`` for the plain
    dict/list/str/float/bool payloads these attributes carry.
    """
    if isinstance(value, dict):
        return {key: snapshot_tree(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [snapshot_tree(item) for item in value]
    return value


class LabeledFeaturesCoordinator:
    """Owns the mutable state behind one instance's two sensors."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry

        # Working state. These are mutated in place; never hand them to an
        # entity directly (see `_publish_features`).
        self.leaders: dict[str, Any] = {}
        self.features: dict[str, Any] = {}
        self.snapshots: dict[str, Any] = {}
        self.label_map: dict[str, Any] = {}

        # Published (immutable-by-convention) snapshots handed to the entities.
        # Home Assistant compares attributes shallowly, so publishing the
        # working dicts would alias the previous State's attributes: an
        # in-place mutation would then compare equal and `async_set` would
        # suppress the `state_changed` event entirely. The consuming
        # automations diff that event, so every write must publish a fresh
        # object graph.
        self._published_leaders: dict[str, Any] = {}
        self._published_features: dict[str, Any] = {}
        self._published_snapshots: dict[str, Any] = {}
        self._published_label_map: dict[str, Any] = {}

        # Entity ids of our own sensors, filled in as they are added.
        self.features_entity_id: str | None = None
        self.areas_entity_id: str | None = None

        self._features_listeners: list[Callable[[], None]] = []
        self._areas_listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._started = False
        # Registry-derived caches, refreshed only on a registry reconcile, so
        # the state_changed firehose and every tick stay off the registries.
        self._leader_ids: set[str] = set()
        self._gated_area_ids: set[str] = set()
        # entity_id -> (label names, area_id, floor_id)
        self._leader_meta: dict[str, tuple[list[str], str, str]] = {}
        self._triple_map: dict[str, list[str]] = {}
        self._registry_debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=REGISTRY_DEBOUNCE_SECONDS,
            immediate=True,
            function=self._async_refresh_registry,
        )

    # ── options ──────────────────────────────────────────────────────────────

    def _option(self, key: str, default: Any) -> Any:
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    @property
    def prefix(self) -> str:
        """Return the object-id slug prefix (never changes after setup)."""
        return str(self.entry.data.get(CONF_PREFIX, DEFAULT_PREFIX))

    @property
    def leader_label(self) -> str:
        """Return the label that identifies leaders and gated areas."""
        return str(self._option(CONF_LEADER_LABEL, DEFAULT_LEADER_LABEL))

    @property
    def default_mode(self) -> str:
        """Return the default resolution mode."""
        return str(self._option(CONF_DEFAULT_MODE, DEFAULT_MODE)).lower()

    @property
    def default_script_call_mode(self) -> str:
        """Return the default script call mode (forward-looking in phase 1)."""
        return str(
            self._option(CONF_DEFAULT_SCRIPT_CALL_MODE, DEFAULT_SCRIPT_CALL_MODE)
        )

    @property
    def default_error_mode(self) -> str:
        """Return the default error mode."""
        return str(self._option(CONF_DEFAULT_ERROR_MODE, DEFAULT_ERROR_MODE)).lower()

    @property
    def mode_overrides(self) -> dict[str, str]:
        """Return parsed ``<Scoped F> Mode: <Mode>`` option overrides."""
        return parse_overrides(
            self._option(CONF_MODE_OVERRIDES, ""),
            "Mode",
            {"Leader": "leader", "Any": "any", "All": "all"},
        )

    @property
    def script_call_mode_overrides(self) -> dict[str, str]:
        """Return parsed ``<Scoped F> Script Call Mode: <Mode>`` overrides."""
        return parse_overrides(
            self._option(CONF_SCRIPT_CALL_MODE_OVERRIDES, ""),
            "Script Call Mode",
            {"Blocking": "Blocking", "NonBlocking": "NonBlocking"},
        )

    @property
    def config_attribute(self) -> dict[str, Any]:
        """Return the diagnostic ``config`` attribute for the features sensor."""
        return {
            "entry_id": self.entry.entry_id,
            "prefix": self.prefix,
            "leader_label": self.leader_label,
            "default_mode": self.default_mode,
            "default_script_call_mode": self.default_script_call_mode,
            "default_error_mode": self.default_error_mode,
            "mode_overrides": self.mode_overrides,
            "script_call_mode_overrides": self.script_call_mode_overrides,
        }

    # ── listener plumbing ────────────────────────────────────────────────────

    @callback
    def async_add_features_listener(
        self, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a write-state callback for the features sensor."""
        self._features_listeners.append(listener)

        def _remove() -> None:
            self._features_listeners.remove(listener)

        return _remove

    @callback
    def async_add_areas_listener(
        self, listener: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a write-state callback for the areas sensor."""
        self._areas_listeners.append(listener)

        def _remove() -> None:
            self._areas_listeners.remove(listener)

        return _remove

    # ── published state ──────────────────────────────────────────────────────

    @property
    def leader_count(self) -> int:
        """Return the cached number of leader entities."""
        return len(self._leader_ids)

    @property
    def gated_area_count(self) -> int:
        """Return the cached number of areas carrying the leader label."""
        return len(self._gated_area_ids)

    @property
    def published_features_attributes(self) -> dict[str, Any]:
        """Return the attribute payload for the features sensor."""
        return {
            ATTR_LEADERS: self._published_leaders,
            ATTR_FEATURES: self._published_features,
            ATTR_SNAPSHOTS: self._published_snapshots,
        }

    @property
    def published_label_map(self) -> dict[str, Any]:
        """Return the attribute payload for the areas sensor."""
        return self._published_label_map

    @callback
    def _publish_features(self) -> None:
        """Snapshot the working state into fresh objects for publication."""
        self._published_leaders = snapshot_tree(self.leaders)
        self._published_features = snapshot_tree(self.features)
        self._published_snapshots = snapshot_tree(self.snapshots)

    @callback
    def _publish_label_map(self) -> None:
        """Snapshot ``label_map`` into a fresh object for publication."""
        self._published_label_map = snapshot_tree(self.label_map)

    @callback
    def _write_features(self) -> None:
        """Publish a fresh snapshot and push one state write."""
        self._publish_features()
        for listener in list(self._features_listeners):
            listener()

    @callback
    def _write_areas(self) -> None:
        """Publish a fresh snapshot and push one state write."""
        self._publish_label_map()
        for listener in list(self._areas_listeners):
            listener()

    # ── restore ──────────────────────────────────────────────────────────────

    @callback
    def async_restore_features(
        self,
        leaders: Any,
        features: Any,
        snapshots: Any,
    ) -> None:
        """Adopt restored attributes for the features sensor."""
        self.leaders = snapshot_tree(leaders) if isinstance(leaders, dict) else {}
        self.features = snapshot_tree(features) if isinstance(features, dict) else {}
        self.snapshots = snapshot_tree(snapshots) if isinstance(snapshots, dict) else {}
        self._publish_features()

    @callback
    def async_restore_label_map(self, label_map: Any) -> None:
        """Adopt a restored ``label_map``."""
        self.label_map = snapshot_tree(label_map) if isinstance(label_map, dict) else {}
        self._publish_label_map()

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def async_start(self) -> None:
        """Subscribe to events and perform the initial reconcile."""
        hass = self.hass

        self._unsubs.append(
            hass.bus.async_listen(EVENT_STATE_CHANGED, self._async_state_changed)
        )
        self._unsubs.append(
            hass.bus.async_listen(EVENT_SET_FEATURE, self._async_set_feature_event)
        )
        self._unsubs.append(
            hass.bus.async_listen(EVENT_SET_SNAPSHOT, self._async_set_snapshot_event)
        )
        for event_type in (
            EVENT_LABEL_REGISTRY_UPDATED,
            EVENT_AREA_REGISTRY_UPDATED,
            EVENT_FLOOR_REGISTRY_UPDATED,
            EVENT_ENTITY_REGISTRY_UPDATED,
        ):
            self._unsubs.append(
                hass.bus.async_listen(event_type, self._async_registry_updated)
            )
        self._unsubs.append(
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._async_hass_started
            )
        )

        self._started = True
        # Reconcile once now so a fresh install (or a restart where the
        # registries changed while HA was down) has correct state immediately.
        await self._async_refresh_registry()

    @callback
    def async_shutdown(self) -> None:
        """Tear down every subscription."""
        self._started = False
        self._registry_debouncer.async_shutdown()
        while self._unsubs:
            self._unsubs.pop()()

    async def _async_hass_started(self, _event: Event) -> None:
        """Reconcile against the live registries once HA has started."""
        await self._async_refresh_registry()

    @callback
    def _async_registry_updated(self, _event: Event) -> None:
        """Schedule a debounced registry reconcile."""
        self.hass.async_create_task(self._registry_debouncer.async_call())

    # ── registry reconcile ───────────────────────────────────────────────────

    async def _async_refresh_registry(self) -> None:
        """Rebuild ``label_map`` and reconcile the leader/triple sets.

        Deliberately conservative on the ``features`` attribute: orphaned
        triples are dropped, but newly mapped triples are **not** seeded here.
        A new triple would look like a first-seed entry to
        ``automation.labeled_feature_leaders`` and dispatch followers purely
        because a label was edited. New triples appear on the leader's next
        state change, exactly as with the legacy template sensor.
        Also refreshes every registry-derived cache (leader ids, gated area
        ids, per-leader label/area/floor metadata and the triple map) so no
        other code path has to touch a registry.
        """
        try:
            regs = Registries.async_get(self.hass)
            leader_label = self.leader_label

            self.label_map = build_label_map(regs, leader_label)

            leader_ids = label_entities(regs, leader_label)
            self._leader_ids = set(leader_ids)
            self._gated_area_ids = set(label_areas(regs, leader_label))
            self._leader_meta = {
                entity_id: (
                    entity_label_names(regs, entity_id),
                    entity_area_id(regs, entity_id),
                    entity_floor_id(regs, entity_id),
                )
                for entity_id in leader_ids
            }
            self._triple_map = build_triple_map(
                [self._leader_info(entity_id) for entity_id in leader_ids]
            )
            self._reconcile_leaders(leader_ids)
        except LabeledFeatureStop:
            raise
        except Exception as err:
            await self._async_error(f"registry reconcile failed: {err}")
            return

        # Both counts can change without the attributes changing, so a
        # reconcile always writes both sensors exactly once.
        self._write_areas()
        self._write_features()

    def _reconcile_leaders(self, leader_ids: list[str]) -> None:
        """Sync the ``leaders`` map and drop orphaned ``features`` triples."""
        # Drop leaders that lost the label.
        for entity_id in list(self.leaders):
            if entity_id not in leader_ids:
                del self.leaders[entity_id]

        # Seed newly labeled leaders.
        for entity_id in leader_ids:
            if entity_id in self.leaders:
                continue
            state = self.hass.states.get(entity_id)
            current = (
                current_value_for(entity_id, state.state, dict(state.attributes))
                if state is not None
                else ""
            )
            timestamp = (
                state.last_changed.timestamp()
                if state is not None
                else dt_util.utcnow().timestamp()
            )
            self.leaders[entity_id] = seed_leader_entry(current, timestamp)

        self.features = carry_forward(self.features, self._triple_map)

    def triple_map_snapshot(self) -> dict[str, list[str]]:
        """Return the cached triple map (diagnostics helper)."""
        return snapshot_tree(self._triple_map)

    def _leader_info(self, entity_id: str) -> LeaderInfo:
        """Collect everything needed to evaluate one leader.

        Label / area / floor data comes from the registry cache refreshed on
        every registry reconcile, so this never touches a registry on the hot
        path. Only the live state is read per call.
        """
        state = self.hass.states.get(entity_id)
        stored = self.leaders.get(entity_id, {})
        stored = stored if isinstance(stored, dict) else {}
        raw_state = state.state if state is not None else ""
        current = (
            current_value_for(entity_id, raw_state, dict(state.attributes))
            if state is not None
            else ""
        )
        labels, area, floor = self._leader_meta.get(entity_id, ([], "", ""))
        return LeaderInfo(
            entity_id=entity_id,
            state=raw_state,
            labels=labels,
            area_id=area,
            floor_id=floor,
            current_value=str(stored.get("current_value", current)),
            previous_value=str(stored.get("previous_value", "")),
        )

    # ── state changed path ───────────────────────────────────────────────────

    @callback
    def _async_state_changed(self, event: Event) -> None:
        """Filter and handle a state_changed event."""
        if not self._started:
            return
        entity_id = event.data.get("entity_id")
        if not entity_id or entity_id in (
            self.features_entity_id,
            self.areas_entity_id,
        ):
            return
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        # Boot-restore / reconnect suppression: a leader with no real previous
        # state is not a user action.
        if old_state is None or is_unreal(old_state.state):
            return
        if entity_id not in self._leader_ids:
            return

        self.hass.async_create_task(
            self._async_handle_leader_change(entity_id, new_state)
        )

    async def _async_handle_leader_change(self, entity_id: str, new_state: Any) -> None:
        """Recompute leaders + features for one leader's state change."""
        try:
            timestamp = (
                new_state.last_changed.timestamp()
                if new_state.last_changed is not None
                else dt_util.utcnow().timestamp()
            )
            current_value = current_value_for(
                entity_id, new_state.state, dict(new_state.attributes)
            )

            previous_entry = self.leaders.get(entity_id)
            previous_current = ""
            if isinstance(previous_entry, dict):
                previous_current = str(previous_entry.get("current_value", ""))

            self.leaders[entity_id] = build_leader_entry(
                previous_entry, current_value, timestamp
            )

            if not is_skip_value(current_value):
                triple_map = self._triple_map
                self.features = carry_forward(self.features, triple_map)

                leader = self._leader_info(entity_id)
                # Evaluate against the freshly observed value, comparing to the
                # value tracked before this tick (direction labels need both).
                leader.current_value = current_value
                leader.previous_value = previous_current
                leader.state = new_state.state

                # Resolved once per tick and reused across every triple, and
                # every other leader is resolved at most once.
                sensor_labels = self._sensor_labels()
                overrides = self.mode_overrides
                default_mode = self.default_mode
                others: dict[str, LeaderInfo] = {entity_id: leader}

                for key, mapped_leaders in triple_map.items():
                    if entity_id not in mapped_leaders:
                        continue
                    triple = triple_from_key(key)
                    mode = resolve_mode(triple, sensor_labels, overrides, default_mode)
                    this_truth = evaluate_leader(leader, triple)
                    if mode == MODE_LEADER:
                        enabled = this_truth
                    else:
                        values: list[bool] = []
                        for other_id in mapped_leaders:
                            if other_id == entity_id:
                                values.append(this_truth)
                                continue
                            if other_id not in others:
                                others[other_id] = self._leader_info(other_id)
                            values.append(evaluate_leader(others[other_id], triple))
                        enabled = fold(mode, values)

                    set_entry(
                        self.features,
                        triple,
                        build_feature_entry(
                            get_entry(self.features, triple),
                            enabled,
                            mode,
                            timestamp,
                            entity_id,
                        ),
                    )
        except LabeledFeatureStop:
            return
        except Exception as err:
            await self._async_error(
                f"failed to process state change for {entity_id}: {err}"
            )
            return

        self._write_features()

    def _sensor_labels(self) -> list[str]:
        """Return the labels carried by our own features sensor entity."""
        if not self.features_entity_id:
            return []
        regs = Registries.async_get(self.hass)
        return entity_label_names(regs, self.features_entity_id)

    # ── manual write paths ───────────────────────────────────────────────────

    @callback
    def _async_set_feature_event(self, event: Event) -> None:
        """Handle a ``labeled_feature_set`` bus event."""
        if not self._started:
            return
        from .routing import async_event_owner  # avoids an import cycle

        if (
            async_event_owner(self.hass, dict(event.data), feature_event=True)
            is not self
        ):
            return
        self.hass.async_create_task(self.async_set_feature(dict(event.data)))

    @callback
    def _async_set_snapshot_event(self, event: Event) -> None:
        """Handle a ``labeled_feature_snapshot_set`` bus event."""
        if not self._started:
            return
        from .routing import async_event_owner  # avoids an import cycle

        if (
            async_event_owner(self.hass, dict(event.data), feature_event=False)
            is not self
        ):
            return
        self.hass.async_create_task(self.async_set_snapshot(dict(event.data)))

    async def async_set_feature(self, data: dict[str, Any]) -> None:
        """Write a manual override into ``features``."""
        target = str(data.get("target_feature", "")).strip()
        scope = str(data.get("scope", "")).strip().lower()
        scope_id = str(data.get("scope_id", "") or "")
        enabled = bool(data.get("enabled", False))
        timestamp = _as_float(data.get("timestamp"), dt_util.utcnow().timestamp())

        if not target or not valid_feature_scope(scope):
            await self._async_error(
                f"ignoring set_feature with target_feature={target!r} scope={scope!r}"
            )
            return
        if scope in (SCOPE_AREA, SCOPE_FLOOR) and not scope_id:
            await self._async_error(
                f"ignoring set_feature for {target!r}: {scope} scope needs a scope_id"
            )
            return

        triple = Triple(target, scope, scope_id)
        # Rebuild rather than mutate: `set_entry` alone would edit the nested
        # dict that the previous State already references, and Home Assistant
        # would then suppress the state_changed event the Leaders automation
        # diffs. `snapshot_tree` gives every level a fresh object.
        features = snapshot_tree(self.features)
        set_entry(
            features,
            triple,
            build_manual_entry(get_entry(features, triple), enabled, timestamp),
        )
        self.features = features
        self._write_features()

    async def async_set_snapshot(self, data: dict[str, Any]) -> None:
        """Merge or delete a snapshot entry."""
        name = str(data.get("snapshot_name", "")).strip()
        if not name:
            await self._async_error("ignoring snapshot write with no snapshot_name")
            return
        payload = data.get("payload")
        # Same reasoning as `async_set_feature`: replace, never mutate.
        snapshots = snapshot_tree(self.snapshots)
        if isinstance(payload, dict) and payload:
            snapshots[name] = snapshot_tree(payload)
        else:
            snapshots.pop(name, None)
        self.snapshots = snapshots
        self._write_features()

    # ── helpers ──────────────────────────────────────────────────────────────

    def owns_triple(self, feature: str, scope: str, scope_id: str) -> bool:
        """Return True when this instance leads or already tracks a triple."""
        triple = Triple(feature, scope, scope_id)
        if get_entry(self.features, triple) is not None:
            return True
        return triple.key in self._triple_map

    def owns_snapshot(self, snapshot_name: str) -> bool:
        """Return True when this instance already holds that snapshot."""
        return snapshot_name in self.snapshots

    async def _async_error(self, message: str) -> None:
        """Report an internal error through the resolved error tier."""
        mode = resolve_error_mode(self._sensor_labels(), self.default_error_mode)
        try:
            await async_handle_error(self.hass, mode, message, source=ERROR_SOURCE)
        except LabeledFeatureStop:
            # `stop` halts the unit of work; the caller has already returned.
            _LOGGER.debug("stop tier raised for: %s", message)


def _as_float(value: Any, default: float) -> float:
    """Coerce to float with a fallback."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


__all__ = [
    "LabeledFeaturesCoordinator",
    "parse_overrides",
    "validate_overrides",
]

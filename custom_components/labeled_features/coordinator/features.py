"""Coordinator for sensor.labeled_features_state.

Ports the two big Jinja blocks (`leaders`, `features`) plus the
`snapshots` merge from `configuration.yaml` into Python. Semantics match
the template one-to-one — see the plan file and configuration.yaml for
the reference behaviour.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_START
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from ..const import (
    BUTTON_DOMAINS,
    CONF_FEATURES_STATE_ENTITY_ID,
    CONF_LEADER_LABEL,
    DEFAULT_FEATURES_STATE_ENTITY_ID,
    DEFAULT_LEADER_LABEL,
    DOMAIN,
    EVENT_LABEL_REGISTRY_UPDATED,
    EVENT_LABELED_FEATURE_SET,
    EVENT_LABELED_FEATURE_SNAPSHOT_SET,
    EVENT_STATE_CHANGED,
    FEATURE_META,
    SCOPE_PREFIX_RE_ALT,
    SKIP_STATES,
    TRUTHY_STATES,
    prefix_for_leader_scope,
)
from ..models import FeatureEntry, LabeledFeaturesStateData, LeaderEntry
from ..registry_helpers import (
    entity_area_id,
    entity_labels,
    floor_of_area,
    label_entities,
    label_id_for_name,
)

_LOGGER = logging.getLogger(__name__)

_LEADER_RE = re.compile(rf"^({SCOPE_PREFIX_RE_ALT})Leader: (.+)$")
_INITIAL_PRESS_RE = re.compile(r"_initial_press$")


LabelsCache = dict[str, list[str]]


def _is_skip_value(value: str | None) -> bool:
    """`True` if a raw current/previous value should be treated as a skip.

    A skip value is either the `<n>_initial_press` suffix Zigbee2MQTT
    emits on the physical initial-press of a button, or one of HA's
    non-state sentinels (`unknown` / `unavailable` / `none`). Skip
    values do not advance `current_value` / `previous_value` and do not
    contribute a per-leader evaluation on their own tick.
    """

    if not value:
        return False
    if _INITIAL_PRESS_RE.search(value):
        return True
    return value.lower() in SKIP_STATES


@dataclass
class FeaturesCoordinatorContext:
    """Runtime configuration for the features coordinator."""

    leader_label: str
    sensor_entity_id: str


class LabeledFeaturesStateCoordinator(
    DataUpdateCoordinator[LabeledFeaturesStateData]
):
    """Owns the leaders / features / snapshots dataclass for one instance."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_features_state_{entry.entry_id}",
        )
        merged = {**entry.data, **entry.options}
        self.context = FeaturesCoordinatorContext(
            leader_label=(
                merged.get(CONF_LEADER_LABEL) or DEFAULT_LEADER_LABEL
            ).strip(),
            sensor_entity_id=(
                merged.get(CONF_FEATURES_STATE_ENTITY_ID)
                or DEFAULT_FEATURES_STATE_ENTITY_ID
            ).strip(),
        )
        # Seed with an empty dataclass; sensor.py may call
        # `apply_restore` before the first refresh to populate history.
        self.data = LabeledFeaturesStateData(feature_meta=dict(FEATURE_META))
        self._unsubs: list[callable] = []
        # Cached label_id resolution — used by the state_changed hot
        # path to check "is this a leader?" without a full registry scan.
        # Invalidated on any label_registry_updated event and on
        # apply_context (leader label rename).
        self._leader_label_id: str | None = None
        # Monotonic version bumped on every mutation. Sensor uses this
        # to memoise the serialised attributes view.
        self._data_version: int = 0

    def _get_leader_label_id(self) -> str | None:
        if self._leader_label_id is None:
            self._leader_label_id = label_id_for_name(
                self.hass, self.context.leader_label
            )
        return self._leader_label_id

    def _bump_version(self) -> None:
        self._data_version += 1

    @property
    def data_version(self) -> int:
        return self._data_version

    # ── Public wiring ───────────────────────────────────────────────────
    def async_subscribe(self) -> None:
        bus = self.hass.bus.async_listen
        self._unsubs.append(bus(EVENT_STATE_CHANGED, self._on_state_changed))
        self._unsubs.append(
            bus(EVENT_LABELED_FEATURE_SET, self._on_manual_override)
        )
        self._unsubs.append(
            bus(EVENT_LABELED_FEATURE_SNAPSHOT_SET, self._on_snapshot_set)
        )
        # Label-registry changes might add/remove a leader; force a
        # refresh so orphaned entries drop and newly-labeled entities
        # get their first tick.
        self._unsubs.append(
            bus(EVENT_LABEL_REGISTRY_UPDATED, self._on_registry_updated)
        )
        self._unsubs.append(
            bus(EVENT_HOMEASSISTANT_START, self._on_registry_updated)
        )

    def async_unsubscribe(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    def apply_context(self, entry: ConfigEntry) -> None:
        merged = {**entry.data, **entry.options}
        self.context = FeaturesCoordinatorContext(
            leader_label=(
                merged.get(CONF_LEADER_LABEL) or DEFAULT_LEADER_LABEL
            ).strip(),
            sensor_entity_id=(
                merged.get(CONF_FEATURES_STATE_ENTITY_ID)
                or DEFAULT_FEATURES_STATE_ENTITY_ID
            ).strip(),
        )
        # Leader label may have been renamed — invalidate the cache.
        self._leader_label_id = None

    def apply_restore(self, restored: dict[str, Any] | None) -> None:
        """Merge restored attribute data into the coordinator's state."""

        if not restored:
            return
        self.data.apply_restore(restored)
        self._bump_version()

    # ── Event handlers ──────────────────────────────────────────────────
    @callback
    def _on_state_changed(self, event: Event) -> None:
        eid = event.data.get("entity_id")
        if not eid:
            return
        # Cheap "is this a leader?" gate first. `state_changed` is HA's
        # firehose; the vast majority of events aren't from a leader
        # entity and we should reject them without scanning the whole
        # registry.
        leader_lid = self._get_leader_label_id()
        if leader_lid is None:
            return
        ent = er.async_get(self.hass).async_get(eid)
        if ent is None or leader_lid not in (ent.labels or set()):
            return
        old_state = event.data.get("old_state")
        # Reject boot / reconnect events without a real prior state.
        if old_state is None:
            return
        old_state_val = (
            getattr(old_state, "state", None)
            if not isinstance(old_state, dict)
            else old_state.get("state")
        )
        if (
            old_state_val is None
            or str(old_state_val).lower() in SKIP_STATES
        ):
            return
        # Only build the full leader set now that we know we're going
        # to do work. It's still used inside `_rebuild_for_state_changed`
        # for the orphan-drop pass.
        leaders = set(label_entities(self.hass, self.context.leader_label))
        new_state = event.data.get("new_state")
        self._rebuild_for_state_changed(eid, new_state, leaders)
        self._bump_version()
        self.async_set_updated_data(self.data)

    @callback
    def _on_manual_override(self, event: Event) -> None:
        self._apply_manual_override(event.data)
        self._bump_version()
        self.async_set_updated_data(self.data)

    @callback
    def _on_snapshot_set(self, event: Event) -> None:
        self._apply_snapshot(event.data)
        self._bump_version()
        self.async_set_updated_data(self.data)

    @callback
    def _on_registry_updated(self, _event: Event) -> None:
        # Registry / start events: drop orphans and freshen the leader
        # map without touching feature entries beyond what the orphan
        # logic already covers. Also invalidate the leader-label-id
        # cache in case the label was created/renamed.
        self._leader_label_id = None
        self._reconcile_leaders_and_orphans()
        self._bump_version()
        self.async_set_updated_data(self.data)

    # ── Manual refresh entrypoint (tests, reload) ───────────────────────
    async def async_config_entry_first_refresh(self) -> None:  # type: ignore[override]
        self._reconcile_leaders_and_orphans()
        self._bump_version()
        # The DataUpdateCoordinator base expects _async_update_data to
        # exist; we override behaviour by explicitly setting data.
        self.async_set_updated_data(self.data)

    # ── Rebuild helpers ─────────────────────────────────────────────────
    def _reconcile_leaders_and_orphans(self) -> None:
        """Bring `leaders` in sync with the label registry and drop orphans."""

        current_leaders = set(label_entities(self.hass, self.context.leader_label))
        # Drop leaders that no longer carry the label.
        self.data.leaders = {
            eid: entry
            for eid, entry in self.data.leaders.items()
            if eid in current_leaders
        }
        # Add stub entries for newly-labeled leaders.
        for eid in current_leaders:
            if eid in self.data.leaders:
                continue
            self.data.leaders[eid] = self._make_leader_stub(eid)
        # Orphan drop on features: any (feature, scope, scope_id) whose
        # leader mapping is empty AND whose entry is not a manual
        # override (`triggering_leader != ''`) is removed.
        triple_map = self._build_triple_index()
        self._drop_orphans(triple_map)

    def _drop_orphans(
        self,
        triple_map: dict[tuple[str, str, str], list[str]],
    ) -> None:
        new_features: dict[str, dict[str, dict[str, FeatureEntry]]] = {}
        for fname, scopes in self.data.features.items():
            for scope, sids in scopes.items():
                for scope_id, entry in sids.items():
                    has_leader = (fname, scope, scope_id) in triple_map
                    is_manual = (entry.triggering_leader or "") == ""
                    if has_leader or is_manual:
                        new_features.setdefault(fname, {}).setdefault(
                            scope, {}
                        )[scope_id] = entry
        self.data.features = new_features

    def _labels(self, entity_id: str, cache: LabelsCache | None) -> list[str]:
        """Return `entity_labels(entity_id)`, cached for the current tick."""

        if cache is None:
            return entity_labels(self.hass, entity_id)
        cached = cache.get(entity_id)
        if cached is None:
            cached = entity_labels(self.hass, entity_id)
            cache[entity_id] = cached
        return cached

    def _make_leader_stub(self, entity_id: str) -> LeaderEntry:
        """Fresh `LeaderEntry` for a newly-labeled leader."""

        state = self.hass.states.get(entity_id)
        return LeaderEntry(
            current_value=state.state if state is not None else "",
            previous_value="",
            last_changed_timestamp=(
                state.last_changed.timestamp()
                if state is not None and state.last_changed is not None
                else 0.0
            ),
        )

    def _build_triple_index(
        self,
        labels_cache: LabelsCache | None = None,
    ) -> dict[tuple[str, str, str], list[str]]:
        """(feature, scope, scope_id) → [leader_entity_ids]."""

        triples: dict[tuple[str, str, str], list[str]] = {}
        for eid in label_entities(self.hass, self.context.leader_label):
            aid = entity_area_id(self.hass, eid)
            floor = floor_of_area(self.hass, aid) if aid else ""
            for lbl in self._labels(eid, labels_cache):
                match = _LEADER_RE.match(lbl)
                if match is None:
                    continue
                prefix = match.group(1).strip()
                fname = match.group(2).strip()
                if not fname:
                    continue
                if prefix == "Area":
                    scope, scope_id = "area", aid
                elif prefix == "Floor":
                    scope, scope_id = "floor", floor
                else:
                    scope, scope_id = "global", ""
                if scope == "area" and not scope_id:
                    continue
                if scope == "floor" and not scope_id:
                    continue
                key = (fname, scope, scope_id)
                if eid not in triples.setdefault(key, []):
                    triples[key].append(eid)
        return triples

    def _resolve_mode(
        self, fname: str, scope: str, labels_cache: LabelsCache | None = None
    ) -> str:
        """Read `<Scoped F> Mode: Leader|Any|All` from sensor labels."""

        prefix = prefix_for_leader_scope(scope)
        target = f"{prefix}{fname} Mode: "
        for lbl in self._labels(self.context.sensor_entity_id, labels_cache):
            if lbl.startswith(target):
                val = lbl[len(target) :].strip().lower()
                if val in ("leader", "any", "all"):
                    return val
        return "leader"

    def _eval_leader(
        self,
        entity_id: str,
        scope_prefix: str,
        fname: str,
        current_value: str,
        previous_value: str,
        labels_cache: LabelsCache | None = None,
    ) -> bool:
        """Port of the `eval_leader` Jinja macro."""

        labels = self._labels(entity_id, labels_cache)
        state = self.hass.states.get(entity_id)
        domain = entity_id.split(".", 1)[0]

        inc_lbl = f"{scope_prefix}{fname} Increasing: True" in labels
        dec_lbl = f"{scope_prefix}{fname} Decreasing: True" in labels

        base: bool
        if inc_lbl or dec_lbl:
            cur_n = _to_float(current_value)
            prev_n = _to_float(previous_value)
            has_movement = cur_n is not None and prev_n is not None
            is_inc = has_movement and cur_n > prev_n
            is_dec = has_movement and cur_n < prev_n
            base = (inc_lbl and is_inc) or (dec_lbl and is_dec)
        else:
            en_val = _extract_value_after_prefix(
                labels, f"{scope_prefix}{fname} Enable: "
            )
            dis_val = _extract_value_after_prefix(
                labels, f"{scope_prefix}{fname} Disable: "
            )
            st_value = state.state if state is not None else ""
            if en_val != "" or dis_val != "":
                by_en = en_val != "" and st_value == en_val
                by_dis = dis_val != "" and st_value == dis_val
                if en_val != "" and dis_val != "":
                    base = by_en and not by_dis
                elif en_val != "":
                    base = by_en
                else:
                    base = not by_dis
            elif domain in BUTTON_DOMAINS:
                base = True
            else:
                base = (st_value == fname) or (
                    str(st_value).lower() in TRUTHY_STATES
                )

        inverted = f"{scope_prefix}{fname} Invert: True" in labels
        return (not base) if inverted else base

    # ── State-changed rebuild ───────────────────────────────────────────
    def _rebuild_for_state_changed(
        self,
        entity_id: str,
        new_state: Any,
        current_leader_set: set[str],
    ) -> None:
        """Mirror the `features` and `leaders` template blocks."""

        # Extract raw current value (event.event_type on event domain,
        # else state.state).
        new_state_state = _get_state_value(new_state)
        new_state_attrs = _get_state_attrs(new_state)
        domain = entity_id.split(".", 1)[0]
        if domain == "event" and new_state is not None:
            cv_raw = new_state_attrs.get("event_type", new_state_state) or new_state_state or ""
        else:
            cv_raw = new_state_state or ""
        cv_raw = str(cv_raw)

        is_skip = _is_skip_value(cv_raw)

        prev_entry = self.data.leaders.get(entity_id, LeaderEntry())
        ts_new = _extract_last_changed(new_state)

        if is_skip:
            cv = prev_entry.current_value
            cv_ts = prev_entry.last_changed_timestamp or ts_new
        else:
            cv = cv_raw
            cv_ts = ts_new

        old_cv = prev_entry.current_value
        old_pv = prev_entry.previous_value
        prev_cv_raw = old_cv if cv != old_cv else old_pv
        prev_cv = "" if _is_skip_value(prev_cv_raw) else prev_cv_raw

        # Per-tick registry-labels cache: every subsequent lookup for
        # the same entity in this rebuild pass reuses one registry read.
        labels_cache: LabelsCache = {}

        # Reconcile leaders map: drop orphans, add stubs, then update the
        # changed entity.
        self.data.leaders = {
            eid: entry
            for eid, entry in self.data.leaders.items()
            if eid in current_leader_set and eid != entity_id
        }
        for other in current_leader_set:
            if other == entity_id or other in self.data.leaders:
                continue
            self.data.leaders[other] = self._make_leader_stub(other)
        self.data.leaders[entity_id] = LeaderEntry(
            current_value=cv,
            previous_value=prev_cv,
            last_changed_timestamp=cv_ts,
        )

        if is_skip:
            # We still refreshed the leaders map (registry drops); no
            # feature re-evaluation to do because the current_value did
            # not advance.
            triple_map = self._build_triple_index(labels_cache)
            self._drop_orphans(triple_map)
            return

        triple_map = self._build_triple_index(labels_cache)

        # Carry-through pass: drop orphans + preserve manual overrides.
        self._drop_orphans(triple_map)

        # For each triple this leader participates in, recompute enabled.
        is_button_leader = domain in BUTTON_DOMAINS
        for (fname, scope, scope_id), leaders_list in triple_map.items():
            if entity_id not in leaders_list:
                continue
            scope_prefix = prefix_for_leader_scope(scope)
            mode = self._resolve_mode(fname, scope, labels_cache)

            this_truth = self._eval_leader(
                entity_id, scope_prefix, fname, cv, prev_cv, labels_cache
            )

            if mode == "leader":
                new_enabled = this_truth
            else:
                values: list[bool] = []
                for other_eid in leaders_list:
                    if other_eid == entity_id:
                        values.append(this_truth)
                        continue
                    other_state = self.hass.states.get(other_eid)
                    other_cv = other_state.state if other_state is not None else ""
                    other_prev = self.data.leaders.get(
                        other_eid, LeaderEntry()
                    ).previous_value
                    values.append(
                        self._eval_leader(
                            other_eid,
                            scope_prefix,
                            fname,
                            other_cv,
                            other_prev,
                            labels_cache,
                        )
                    )
                new_enabled = all(values) if mode == "all" else any(values)

            existing = (
                self.data.features.get(fname, {})
                .get(scope, {})
                .get(scope_id)
            )
            prev_enabled = existing.enabled if existing is not None else None
            prev_ts = existing.last_changed_timestamp if existing is not None else cv_ts
            flipped = (
                prev_enabled is None or prev_enabled != new_enabled or is_button_leader
            )
            new_ts = cv_ts if flipped else prev_ts
            new_entry = FeatureEntry(
                enabled=new_enabled,
                mode=mode,
                last_changed_timestamp=new_ts,
                triggering_leader=entity_id,
            )
            self.data.features.setdefault(fname, {}).setdefault(scope, {})[
                scope_id
            ] = new_entry

    # ── Manual override / snapshot ──────────────────────────────────────
    def _apply_manual_override(self, data: dict[str, Any]) -> None:
        target = str(data.get("target_feature") or "").strip()
        scope = str(data.get("scope") or "").strip().lower()
        scope_id = str(data.get("scope_id") or "")
        enabled = bool(data.get("enabled", False))
        ts = _coerce_ts(data.get("timestamp"))

        if not target or scope not in ("area", "floor", "global"):
            return
        prev = (
            self.data.features.get(target, {}).get(scope, {}).get(scope_id)
        )
        mode = prev.mode if prev is not None else "leader"
        self.data.features.setdefault(target, {}).setdefault(scope, {})[
            scope_id
        ] = FeatureEntry(
            enabled=enabled,
            mode=mode,
            last_changed_timestamp=ts,
            triggering_leader="",
        )

    def _apply_snapshot(self, data: dict[str, Any]) -> None:
        snapshot_name = str(data.get("snapshot_name") or "").strip()
        payload = data.get("payload")
        if not snapshot_name:
            return
        new_snaps = copy.deepcopy(self.data.snapshots)
        if isinstance(payload, dict) and payload:
            new_snaps[snapshot_name] = dict(payload)
        else:
            new_snaps.pop(snapshot_name, None)
        self.data.snapshots = new_snaps


# ── Helpers ─────────────────────────────────────────────────────────────


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_state_value(state: Any) -> str:
    if state is None:
        return ""
    if isinstance(state, dict):
        return str(state.get("state", ""))
    return str(getattr(state, "state", ""))


def _get_state_attrs(state: Any) -> dict[str, Any]:
    if state is None:
        return {}
    if isinstance(state, dict):
        attrs = state.get("attributes") or {}
        return attrs if isinstance(attrs, dict) else {}
    attrs = getattr(state, "attributes", None)
    return attrs if isinstance(attrs, dict) else {}


def _extract_last_changed(state: Any) -> float:
    if state is None:
        return dt_util.utcnow().timestamp()
    lc = None
    if isinstance(state, dict):
        lc = state.get("last_changed")
    else:
        lc = getattr(state, "last_changed", None)
    if lc is None:
        return dt_util.utcnow().timestamp()
    if hasattr(lc, "timestamp"):
        return float(lc.timestamp())
    try:
        return float(lc)
    except (TypeError, ValueError):
        return dt_util.utcnow().timestamp()


def _extract_value_after_prefix(labels: list[str], prefix: str) -> str:
    for lbl in labels:
        if lbl.startswith(prefix):
            return lbl[len(prefix) :]
    return ""


def _coerce_ts(value: Any) -> float:
    ts = _to_float(value)
    if ts is None:
        return dt_util.utcnow().timestamp()
    return ts


# Re-exports to make the type available under the package alias without
# forcing consumers to import from `.models`.
__all__ = [
    "FeatureEntry",
    "LabeledFeaturesStateCoordinator",
    "LeaderEntry",
]

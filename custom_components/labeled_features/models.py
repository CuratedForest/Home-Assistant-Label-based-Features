"""Dataclasses for the Labeled Features coordinators.

These mirror the shape of the template-sensor attributes documented in
`configuration.yaml` and in the design plan, so downstream scripts that
read them via `state_attr('sensor.labeled_features_state', '<attr>')`
continue to see the exact same structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LeaderEntry:
    """Per-leader diagnostic and substitution surface.

    Serialised into the sensor's `leaders` attribute keyed by entity_id.
    """

    current_value: str = ""
    previous_value: str = ""
    last_changed_timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_value": self.current_value,
            "previous_value": self.previous_value,
            "last_changed_timestamp": self.last_changed_timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LeaderEntry:
        return cls(
            current_value=str(data.get("current_value", "")),
            previous_value=str(data.get("previous_value", "")),
            last_changed_timestamp=float(data.get("last_changed_timestamp", 0.0)),
        )


@dataclass
class FeatureEntry:
    """Per-(feature, scope, scope_id) evaluation result.

    Serialised into `features[feature][scope][scope_id]`.
    """

    enabled: bool = False
    mode: str = "leader"
    last_changed_timestamp: float = 0.0
    triggering_leader: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "mode": self.mode,
            "last_changed_timestamp": self.last_changed_timestamp,
            "triggering_leader": self.triggering_leader,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureEntry:
        return cls(
            enabled=bool(data.get("enabled", False)),
            mode=str(data.get("mode", "leader")),
            last_changed_timestamp=float(data.get("last_changed_timestamp", 0.0)),
            triggering_leader=str(data.get("triggering_leader", "")),
        )


@dataclass
class LabelMapEntry:
    """One row in `sensor.labeled_feature_areas_state.label_map`.

    Keyed in the outer map by `f"{scope_id}||{label}"`.
    """

    scope_id: str
    label: str
    scope: str  # "area" | "floor" | "none"
    component: str  # default "select"; overridable via a modifier label
    declaring_area_id: str

    def to_dict(self) -> dict[str, Any]:
        # Nested `label_data` mirrors the shape the automation used to
        # consume from the template sensor.
        return {
            "scope_id": self.scope_id,
            "label": self.label,
            "scope": self.scope,
            "component": self.component,
            "declaring_area_id": self.declaring_area_id,
            "label_data": {
                "scope": self.scope,
                "scope_id": self.scope_id,
                "component": self.component,
                "declaring_area_id": self.declaring_area_id,
            },
        }


@dataclass
class LabeledFeaturesStateData:
    """All four attributes of `sensor.labeled_features_state` in one bag.

    The coordinator holds one of these; the sensor mirrors it into
    `extra_state_attributes` and its `RestoreEntity` payload.
    """

    feature_meta: dict[str, dict[str, str]] = field(default_factory=dict)
    leaders: dict[str, LeaderEntry] = field(default_factory=dict)
    # features[feature][scope][scope_id] = FeatureEntry
    features: dict[str, dict[str, dict[str, FeatureEntry]]] = field(default_factory=dict)
    snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def leader_count(self) -> int:
        return len(self.leaders)

    # ── Serialisation helpers ───────────────────────────────────────────
    def leaders_as_dict(self) -> dict[str, dict[str, Any]]:
        return {eid: entry.to_dict() for eid, entry in self.leaders.items()}

    def features_as_dict(self) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
        return {
            fname: {
                scope: {sid: entry.to_dict() for sid, entry in sids.items()}
                for scope, sids in scopes.items()
            }
            for fname, scopes in self.features.items()
        }

    # ── Restore helpers ─────────────────────────────────────────────────
    def to_restore(self) -> dict[str, Any]:
        return {
            "leaders": self.leaders_as_dict(),
            "features": self.features_as_dict(),
            "snapshots": self.snapshots,
        }

    def apply_restore(self, data: dict[str, Any] | None) -> None:
        if not data:
            return
        raw_leaders = data.get("leaders") or {}
        if isinstance(raw_leaders, dict):
            self.leaders = {
                eid: LeaderEntry.from_dict(v)
                for eid, v in raw_leaders.items()
                if isinstance(v, dict)
            }
        raw_features = data.get("features") or {}
        rebuilt: dict[str, dict[str, dict[str, FeatureEntry]]] = {}
        if isinstance(raw_features, dict):
            for fname, scopes in raw_features.items():
                if not isinstance(scopes, dict):
                    continue
                rebuilt[fname] = {}
                for scope, sids in scopes.items():
                    if not isinstance(sids, dict):
                        continue
                    rebuilt[fname][scope] = {
                        sid: FeatureEntry.from_dict(v)
                        for sid, v in sids.items()
                        if isinstance(v, dict)
                    }
        self.features = rebuilt
        raw_snap = data.get("snapshots") or {}
        if isinstance(raw_snap, dict):
            self.snapshots = {
                k: v for k, v in raw_snap.items() if isinstance(v, dict)
            }

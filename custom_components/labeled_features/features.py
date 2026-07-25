"""Pure logic for the Labeled Features State sensor.

Everything in this module is a pure function over explicit inputs so the truth
function, the triple map, the mode fold and the orphan-drop rules can be tested
directly without a running Home Assistant.

The behavior here reproduces the legacy trigger-based template sensor
(`sensor.labeled_features_state`) exactly, including its documented quirks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import (
    ATTR_CURRENT_VALUE,
    ATTR_ENABLED,
    ATTR_LAST_CHANGED_TIMESTAMP,
    ATTR_MODE,
    ATTR_PREVIOUS_VALUE,
    ATTR_TRIGGERING_LEADER,
    FIRE_ALWAYS_DOMAINS,
    MODE_ALL,
    MODE_ANY,
    MODE_LEADER,
    SCOPE_AREA,
    SCOPE_FLOOR,
    SCOPE_GLOBAL,
    SKIP_EVENT_SUFFIX,
    TRUTHY_STATES,
    UNREAL_STATES,
)
from .labels import parse_grouping_label, scoped_feature

TRIPLE_SEPARATOR = "||"


@dataclass(frozen=True, slots=True)
class Triple:
    """A ``(feature, scope, scope_id)`` triple."""

    feature: str
    scope: str
    scope_id: str

    @property
    def key(self) -> str:
        """Return the flat key used for internal maps."""
        return TRIPLE_SEPARATOR.join((self.feature, self.scope, self.scope_id))

    @property
    def label_prefix(self) -> str:
        """Return the scoped feature name used as the optional-label prefix."""
        return scoped_feature(self.scope, self.feature)


@dataclass(slots=True)
class LeaderInfo:
    """Everything needed to evaluate one leader entity."""

    entity_id: str
    state: str
    labels: list[str] = field(default_factory=list)
    area_id: str = ""
    floor_id: str = ""
    # `current_value` differs from `state` for event-domain entities.
    current_value: str = ""
    previous_value: str = ""

    @property
    def domain(self) -> str:
        """Return the entity's domain."""
        return self.entity_id.split(".")[0]


def is_unreal(value: Any) -> bool:
    """Return True for unknown / unavailable / none-ish values."""
    return str(value).lower() in UNREAL_STATES


def is_skip_value(value: Any) -> bool:
    """Return True when a value must not overwrite the tracked leader value.

    Matches the legacy sensor: ``*_initial_press`` events and unreal states are
    not "the user did the thing", so the previously tracked value is carried
    forward instead.
    """
    text = str(value)
    return text.endswith(SKIP_EVENT_SUFFIX) or is_unreal(text)


def current_value_for(entity_id: str, state: str, attributes: dict[str, Any]) -> str:
    """Return the tracked ``current_value`` for a leader's state.

    Event-domain entities expose the meaningful value as the ``event_type``
    attribute; their state is an ISO timestamp.
    """
    if entity_id.split(".")[0] == "event":
        event_type = attributes.get("event_type")
        if event_type is not None:
            return str(event_type)
    return str(state)


# ── leaders attribute ────────────────────────────────────────────────────────


def build_leader_entry(
    previous_entry: dict[str, Any] | None,
    current_value: str,
    timestamp: float,
) -> dict[str, Any]:
    """Build a ``leaders[<entity_id>]`` entry for a changed leader.

    * Skip-values carry the previous ``current_value`` and timestamp forward.
    * ``previous_value`` becomes the prior ``current_value`` when it changed,
      otherwise the prior ``previous_value``; skip-ish results are blanked.
    """
    prev = previous_entry if isinstance(previous_entry, dict) else {}
    prev_current = str(prev.get(ATTR_CURRENT_VALUE, ""))
    prev_previous = str(prev.get(ATTR_PREVIOUS_VALUE, ""))

    if is_skip_value(current_value):
        value = prev.get(ATTR_CURRENT_VALUE, current_value)
        stamp = float(prev.get(ATTR_LAST_CHANGED_TIMESTAMP, timestamp))
    else:
        value = current_value
        stamp = float(timestamp)

    previous = prev_current if str(value) != prev_current else prev_previous
    if is_skip_value(previous):
        previous = ""

    return {
        ATTR_CURRENT_VALUE: value,
        ATTR_PREVIOUS_VALUE: previous,
        ATTR_LAST_CHANGED_TIMESTAMP: stamp,
    }


def seed_leader_entry(current_value: str, timestamp: float) -> dict[str, Any]:
    """Build the initial entry for a newly labeled leader."""
    return {
        ATTR_CURRENT_VALUE: current_value,
        ATTR_PREVIOUS_VALUE: "",
        ATTR_LAST_CHANGED_TIMESTAMP: float(timestamp),
    }


# ── truth function ───────────────────────────────────────────────────────────


def evaluate_leader(leader: LeaderInfo, triple: Triple) -> bool:
    """Evaluate one leader's truth value for one triple.

    Resolution order (mirrors the docs and the legacy sensor):

    1. Direction labels ``<pfx><F> Increasing|Decreasing: True`` — numeric
       comparison of ``current_value`` against ``previous_value``. Both may be
       present, in which case they are OR'd. Non-numeric or first update -> False.
    2. ``<pfx><F> Enable: <v>`` / ``<pfx><F> Disable: <v>`` compared against the
       entity's **state**.
    3. ``event`` / ``button`` domains -> True.
    4. Default truth: ``state == <F>`` (case-sensitive) OR the state is in the
       generic truthy set (case-insensitive).

    ``<pfx><F> Invert: True`` flips the result afterwards.
    """
    prefix = triple.label_prefix
    labels = leader.labels

    increasing = f"{prefix} Increasing: True" in labels
    decreasing = f"{prefix} Decreasing: True" in labels

    if increasing or decreasing:
        base = _evaluate_direction(leader, increasing, decreasing)
    else:
        base = _evaluate_value(leader, triple, prefix)

    if f"{prefix} Invert: True" in labels:
        return not base
    return base


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _evaluate_direction(leader: LeaderInfo, increasing: bool, decreasing: bool) -> bool:
    current = _to_float(leader.current_value)
    previous = _to_float(leader.previous_value)
    if current is None or previous is None:
        return False
    if increasing and current > previous:
        return True
    return bool(decreasing and current < previous)


def _first_label_value(labels: list[str], key: str) -> str:
    """Return the first ``<key>: <value>`` value, requiring a non-empty value."""
    prefix = f"{key}: "
    for label in labels:
        if label.startswith(prefix):
            value = label[len(prefix) :]
            if value:
                return value
    return ""


def _evaluate_value(leader: LeaderInfo, triple: Triple, prefix: str) -> bool:
    labels = leader.labels
    # NOTE: the comparison uses the entity's *state*, not `current_value`. On
    # event-domain leaders that means the ISO timestamp is compared, so
    # Enable/Disable labels never match there. This is a faithful reproduction
    # of the legacy template sensor; see KNOWN_DIVERGENCES in the README.
    state = leader.state
    enable_value = _first_label_value(labels, f"{prefix} Enable")
    disable_value = _first_label_value(labels, f"{prefix} Disable")

    if enable_value or disable_value:
        by_enable = bool(enable_value) and state == enable_value
        by_disable = bool(disable_value) and state == disable_value
        if enable_value and disable_value:
            return by_enable and not by_disable
        if enable_value:
            return by_enable
        return not by_disable

    if leader.domain in FIRE_ALWAYS_DOMAINS:
        return True

    return state == triple.feature or state.lower() in TRUTHY_STATES


# ── triple map ───────────────────────────────────────────────────────────────


def build_triple_map(leaders: list[LeaderInfo]) -> dict[str, list[str]]:
    """Map ``triple.key`` -> ordered list of leader entity ids.

    Leaders whose scope cannot be resolved (``Area Leader:`` on an entity with
    no area, ``Floor Leader:`` with no floor) are skipped for that label.
    """
    triples: dict[str, list[str]] = {}
    for leader in leaders:
        for label in leader.labels:
            parsed = parse_grouping_label(label, "Leader")
            if parsed is None:
                continue
            scope, feature = parsed
            if scope == SCOPE_AREA:
                scope_id = leader.area_id
            elif scope == SCOPE_FLOOR:
                scope_id = leader.floor_id
            else:
                scope_id = ""
            if scope in (SCOPE_AREA, SCOPE_FLOOR) and not scope_id:
                continue
            key = Triple(feature, scope, scope_id).key
            entries = triples.setdefault(key, [])
            if leader.entity_id not in entries:
                entries.append(leader.entity_id)
    return triples


def triple_from_key(key: str) -> Triple:
    """Rebuild a Triple from its flat key."""
    feature, scope, scope_id = key.split(TRIPLE_SEPARATOR, 2)
    return Triple(feature, scope, scope_id)


# ── mode resolution ──────────────────────────────────────────────────────────


def resolve_mode(
    triple: Triple,
    sensor_labels: list[str],
    option_overrides: dict[str, str],
    default_mode: str,
) -> str:
    """Resolve the resolution mode for a triple.

    Precedence: a ``<Scoped F> Mode: Leader|Any|All`` label on the sensor
    entity, then the parsed config-entry override for the same scoped feature,
    then the entry's default mode, then ``leader``.
    """
    key = f"{triple.label_prefix} Mode: "
    for label in sensor_labels:
        if label.startswith(key):
            value = label[len(key) :]
            if value in ("Leader", "Any", "All"):
                return value.lower()
    if (override := option_overrides.get(triple.label_prefix)) is not None:
        return override
    return default_mode or MODE_LEADER


def fold(mode: str, values: list[bool]) -> bool:
    """Fold per-leader truth values per the resolution mode."""
    if not values:
        return False
    if mode == MODE_ALL:
        return all(values)
    if mode == MODE_ANY:
        return any(values)
    # `leader` mode never folds; the caller passes a single value.
    return bool(values[0])


# ── features attribute ───────────────────────────────────────────────────────


def get_entry(features: dict[str, Any], triple: Triple) -> dict[str, Any] | None:
    """Return the stored entry for a triple, or None."""
    scopes = features.get(triple.feature)
    if not isinstance(scopes, dict):
        return None
    scope_ids = scopes.get(triple.scope)
    if not isinstance(scope_ids, dict):
        return None
    entry = scope_ids.get(triple.scope_id)
    return entry if isinstance(entry, dict) else None


def set_entry(features: dict[str, Any], triple: Triple, entry: dict[str, Any]) -> None:
    """Write an entry for a triple, creating the nesting as needed."""
    scopes = features.setdefault(triple.feature, {})
    scope_ids = scopes.setdefault(triple.scope, {})
    scope_ids[triple.scope_id] = entry


def iter_entries(features: dict[str, Any]):
    """Yield ``(Triple, entry)`` for every entry, tolerating legacy shapes."""
    if not isinstance(features, dict):
        return
    for feature, scopes in features.items():
        if not isinstance(scopes, dict):
            continue
        for scope, scope_ids in scopes.items():
            if not isinstance(scope_ids, dict):
                continue
            for scope_id, entry in scope_ids.items():
                yield Triple(str(feature), str(scope), str(scope_id)), (
                    entry if isinstance(entry, dict) else {}
                )


def carry_forward(
    features: dict[str, Any], triple_map: dict[str, list[str]]
) -> dict[str, Any]:
    """Drop orphaned triples, keeping manual overrides.

    An entry survives when a leader still maps to its triple, or when it was
    written by a manual override (``triggering_leader == ''``).
    """
    result: dict[str, Any] = {}
    for triple, entry in iter_entries(features):
        is_manual = str(entry.get(ATTR_TRIGGERING_LEADER, "")) == ""
        if triple.key in triple_map or is_manual:
            set_entry(result, triple, dict(entry))
    return result


def build_feature_entry(
    previous_entry: dict[str, Any] | None,
    enabled: bool,
    mode: str,
    timestamp: float,
    triggering_leader: str,
) -> dict[str, Any]:
    """Build a features entry, applying the timestamp-bump rule.

    The timestamp bumps when there was no previous entry, when ``enabled``
    flips, or when the triggering leader is an ``event``/``button`` entity
    (every accepted press is a distinct "user did the thing", even when the
    resolved value is unchanged).
    """
    prev = previous_entry if isinstance(previous_entry, dict) else {}
    previous_enabled = prev.get(ATTR_ENABLED)
    previous_timestamp = prev.get(ATTR_LAST_CHANGED_TIMESTAMP, timestamp)
    is_button_leader = (
        triggering_leader.split(".")[0] in FIRE_ALWAYS_DOMAINS
        if triggering_leader
        else False
    )
    flipped = (
        previous_enabled is None or previous_enabled != enabled or is_button_leader
    )
    return {
        ATTR_ENABLED: bool(enabled),
        ATTR_MODE: mode,
        ATTR_LAST_CHANGED_TIMESTAMP: float(
            timestamp if flipped else previous_timestamp
        ),
        ATTR_TRIGGERING_LEADER: triggering_leader,
    }


def build_manual_entry(
    previous_entry: dict[str, Any] | None,
    enabled: bool,
    timestamp: float,
) -> dict[str, Any]:
    """Build a features entry for a manual override.

    ``mode`` is preserved from any existing entry, otherwise ``leader``.
    ``triggering_leader`` is always empty so the entry is exempt from the
    orphan-drop rule and the Leaders automation skips leader-label parsing.
    """
    prev = previous_entry if isinstance(previous_entry, dict) else {}
    return {
        ATTR_ENABLED: bool(enabled),
        ATTR_MODE: str(prev.get(ATTR_MODE, MODE_LEADER)),
        ATTR_LAST_CHANGED_TIMESTAMP: float(timestamp),
        ATTR_TRIGGERING_LEADER: "",
    }


def valid_feature_scope(scope: str) -> bool:
    """Return True when the scope is writable by a manual override."""
    return scope in (SCOPE_AREA, SCOPE_FLOOR, SCOPE_GLOBAL)

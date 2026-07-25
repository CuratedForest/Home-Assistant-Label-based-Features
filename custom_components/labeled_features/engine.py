"""Pure evaluation engine for Labeled Features.

Faithful port of the two legacy trigger-based template sensors:

- ``sensor.labeled_features_state`` — ``leaders`` / ``features`` /
  ``snapshots`` attribute templates.
- ``sensor.labeled_feature_areas_state`` — ``label_map`` attribute
  template.

Everything in this module is a pure function over plain dicts / lists /
strings so it can be unit-tested without Home Assistant. Registry and
state access is injected by the coordinator via plain values and small
callables.

Behavior spec: the Label Based Features documentation ("Theory",
"Features & Labels", "Area Based Features") plus the legacy Jinja
implementations. Label matching is case-sensitive throughout, per the
docs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import re
from typing import Any

from .const import (
    MOMENTARY_DOMAINS,
    SCOPE_AREA,
    SCOPE_FLOOR,
    SCOPE_GLOBAL,
    SCOPES,
    TRUTHY_STATES,
    UNREAL_STATES,
)

# A (feature, scope, scope_id) triple key. Kept as a tuple internally
# (the legacy templates used '||'-joined strings, which break on
# feature names containing '||').
TripleKey = tuple[str, str, str]

_LEADER_LABEL_RE = re.compile(r"^(Area |Floor |)Leader: (.+)$")
_PROVIDES_LABEL_RE = re.compile(r"^(Area |Floor |)Provides: (.+)$")
_PROVIDES_MODIFIER_RE = re.compile(
    r"^[^:]+ (Component|Min|Max|Step|Unit|Icon|Initial|Static|Mode"
    r"|Device Class): "
)
_INITIAL_PRESS_RE = re.compile(r"_initial_press$")

_SCOPE_PREFIXES = {SCOPE_AREA: "Area ", SCOPE_FLOOR: "Floor ", SCOPE_GLOBAL: ""}


def _label_value(label: str) -> str:
    """Value part of a ``<key>: <value>`` label.

    Mirrors the legacy ``regex_replace('^.+: ', '')`` (greedy) — the
    value is everything after the *last* ``': '`` occurrence.
    """
    return label.rsplit(": ", 1)[-1].strip()


def _first_match_value(labels: Iterable[str], pattern: str) -> str:
    """Value of the first label matching ``pattern`` ('' when none)."""
    compiled = re.compile(pattern)
    for label in labels:
        if compiled.match(label):
            return _label_value(label)
    return ""


def _to_float(value: Any) -> float | None:
    """``float(value)`` or None — the Jinja ``float(none)`` shape."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_skip_value(value: str) -> bool:
    """True when a leader value must not be recorded / evaluated.

    ``*_initial_press`` events and unknown/unavailable/none states are
    skipped: the previous value and timestamp are carried through.
    """
    if _INITIAL_PRESS_RE.search(value):
        return True
    return value.lower() in UNREAL_STATES


def eval_leader(
    labels: list[str],
    scope_pfx: str,
    fname: str,
    *,
    state: str,
    cv: str,
    prev_cv: str,
    domain: str,
) -> bool:
    """Per-leader truth value for one feature (post-Invert).

    Evaluation order (per the docs):

    1. Direction (``Increasing:``/``Decreasing:`` labels) — numeric
       compare of ``cv`` vs ``prev_cv``; takes precedence over
       Enable/Disable. Non-numeric or first update → False. Both labels
       may be present (OR).
    2. ``Enable:`` / ``Disable:`` labels — compared against the live
       ``state``.
    3. Default truth — ``event``/``button`` domains are always True;
       otherwise ``state == fname`` (case-sensitive) OR state is a
       generic truthy value (case-insensitive).

    ``Invert: True`` flips the result *after* whichever rule applied.
    """
    inc = f"{scope_pfx}{fname} Increasing: True" in labels
    dec = f"{scope_pfx}{fname} Decreasing: True" in labels

    if inc or dec:
        cur_n = _to_float(cv)
        prev_n = _to_float(prev_cv)
        has_mov = cur_n is not None and prev_n is not None
        is_inc = has_mov and cur_n > prev_n
        is_dec = has_mov and cur_n < prev_n
        base = (inc and is_inc) or (dec and is_dec)
    else:
        en_val = _first_match_value(
            labels, f"^{re.escape(scope_pfx + fname)} Enable: .+"
        )
        dis_val = _first_match_value(
            labels, f"^{re.escape(scope_pfx + fname)} Disable: .+"
        )
        if en_val or dis_val:
            by_en = en_val != "" and state == en_val
            by_dis = dis_val != "" and state == dis_val
            if en_val and dis_val:
                base = by_en and not by_dis
            elif en_val:
                base = by_en
            else:
                base = not by_dis
        elif domain in MOMENTARY_DOMAINS:
            base = True
        else:
            base = state == fname or state.lower() in TRUTHY_STATES

    if f"{scope_pfx}{fname} Invert: True" in labels:
        return not base
    return base


def build_triples(
    labels_by_eid: Mapping[str, list[str]],
    entity_ctx: Mapping[str, Mapping[str, str]],
) -> tuple[dict[TripleKey, list[str]], list[dict[str, str]]]:
    """Map ``(feature, scope, scope_id)`` triples to their leaders.

    ``labels_by_eid`` — label names per feature_leader entity.
    ``entity_ctx`` — per entity: ``{'area_id': ..., 'floor_id': ...}``.

    Area/floor-scoped leader labels whose entity has no resolvable
    area/floor are skipped (the legacy template skipped them silently;
    an error record is emitted so the coordinator can route it through
    Error Mode).
    """
    triples: dict[TripleKey, list[str]] = {}
    errors: list[dict[str, str]] = []

    for eid, labels in labels_by_eid.items():
        ctx = entity_ctx.get(eid, {})
        area_id = str(ctx.get("area_id", "") or "")
        floor_id = str(ctx.get("floor_id", "") or "")
        for label in labels:
            match = _LEADER_LABEL_RE.match(label)
            if match is None:
                continue
            prefix = match.group(1)
            fname = match.group(2).strip()
            if not fname:
                continue
            if prefix == "Area ":
                scope, scope_id = SCOPE_AREA, area_id
            elif prefix == "Floor ":
                scope, scope_id = SCOPE_FLOOR, floor_id
            else:
                scope, scope_id = SCOPE_GLOBAL, ""
            if scope in (SCOPE_AREA, SCOPE_FLOOR) and scope_id == "":
                errors.append(
                    {
                        "key": "unresolved_scope",
                        "message": (
                            f"Leader {eid} declares '{label}' but has no "
                            f"resolvable {scope}; the label is ignored."
                        ),
                    }
                )
                continue
            key: TripleKey = (fname, scope, scope_id)
            leaders = triples.setdefault(key, [])
            if eid not in leaders:
                leaders.append(eid)

    return triples, errors


def resolve_modes(
    triple_keys: Iterable[TripleKey],
    sensor_labels: list[str],
) -> dict[TripleKey, str]:
    """Resolve per-triple Mode from labels on the state sensor entity.

    ``<Scoped F> Mode: Leader|Any|All`` — default ``leader``.
    """
    modes: dict[TripleKey, str] = {}
    for key in triple_keys:
        fname, scope, _scope_id = key
        scope_pfx = _SCOPE_PREFIXES.get(scope, "")
        pattern = re.compile(f"^{re.escape(scope_pfx + fname)} Mode: (Leader|Any|All)$")
        mode = "leader"
        for label in sensor_labels:
            if pattern.match(label):
                mode = _label_value(label).lower()
                break
        modes[key] = mode
    return modes


def _write_entry(
    features: dict[str, Any],
    fname: str,
    scope: str,
    scope_id: str,
    entry: dict[str, Any],
) -> None:
    features.setdefault(fname, {}).setdefault(scope, {})[scope_id] = entry


def _get_entry(
    features: Mapping[str, Any], fname: str, scope: str, scope_id: str
) -> dict[str, Any]:
    scopes_map = features.get(fname, {})
    if not isinstance(scopes_map, Mapping):
        return {}
    sids = scopes_map.get(scope, {})
    if not isinstance(sids, Mapping):
        return {}
    entry = sids.get(scope_id, {})
    return dict(entry) if isinstance(entry, Mapping) else {}


def update_features(
    prev_features: Mapping[str, Any],
    prev_leaders: Mapping[str, Any],
    triples: Mapping[TripleKey, list[str]],
    modes: Mapping[TripleKey, str],
    labels_by_eid: Mapping[str, list[str]],
    live_state: Callable[[str], str],
    *,
    changed_eid: str | None = None,
    cv_raw: str | None = None,
    changed_ts: float | None = None,
    manual: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the next ``features`` attribute value.

    Nested ``feature → scope → scope_id → {enabled, mode,
    last_changed_timestamp, triggering_leader}``.

    Semantics (all ported from the legacy template):

    - Prior triples carry through when still mapped to a leader OR when
      manual (``triggering_leader == ''``); other orphans drop.
    - Manual path writes the override entry, preserving an existing
      ``mode`` (default ``leader``).
    - State-changed path re-evaluates every triple the changed leader
      contributes to, per the triple's mode (leader/any/all).
    - ``last_changed_timestamp`` bumps when ``enabled`` flips, when the
      entry is new, or when the changed leader is an event/button
      domain entity (every accepted press is a distinct action).
    """
    prev = prev_features if isinstance(prev_features, Mapping) else {}
    result: dict[str, Any] = {}

    # ── Carry-through (mapped leaders or manual overrides) ──────────
    for fname, scopes_map in prev.items():
        if not isinstance(scopes_map, Mapping):
            continue
        for scope, sids in scopes_map.items():
            if not isinstance(sids, Mapping):
                continue
            for scope_id, entry in sids.items():
                entry_map = dict(entry) if isinstance(entry, Mapping) else {}
                has_leader = (fname, scope, scope_id) in triples
                is_manual = entry_map.get("triggering_leader", "") == ""
                if has_leader or is_manual:
                    _write_entry(result, fname, scope, scope_id, entry_map)

    # ── Manual override path ─────────────────────────────────────────
    if manual is not None:
        target = str(manual.get("target_feature", "")).strip()
        scope = str(manual.get("scope", "")).lower().strip()
        scope_id = str(manual.get("scope_id", ""))
        enabled = bool(manual.get("enabled", False))
        timestamp = float(manual.get("timestamp", 0.0))
        if target and scope in SCOPES:
            prev_entry = _get_entry(result, target, scope, scope_id)
            _write_entry(
                result,
                target,
                scope,
                scope_id,
                {
                    "enabled": enabled,
                    "mode": prev_entry.get("mode", "leader"),
                    "last_changed_timestamp": timestamp,
                    "triggering_leader": "",
                },
            )

    # ── State-changed path ───────────────────────────────────────────
    if changed_eid and cv_raw is not None and not is_skip_value(cv_raw):
        ts = changed_ts if changed_ts is not None else 0.0
        prev_leaders_map = prev_leaders if isinstance(prev_leaders, Mapping) else {}
        prev_l = prev_leaders_map.get(changed_eid, {})
        prev_l = dict(prev_l) if isinstance(prev_l, Mapping) else {}
        prev_cv = str(prev_l.get("current_value", ""))
        changed_domain = changed_eid.split(".")[0]
        is_momentary = changed_domain in MOMENTARY_DOMAINS

        for key, leaders_list in triples.items():
            if changed_eid not in leaders_list:
                continue
            fname, scope, scope_id = key
            scope_pfx = _SCOPE_PREFIXES.get(scope, "")
            mode = modes.get(key, "leader")

            this_truth = eval_leader(
                labels_by_eid.get(changed_eid, []),
                scope_pfx,
                fname,
                state=live_state(changed_eid),
                cv=cv_raw,
                prev_cv=prev_cv,
                domain=changed_domain,
            )

            if mode == "leader":
                new_enabled = this_truth
            else:
                values: list[bool] = []
                for other_eid in leaders_list:
                    if other_eid == changed_eid:
                        values.append(this_truth)
                        continue
                    other_state = live_state(other_eid)
                    other_prev_raw = prev_leaders_map.get(other_eid, {})
                    other_prev_map = (
                        dict(other_prev_raw)
                        if isinstance(other_prev_raw, Mapping)
                        else {}
                    )
                    other_prev = str(other_prev_map.get("previous_value", ""))
                    values.append(
                        eval_leader(
                            labels_by_eid.get(other_eid, []),
                            scope_pfx,
                            fname,
                            state=other_state,
                            cv=other_state,
                            prev_cv=other_prev,
                            domain=other_eid.split(".")[0],
                        )
                    )
                new_enabled = all(values) if mode == "all" else any(values)

            prev_entry = _get_entry(result, fname, scope, scope_id)
            prev_enabled = prev_entry.get("enabled")
            prev_ts = prev_entry.get("last_changed_timestamp", ts)
            flipped = (
                prev_enabled is None or prev_enabled != new_enabled or is_momentary
            )
            _write_entry(
                result,
                fname,
                scope,
                scope_id,
                {
                    "enabled": new_enabled,
                    "mode": mode,
                    "last_changed_timestamp": ts if flipped else prev_ts,
                    "triggering_leader": changed_eid,
                },
            )

    return result


def update_leaders(
    prev_leaders: Mapping[str, Any],
    all_leader_ids: list[str],
    *,
    changed_eid: str | None = None,
    cv_raw: str | None = None,
    changed_ts: float | None = None,
    seed_getter: Callable[[str], tuple[str, float]],
) -> dict[str, Any]:
    """Compute the next ``leaders`` attribute value.

    Keyed by entity_id → ``{current_value, previous_value,
    last_changed_timestamp}``.

    - Entries for entities no longer labeled ``feature_leader`` drop.
    - Newly-labeled leaders seed from live state with empty previous.
    - The changed leader applies the skip rule (``*_initial_press`` /
      unknown values keep the prior value + timestamp) and chains
      ``previous_value`` (sanitizing skip-values to '').
    """
    prev = prev_leaders if isinstance(prev_leaders, Mapping) else {}
    leader_ids = set(all_leader_ids)
    result: dict[str, Any] = {}

    for eid, ldat in prev.items():
        if eid in leader_ids and eid != changed_eid:
            result[eid] = dict(ldat) if isinstance(ldat, Mapping) else {}

    for eid in all_leader_ids:
        if eid not in result and eid != changed_eid:
            state, lct = seed_getter(eid)
            result[eid] = {
                "current_value": state,
                "previous_value": "",
                "last_changed_timestamp": lct,
            }

    if changed_eid and changed_eid in leader_ids and cv_raw is not None:
        ts = changed_ts if changed_ts is not None else 0.0
        skip = is_skip_value(cv_raw)
        prev_l_raw = prev.get(changed_eid, {})
        prev_l = dict(prev_l_raw) if isinstance(prev_l_raw, Mapping) else {}
        cv = prev_l.get("current_value", cv_raw) if skip else cv_raw
        cv_ts = prev_l.get("last_changed_timestamp", ts) if skip else ts
        old_cv = str(prev_l.get("current_value", ""))
        old_pv = str(prev_l.get("previous_value", ""))
        prev_cv_raw = old_cv if cv != old_cv else old_pv
        prev_cv = "" if is_skip_value(prev_cv_raw) else prev_cv_raw
        result[changed_eid] = {
            "current_value": cv,
            "previous_value": prev_cv,
            "last_changed_timestamp": cv_ts,
        }

    return result


def update_snapshots(
    prev_snapshots: Mapping[str, Any],
    snapshot_name: str | None = None,
    payload: Any = None,
) -> dict[str, Any]:
    """Compute the next ``snapshots`` attribute value.

    Keyed by snapshot_name → arbitrary mapping payload. A mapping
    payload with content sets the entry; an empty / non-mapping payload
    removes it. Non-snapshot ticks (no ``snapshot_name``) carry the
    existing dict through unchanged.
    """
    prev = prev_snapshots if isinstance(prev_snapshots, Mapping) else {}
    name = (snapshot_name or "").strip()
    if not name:
        return dict(prev)

    result = {key: value for key, value in prev.items() if key != name}
    if isinstance(payload, Mapping) and len(payload) > 0:
        result[name] = dict(payload)
    return result


def build_label_map(
    gated_areas: list[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Compute the ``label_map`` attribute for the areas sensor.

    ``gated_areas`` — one entry per area carrying the ``feature_leader``
    label: ``{'area_id': ..., 'floor_id': ..., 'labels': [...]}``.

    Output: flat ``<scope_id>||<label>`` → ``{scope_id, label, scope,
    component, declaring_area_id, label_data}`` map, where
    ``label_data`` nests ``{scope, scope_id, component,
    declaring_area_id}``.

    Rules ported from the legacy template:

    - Only ``(Area |Floor |)Provides: <Label>`` labels register.
    - Modifier labels (``Provides <F> Component:``, ``… Min:``, etc.)
      never register as features in their own right.
    - Component defaults to ``select``; a sibling
      ``<scope-prefix>Provides <Label> Component: <comp>`` label on the
      same area overrides it.
    - Scope: ``Area`` → ``area`` (scope_id = declaring area), ``Floor``
      → ``floor`` (scope_id = declaring area's floor; deduped so
      multiple areas on one floor produce a single entry), bare →
      ``none`` (scope_id = declaring area, global entity pool).
    - The first declaration per ``(scope_id, label)`` wins.
    """
    errors: list[dict[str, str]] = []
    # Intermediate: scope_id → label name → entry (first wins).
    scopes: dict[str, dict[str, dict[str, str]]] = {}

    for area in gated_areas:
        aid = str(area.get("area_id", "") or "")
        floor_id = str(area.get("floor_id", "") or "")
        labels_raw = area.get("labels", [])
        area_labels = [str(lbl) for lbl in labels_raw if lbl]
        for label in area_labels:
            match = _PROVIDES_LABEL_RE.match(label)
            if match is None:
                continue
            prefix = match.group(1)
            lname = match.group(2).strip()
            if not lname or _PROVIDES_MODIFIER_RE.search(lname):
                continue
            if prefix == "Area ":
                scope = "area"
                scope_id = aid
            elif prefix == "Floor ":
                scope = "floor"
                scope_id = floor_id
            else:
                scope = "none"
                scope_id = aid
            if scope_id == "":
                errors.append(
                    {
                        "key": "unresolved_scope",
                        "message": (
                            f"Area {aid or '(unknown)'} declares '{label}' "
                            f"but has no resolvable {scope}; the label is "
                            "ignored."
                        ),
                    }
                )
                continue
            scope_pfx = _SCOPE_PREFIXES.get(
                SCOPE_AREA
                if scope == "area"
                else (SCOPE_FLOOR if scope == "floor" else SCOPE_GLOBAL),
                "",
            )
            comp_pattern = re.compile(
                f"^{re.escape(scope_pfx + 'Provides ' + lname)}"
                r" Component: .+$"
            )
            comp_override = ""
            for sibling in area_labels:
                if comp_pattern.match(sibling):
                    comp_override = _label_value(sibling)
                    break
            component = comp_override if comp_override else "select"

            entry = {
                "scope": scope,
                "scope_id": scope_id,
                "component": component,
                "declaring_area_id": aid,
            }
            bucket = scopes.setdefault(scope_id, {})
            if lname not in bucket:
                bucket[lname] = entry

    label_map: dict[str, Any] = {}
    for scope_id, labels in scopes.items():
        for lname, ldat in labels.items():
            label_map[f"{scope_id}||{lname}"] = {
                "scope_id": scope_id,
                "label": lname,
                "scope": ldat["scope"],
                "component": ldat["component"],
                "declaring_area_id": ldat["declaring_area_id"],
                "label_data": ldat,
            }
    return label_map, errors

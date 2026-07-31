"""Label map construction for the Labeled Feature Areas State sensor.

The sensor is deliberately a *trigger surface and nothing more*: it emits the
flat ``(scope_id, label)`` registry the Areas automation diffs, plus the single
``component`` hint. It knows nothing about feature names, object ids, option
pools, or any other per-feature knob — those all resolve at dispatch time in
``script.labeled_feature_area``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from .const import (
    DEFAULT_AREA_COMPONENT,
    LABEL_MAP_KEY_SEPARATOR,
    PROVIDES_MODIFIER_KEYWORDS,
    PROVIDES_SCOPES,
    SCOPE_AREA,
    SCOPE_FLOOR,
    SCOPE_NONE,
    SUBCONF_COMPONENT,
    SUBCONF_FEATURE,
    SUBCONF_SCOPE,
)
from .labels import (
    Registries,
    area_floor_id,
    area_label_names,
    label_areas,
    parse_provides_label,
)

_MODIFIER_RE = re.compile(r"^[^:]+ (" + "|".join(PROVIDES_MODIFIER_KEYWORDS) + r"): ")

# Scope value -> raw `(Area |Floor |)` prefix used by Provides labels.
_SCOPE_TO_RAW_PREFIX = {SCOPE_AREA: "Area", SCOPE_FLOOR: "Floor", SCOPE_NONE: ""}


def is_modifier_label_value(feature: str) -> bool:
    """Return True when a parsed ``Provides:`` value is really a modifier label.

    ``Area Provides Audio Mode Component: number`` also matches the
    ``Provides: <Feature>`` shape (with feature == ``Audio Mode Component:
    number``), so modifier labels must be rejected explicitly.
    """
    return _MODIFIER_RE.match(feature) is not None


def _component_for(
    area_labels: list[str], scope_label_prefix: str, feature: str
) -> str:
    """Resolve the component hint for a feature declared on an area."""
    prefix = f"{scope_label_prefix}Provides {feature} Component: "
    for label in area_labels:
        if label.startswith(prefix):
            value = label[len(prefix) :].strip()
            if value:
                return value
    return DEFAULT_AREA_COMPONENT


def provides_label_covers(area_labels: list[str], feature: str, prefix: str) -> bool:
    """Return True when the area's labels already declare ``(feature, prefix)``.

    Used to keep provides subentries a fill-in only: when a real
    ``(Area |Floor |)Provides: <F>`` label covers the same declaration, the
    label wins and the subentry is ignored.
    """
    for label in area_labels:
        parsed = parse_provides_label(label)
        if parsed is None:
            continue
        label_prefix, label_feature = parsed
        if is_modifier_label_value(label_feature):
            continue
        if (label_prefix, label_feature) == (prefix, feature):
            return True
    return False


def subentry_provides_labels(data: Mapping[str, Any]) -> list[str] | None:
    """Convert a provides subentry into synthetic area labels.

    Returns the declaration plus an optional ``Component:`` companion label,
    or None when the feature or scope is unusable. A floor scope on an area
    with no floor is dropped later at map-build time, exactly like a real
    ``Floor Provides:`` label on such an area.
    """
    feature = str(data.get(SUBCONF_FEATURE, "")).strip()
    scope = str(data.get(SUBCONF_SCOPE, SCOPE_AREA))
    if not feature or scope not in PROVIDES_SCOPES:
        return None
    prefix = _SCOPE_TO_RAW_PREFIX[scope]
    scope_label_prefix = f"{prefix} " if prefix else ""
    labels = [f"{scope_label_prefix}Provides: {feature}"]
    component = str(data.get(SUBCONF_COMPONENT, "") or "").strip()
    if component and component != DEFAULT_AREA_COMPONENT:
        labels.append(f"{scope_label_prefix}Provides {feature} Component: {component}")
    return labels


def build_label_map(
    regs: Registries,
    leader_label: str,
    extra_area_labels: Mapping[str, list[str]] | None = None,
    extra_gated_area_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Build the ``label_map`` attribute.

    Keys are ``<scope_id>||<label>``; values carry the five fields the Areas
    automation and ``script.labeled_feature_area`` consume, plus the nested
    ``label_data`` copy that the automation forwards verbatim.

    Scope semantics (see the Area Based Features docs):

    * ``Area Provides: <F>``  -> scope ``area``,  scope_id = declaring area
    * ``Floor Provides: <F>`` -> scope ``floor``, scope_id = the area's floor
    * ``Provides: <F>``       -> scope ``none``,  scope_id = declaring area

    Floor-scoped declarations on several areas of one floor deduplicate by
    ``(scope_id, label)``; the first declaration wins.

    ``extra_area_labels`` carries synthetic declarations from provides
    subentries, keyed by declaring area id. They are parsed by the same code
    path as real labels, but only fill in what the area's real labels do not
    already declare — labels win on conflict. ``extra_gated_area_ids`` joins
    the label-gated area set so subentry-only areas are scanned at all.
    """
    result: dict[str, Any] = {}
    extra_area_labels = extra_area_labels or {}

    gated_area_ids = list(label_areas(regs, leader_label))
    for area_id in extra_gated_area_ids:
        if area_id not in gated_area_ids:
            gated_area_ids.append(area_id)

    for area_id in gated_area_ids:
        floor_id = area_floor_id(regs, area_id)
        real_labels = area_label_names(regs, area_id)
        area_labels = list(real_labels)

        extras = extra_area_labels.get(area_id, ())
        for label in extras:
            parsed = parse_provides_label(label)
            if parsed is None:
                # Companion modifier labels are pulled in with their
                # declaration below.
                continue
            prefix, feature = parsed
            if is_modifier_label_value(feature):
                continue
            if provides_label_covers(real_labels, feature, prefix):
                continue
            scope_label_prefix = f"{prefix} " if prefix else ""
            companion_prefix = f"{scope_label_prefix}Provides {feature} "
            area_labels.append(label)
            area_labels.extend(
                mod for mod in extras if mod.startswith(companion_prefix)
            )

        for label in area_labels:
            parsed = parse_provides_label(label)
            if parsed is None:
                continue
            prefix, feature = parsed
            if is_modifier_label_value(feature):
                continue

            if prefix == "Area":
                scope = SCOPE_AREA
                scope_id = area_id
                scope_label_prefix = "Area "
            elif prefix == "Floor":
                scope = SCOPE_FLOOR
                scope_id = floor_id
                scope_label_prefix = "Floor "
            else:
                scope = SCOPE_NONE
                scope_id = area_id
                scope_label_prefix = ""

            if not scope_id:
                # Floor scope on an area with no floor cannot resolve.
                continue

            key = f"{scope_id}{LABEL_MAP_KEY_SEPARATOR}{feature}"
            if key in result:
                # Floor dedup / duplicate declaration: first one wins.
                continue

            label_data = {
                "scope": scope,
                "scope_id": scope_id,
                "component": _component_for(area_labels, scope_label_prefix, feature),
                "declaring_area_id": area_id,
            }
            result[key] = {
                "scope_id": scope_id,
                "label": feature,
                "scope": label_data["scope"],
                "component": label_data["component"],
                "declaring_area_id": label_data["declaring_area_id"],
                "label_data": label_data,
            }

    return result

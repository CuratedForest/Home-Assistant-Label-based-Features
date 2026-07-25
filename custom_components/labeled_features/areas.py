"""Label map construction for the Labeled Feature Areas State sensor.

The sensor is deliberately a *trigger surface and nothing more*: it emits the
flat ``(scope_id, label)`` registry the Areas automation diffs, plus the single
``component`` hint. It knows nothing about feature names, object ids, option
pools, or any other per-feature knob — those all resolve at dispatch time in
``script.labeled_feature_area``.
"""

from __future__ import annotations

import re
from typing import Any

from .const import (
    DEFAULT_AREA_COMPONENT,
    LABEL_MAP_KEY_SEPARATOR,
    PROVIDES_MODIFIER_KEYWORDS,
    SCOPE_AREA,
    SCOPE_FLOOR,
    SCOPE_NONE,
)
from .labels import (
    Registries,
    area_floor_id,
    area_label_names,
    label_areas,
    parse_provides_label,
)

_MODIFIER_RE = re.compile(r"^[^:]+ (" + "|".join(PROVIDES_MODIFIER_KEYWORDS) + r"): ")


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


def build_label_map(regs: Registries, leader_label: str) -> dict[str, Any]:
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
    """
    result: dict[str, Any] = {}

    for area_id in label_areas(regs, leader_label):
        floor_id = area_floor_id(regs, area_id)
        area_labels = area_label_names(regs, area_id)

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

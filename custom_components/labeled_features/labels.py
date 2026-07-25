"""Label and registry helpers.

These deliberately mirror the semantics of the Home Assistant template
functions the legacy template sensors used, so the component resolves exactly
the same entity/area sets:

* ``labels(<entity_id>)``  -> the entity's *own* labels (device labels are not
  inherited, matching ``homeassistant.helpers.template.labels``).
* ``label_entities(<label>)`` -> entities labeled directly with that label.
* ``label_areas(<label>)`` -> areas labeled with that label.
* ``area_id(<entity_id>)`` -> the entity's area, falling back to its device's
  area.
* floor resolution -> the floor of the entity's area.

All label matching in the Labeled Features system is case-sensitive; only the
label *lookup* accepts either a label name or a label id, as the template
functions do.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)

from .const import SCOPE_LABEL_PREFIX, SCOPE_PREFIXES


@dataclass(frozen=True, slots=True)
class Registries:
    """Bundle of the registries the label helpers need."""

    areas: ar.AreaRegistry
    devices: dr.DeviceRegistry
    entities: er.EntityRegistry
    floors: fr.FloorRegistry
    labels: lr.LabelRegistry

    @classmethod
    def async_get(cls, hass: HomeAssistant) -> Registries:
        """Build the bundle from hass."""
        return cls(
            areas=ar.async_get(hass),
            devices=dr.async_get(hass),
            entities=er.async_get(hass),
            floors=fr.async_get(hass),
            labels=lr.async_get(hass),
        )


def resolve_label_id(regs: Registries, label_id_or_name: str) -> str | None:
    """Resolve a label id or label name to a label id.

    Mirrors ``template._label_id_or_name``: an existing id wins, otherwise the
    value is treated as a name.
    """
    if not label_id_or_name:
        return None
    if regs.labels.async_get_label(label_id_or_name) is not None:
        return label_id_or_name
    if label := regs.labels.async_get_label_by_name(label_id_or_name):
        return label.label_id
    return None


def label_names(regs: Registries, label_ids: set[str] | list[str]) -> list[str]:
    """Map label ids to label names, dropping unknown ids.

    Mirrors ``labels(x) | map('label_name') | reject('none') | list``.
    """
    names: list[str] = []
    for label_id in label_ids:
        if (entry := regs.labels.async_get_label(label_id)) is not None:
            names.append(entry.name)
    return names


def entity_label_names(regs: Registries, entity_id: str) -> list[str]:
    """Return the label names carried by an entity registry entry."""
    if (entry := regs.entities.async_get(entity_id)) is None:
        return []
    return label_names(regs, entry.labels)


def area_label_names(regs: Registries, area_id: str) -> list[str]:
    """Return the label names carried by an area."""
    if (area := regs.areas.async_get_area(area_id)) is None:
        return []
    return label_names(regs, area.labels)


def label_entities(regs: Registries, label_id_or_name: str) -> list[str]:
    """Return entity ids labeled with the given label."""
    if (label_id := resolve_label_id(regs, label_id_or_name)) is None:
        return []
    return [
        entry.entity_id for entry in er.async_entries_for_label(regs.entities, label_id)
    ]


def label_areas(regs: Registries, label_id_or_name: str) -> list[str]:
    """Return area ids labeled with the given label."""
    if (label_id := resolve_label_id(regs, label_id_or_name)) is None:
        return []
    return [entry.id for entry in ar.async_entries_for_label(regs.areas, label_id)]


def entity_area_id(regs: Registries, entity_id: str) -> str:
    """Return the area id for an entity, falling back to its device's area."""
    if (entry := regs.entities.async_get(entity_id)) is None:
        return ""
    if entry.area_id:
        return entry.area_id
    if entry.device_id and (device := regs.devices.async_get(entry.device_id)):
        return device.area_id or ""
    return ""


def area_floor_id(regs: Registries, area_id: str) -> str:
    """Return the floor id of an area, or an empty string."""
    if not area_id:
        return ""
    if (area := regs.areas.async_get_area(area_id)) is None:
        return ""
    return area.floor_id or ""


def entity_floor_id(regs: Registries, entity_id: str) -> str:
    """Return the floor id of the entity's area, or an empty string."""
    return area_floor_id(regs, entity_area_id(regs, entity_id))


# ── Label parsing ────────────────────────────────────────────────────────────

_GROUPING_RE = re.compile(r"^(Area |Floor |)(Leader|Follower): (.+)$")
_PROVIDES_RE = re.compile(r"^(Area |Floor |)Provides: (.+)$")


def parse_grouping_label(label: str, role: str) -> tuple[str, str] | None:
    """Parse ``(Area |Floor |)<role>: <Feature>``.

    Returns ``(scope, feature_name)`` where scope is ``area``/``floor``/
    ``global``, or None when the label is not a grouping label for ``role``.
    """
    match = _GROUPING_RE.match(label)
    if match is None or match.group(2) != role:
        return None
    feature = match.group(3).strip()
    if not feature:
        return None
    return SCOPE_PREFIXES[match.group(1).strip()], feature


def parse_provides_label(label: str) -> tuple[str, str] | None:
    """Parse ``(Area |Floor |)Provides: <Feature>``.

    Returns ``(prefix, feature_name)`` with the raw prefix (``Area``/``Floor``/
    ``''``) so callers can apply their own scope mapping (the areas sensor maps
    the bare form to ``none``, not ``global``).
    """
    match = _PROVIDES_RE.match(label)
    if match is None:
        return None
    feature = match.group(2).strip()
    if not feature:
        return None
    return match.group(1).strip(), feature


def scoped_feature(scope: str, feature: str) -> str:
    """Return the scoped feature key used as the optional-label prefix."""
    return f"{SCOPE_LABEL_PREFIX.get(scope, '')}{feature}"


def label_value(labels: list[str], key: str) -> str | None:
    """Return the value of the first ``<key>: <value>`` label, else None.

    ``key`` is matched literally and case-sensitively, e.g.
    ``Area Night Enable``.
    """
    prefix = f"{key}: "
    for label in labels:
        if label.startswith(prefix):
            return label[len(prefix) :]
    return None


def has_label(labels: list[str], label: str) -> bool:
    """Return True when the exact label is present."""
    return label in labels

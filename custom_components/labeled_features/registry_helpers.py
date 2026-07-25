"""Thin wrappers around HA registry lookups used across the coordinators.

Ported from the template `labels(...)`, `label_areas(...)`,
`label_entities(...)`, `area_id(...)`, and `area_entities(...)` template
helpers so the coordinators don't depend on `homeassistant.helpers.template`
for anything at render time.

Semantics match HA's built-in template helpers exactly. In particular,
`entity_labels(hass, entity_id)` returns ONLY the labels applied to the
entity registry entry, not the union with the entity's device labels —
this matches `homeassistant.helpers.template.labels(<entity_id>)` at
`homeassistant/helpers/template.py:1670-1671`, and matches how the two
template sensors this component replaces read `labels(eid) | map('label_name')`.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    label_registry as lr,
)

__all__ = [
    "area_labels",
    "entity_area_id",
    "entity_labels",
    "floor_of_area",
    "label_areas",
    "label_entities",
    "label_id_for_name",
]


def label_id_for_name(hass: HomeAssistant, name: str) -> str | None:
    """Return the label_id whose display name matches `name`."""

    reg = lr.async_get(hass)
    entry = reg.async_get_label_by_name(name)
    return entry.label_id if entry is not None else None


def label_entities(hass: HomeAssistant, name: str) -> list[str]:
    """All entity_ids that carry the label with display name `name`."""

    lid = label_id_for_name(hass, name)
    if lid is None:
        return []
    reg = er.async_get(hass)
    return [entry.entity_id for entry in reg.entities.get_entries_for_label(lid)]


def label_areas(hass: HomeAssistant, name: str) -> list[str]:
    """All area_ids that carry the label with display name `name`."""

    lid = label_id_for_name(hass, name)
    if lid is None:
        return []
    reg = ar.async_get(hass)
    return [
        area.id
        for area in reg.async_list_areas()
        if lid in (area.labels or set())
    ]


def entity_labels(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Display names of the labels an entity carries.

    Returns entity-registry-only labels, matching HA's built-in
    `labels(<entity_id>)` template helper. Callers use the result for
    `in` / `startswith` checks; ordering is not stable and is not sorted.
    """

    reg = er.async_get(hass)
    ent = reg.async_get(entity_id)
    if ent is None:
        return []
    lbl_reg = lr.async_get(hass)
    return [
        entry.name
        for lid in (ent.labels or ())
        if (entry := lbl_reg.async_get_label(lid)) is not None
    ]


def area_labels(hass: HomeAssistant, area_id: str) -> list[str]:
    """Display names of the labels an area carries."""

    reg = ar.async_get(hass)
    area = reg.async_get_area(area_id)
    if area is None:
        return []
    lbl_reg = lr.async_get(hass)
    return [
        entry.name
        for lid in (area.labels or ())
        if (entry := lbl_reg.async_get_label(lid)) is not None
    ]


def entity_area_id(hass: HomeAssistant, entity_id: str) -> str:
    """The area_id assigned to an entity (or its device)."""

    reg = er.async_get(hass)
    ent = reg.async_get(entity_id)
    if ent is None:
        return ""
    if ent.area_id:
        return ent.area_id
    if ent.device_id:
        dev_reg = dr.async_get(hass)
        device = dev_reg.async_get(ent.device_id)
        if device is not None and device.area_id:
            return device.area_id
    return ""


def floor_of_area(hass: HomeAssistant, area_id: str) -> str:
    """Return the floor_id an area belongs to, or ''."""

    if not area_id:
        return ""
    reg = ar.async_get(hass)
    area = reg.async_get_area(area_id)
    if area is None or not area.floor_id:
        return ""
    return area.floor_id




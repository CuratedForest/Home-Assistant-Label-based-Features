"""Sync the sensor-wide default labels the component owns.

The config entry stores two sensor-wide defaults — `Error Mode` and
`Script Call Mode`. Downstream scripts still read them via
`labels('sensor.labeled_features_state')`, so the component maintains
exactly one label per managed key on the features-state sensor entity,
letting user-authored per-feature `<Scoped F> Mode: ...` labels coexist
untouched.

The current label IDs the entry manages are persisted into
`config_entry.data[DATA_MANAGED_LABEL_IDS]` so `async_unload_entry` can
un-apply them without touching user-authored labels.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from .const import (
    CONF_ERROR_MODE_DEFAULT,
    CONF_FEATURES_STATE_ENTITY_ID,
    CONF_SCRIPT_CALL_MODE_DEFAULT,
    DATA_MANAGED_LABEL_IDS,
    LABEL_KEY_ERROR_MODE,
    LABEL_KEY_SCRIPT_CALL_MODE,
)

_LOGGER = logging.getLogger(__name__)


def _label_name(key: str, value: str) -> str:
    return f"{key}: {value}"


def _ensure_label(
    label_reg: lr.LabelRegistry, name: str
) -> lr.LabelEntry:
    """Look up (or create) a label by display name."""

    existing = label_reg.async_get_label_by_name(name)
    if existing is not None:
        return existing
    return label_reg.async_create(name=name)


def _resolve_managed_pair(
    label_reg: lr.LabelRegistry,
    error_mode: str,
    script_call_mode: str,
) -> tuple[lr.LabelEntry, lr.LabelEntry]:
    error_label = _ensure_label(
        label_reg, _label_name(LABEL_KEY_ERROR_MODE, error_mode)
    )
    script_label = _ensure_label(
        label_reg, _label_name(LABEL_KEY_SCRIPT_CALL_MODE, script_call_mode)
    )
    return error_label, script_label


def _find_label_ids_for_key(
    label_reg: lr.LabelRegistry, key: str
) -> set[str]:
    """All label IDs whose display name starts with `<key>: `."""

    prefix = f"{key}: "
    return {
        lbl.label_id
        for lbl in label_reg.async_list_labels()
        if lbl.name.startswith(prefix)
    }


async def async_sync_labels(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply managed labels to the features-state sensor entity.

    Behaviour:
    - If the sensor entity is not yet in the entity registry we skip
      silently — the caller will re-run this after the sensor platform
      finishes setup.
    - We first strip any previously-managed labels that no longer match
      the current defaults.
    - Then we apply the two labels that reflect the current configured
      defaults.
    - The set of managed label IDs is written back to `entry.data`.
    """

    merged = {**entry.data, **entry.options}
    features_eid = merged.get(CONF_FEATURES_STATE_ENTITY_ID)
    if not features_eid:
        return

    ent_reg = er.async_get(hass)
    ent_entry = ent_reg.async_get(features_eid)
    if ent_entry is None:
        return

    label_reg = lr.async_get(hass)
    error_mode = merged.get(CONF_ERROR_MODE_DEFAULT)
    script_call_mode = merged.get(CONF_SCRIPT_CALL_MODE_DEFAULT)
    if not error_mode or not script_call_mode:
        return

    error_label, script_label = _resolve_managed_pair(
        label_reg, error_mode, script_call_mode
    )
    desired_ids = {error_label.label_id, script_label.label_id}

    # Union of every label ID whose name starts with one of our managed
    # keys. This is what we consider "managed by the integration" for the
    # purposes of removing stale entries; user-authored per-feature
    # labels use different prefixes (`<Feature> Mode: ...`) and are
    # skipped.
    strictly_managed_ids = _find_label_ids_for_key(
        label_reg, LABEL_KEY_ERROR_MODE
    ) | _find_label_ids_for_key(label_reg, LABEL_KEY_SCRIPT_CALL_MODE)

    current_ids = set(ent_entry.labels or set())
    stale_ids = (current_ids & strictly_managed_ids) - desired_ids

    new_ids = (current_ids - stale_ids) | desired_ids
    if new_ids != current_ids:
        ent_reg.async_update_entity(features_eid, labels=new_ids)

    # Persist the managed IDs on the entry so unload can undo them.
    existing_managed = set(entry.data.get(DATA_MANAGED_LABEL_IDS) or [])
    if existing_managed != desired_ids:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, DATA_MANAGED_LABEL_IDS: sorted(desired_ids)},
        )


async def async_unbind_managed_labels(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove managed labels from the sensor entity on unload/remove."""

    merged = {**entry.data, **entry.options}
    features_eid = merged.get(CONF_FEATURES_STATE_ENTITY_ID)
    if not features_eid:
        return

    ent_reg = er.async_get(hass)
    ent_entry = ent_reg.async_get(features_eid)
    if ent_entry is None:
        return

    managed_ids: Iterable[str] = entry.data.get(DATA_MANAGED_LABEL_IDS) or []
    if not managed_ids:
        return

    current_ids = set(ent_entry.labels or set())
    new_ids = current_ids - set(managed_ids)
    if new_ids != current_ids:
        ent_reg.async_update_entity(features_eid, labels=new_ids)

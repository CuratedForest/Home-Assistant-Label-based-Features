"""Constants for the Labeled Features integration.

Every string that appears in labels, events, or config flow keys lives here
so the Python code and the tests share one source of truth.

See `.kilo/plans/1785005878166-labeled-features-component-pt2.md` for the
design rationale and the wider Labeled Features documentation at
https://curatedforest.com/tech/home-assistant/label-based-features/ for the
system-level architecture.
"""

from __future__ import annotations

import re
from typing import Final

DOMAIN: Final = "labeled_features"

# ── Config entry keys ───────────────────────────────────────────────────
CONF_INSTANCE_NAME: Final = "instance_name"
CONF_LEADER_LABEL: Final = "leader_label"
CONF_FEATURES_STATE_ENTITY_ID: Final = "features_state_entity_id"
CONF_AREAS_STATE_ENTITY_ID: Final = "areas_state_entity_id"
CONF_ERROR_MODE_DEFAULT: Final = "error_mode_default"
CONF_SCRIPT_CALL_MODE_DEFAULT: Final = "script_call_mode_default"

# Managed-label registry: which label IDs the component owns on its sensor.
# Stored in the config entry's data so we can clean them up on unload.
DATA_MANAGED_LABEL_IDS: Final = "managed_label_ids"

# ── Defaults ────────────────────────────────────────────────────────────
DEFAULT_INSTANCE_NAME: Final = "Labeled Features"
DEFAULT_LEADER_LABEL: Final = "feature_leader"
DEFAULT_FEATURES_STATE_ENTITY_ID: Final = "sensor.labeled_features_state"
DEFAULT_AREAS_STATE_ENTITY_ID: Final = "sensor.labeled_feature_areas_state"
DEFAULT_ERROR_MODE: Final = "log"
DEFAULT_SCRIPT_CALL_MODE: Final = "Blocking"

ERROR_MODES: Final = ("silent", "log", "alert", "stop")
SCRIPT_CALL_MODES: Final = ("Blocking", "NonBlocking")

# ── Event names ─────────────────────────────────────────────────────────
EVENT_LABELED_FEATURE_SET: Final = "labeled_feature_set"
EVENT_LABELED_FEATURE_SNAPSHOT_SET: Final = "labeled_feature_snapshot_set"
EVENT_LABEL_REGISTRY_UPDATED: Final = "label_registry_updated"
EVENT_AREA_REGISTRY_UPDATED: Final = "area_registry_updated"
EVENT_FLOOR_REGISTRY_UPDATED: Final = "floor_registry_updated"
EVENT_STATE_CHANGED: Final = "state_changed"

# ── Service names ───────────────────────────────────────────────────────
SERVICE_REPORT_ERROR: Final = "report_error"

# ── Domain runtime storage keys ─────────────────────────────────────────
# hass.data[DOMAIN] shape:
#   {
#     "entries": {entry_id: {"features": FeaturesCoordinator,
#                            "areas": AreasCoordinator,
#                            "unsub": [callable, ...]}},
#     "service_registered": bool,
#   }
DATA_ENTRIES: Final = "entries"
DATA_SERVICE_REGISTERED: Final = "service_registered"

# ── Label keys the component manages on the features-state sensor ───────
LABEL_KEY_ERROR_MODE: Final = "Error Mode"
LABEL_KEY_SCRIPT_CALL_MODE: Final = "Script Call Mode"

# ── Feature-meta catalog ────────────────────────────────────────────────
# Source of truth for the generic-feature catalog. Ported byte-for-byte
# from the template sensor in configuration.yaml.
FEATURE_META: Final[dict[str, dict[str, str]]] = {
    "Media Toggle": {
        "domain": "media_player",
        "kind": "media_toggle",
        "domain_label": "Media Player",
    },
    "Media Play": {
        "domain": "media_player",
        "kind": "media_play",
        "domain_label": "Media Player",
    },
    "Media Pause": {
        "domain": "media_player",
        "kind": "media_pause",
        "domain_label": "Media Player",
    },
    "Media Next": {
        "domain": "media_player",
        "kind": "media_next",
        "domain_label": "Media Player",
    },
    "Media Previous": {
        "domain": "media_player",
        "kind": "media_previous",
        "domain_label": "Media Player",
    },
    "Media Seek Back": {
        "domain": "media_player",
        "kind": "media_seek_back",
        "domain_label": "Media Player",
    },
    "Media Seek Forward": {
        "domain": "media_player",
        "kind": "media_seek_forward",
        "domain_label": "Media Player",
    },
    "Volume Up": {
        "domain": "media_player",
        "kind": "volume_up",
        "domain_label": "Media Player",
    },
    "Volume Down": {
        "domain": "media_player",
        "kind": "volume_down",
        "domain_label": "Media Player",
    },
    "Lights On": {"domain": "light", "kind": "light_on", "domain_label": "Light"},
    "Lights Off": {"domain": "light", "kind": "light_off", "domain_label": "Light"},
    "Lights Up": {"domain": "light", "kind": "light_up", "domain_label": "Light"},
    "Lights Down": {"domain": "light", "kind": "light_down", "domain_label": "Light"},
    "Fan On": {"domain": "fan", "kind": "fan_on", "domain_label": "Fan"},
    "Fan Off": {"domain": "fan", "kind": "fan_off", "domain_label": "Fan"},
    "Fan Up": {"domain": "fan", "kind": "fan_up", "domain_label": "Fan"},
    "Fan Down": {"domain": "fan", "kind": "fan_down", "domain_label": "Fan"},
}

# ── Truth function helpers ──────────────────────────────────────────────
TRUTHY_STATES: Final = frozenset(
    {"on", "true", "home", "open", "detected", "active", "unlocked"}
)
SKIP_STATES: Final = frozenset({"unknown", "unavailable", "none"})
BUTTON_DOMAINS: Final = frozenset({"event", "button"})

# ── Scope prefixes ──────────────────────────────────────────────────────
# Single source of truth for the `(Area |Floor |)` prefix alphabet.
# `prefix` is the label-text prefix (with trailing space, empty for the
# global / area-declared-bare case). Leader-side and provides-side use
# the same prefix alphabet but assign different scope values to the
# bare / no-prefix case:
#   Leaders  — bare prefix means `global`.
#   Provides — bare prefix means `none`.
SCOPE_PREFIXES: Final = (
    ("Area ", "area", "area"),
    ("Floor ", "floor", "floor"),
    ("", "global", "none"),
)


def prefix_for_leader_scope(scope: str) -> str:
    """Return the label prefix (`Area ` / `Floor ` / ``) for a leader scope."""

    for prefix, leader_scope, _ in SCOPE_PREFIXES:
        if leader_scope == scope:
            return prefix
    return ""


def prefix_for_provides_scope(scope: str) -> str:
    """Return the label prefix (`Area ` / `Floor ` / ``) for a provides scope."""

    for prefix, _, provides_scope in SCOPE_PREFIXES:
        if provides_scope == scope:
            return prefix
    return ""


# The prefix alternation used inside `_LEADER_RE` and `_PROVIDES_RE`.
# `re.escape` handles the empty-string case cleanly.
SCOPE_PREFIX_RE_ALT: Final = "|".join(re.escape(p) for p, _, _ in SCOPE_PREFIXES)


# Modifier labels that Area Based Features should NOT treat as feature
# names when parsing `Provides:` labels on areas.
AREA_MODIFIER_KEYWORDS: Final = (
    "Component",
    "Min",
    "Max",
    "Step",
    "Unit",
    "Icon",
    "Initial",
    "Static",
    "Mode",
    "Device Class",
)

# ── Platforms ───────────────────────────────────────────────────────────
PLATFORMS: Final = ["sensor"]

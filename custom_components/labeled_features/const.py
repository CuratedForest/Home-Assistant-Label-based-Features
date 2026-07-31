"""Constants for the Labeled Features integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "labeled_features"

# ── Config entry keys ────────────────────────────────────────────────────────
CONF_NAME: Final = "name"
CONF_PREFIX: Final = "prefix"
CONF_LEADER_LABEL: Final = "leader_label"
CONF_DEFAULT_MODE: Final = "default_mode"
CONF_DEFAULT_SCRIPT_CALL_MODE: Final = "default_script_call_mode"
CONF_DEFAULT_ERROR_MODE: Final = "default_error_mode"
CONF_MODE_OVERRIDES: Final = "mode_overrides"
CONF_SCRIPT_CALL_MODE_OVERRIDES: Final = "script_call_mode_overrides"
CONF_ALERT_ACTION: Final = "alert_action"
CONF_ALERT_SEVERITY: Final = "alert_severity"

DEFAULT_NAME: Final = "Labeled Features"
DEFAULT_PREFIX: Final = "labeled_feature"
# The documented label name (see the Features & Labels docs). Label lookups
# accept either a label name or a label id, so an existing `feature_leader`
# label id keeps resolving.
DEFAULT_LEADER_LABEL: Final = "Feature Leader"

# ── Resolution modes ─────────────────────────────────────────────────────────
MODE_LEADER: Final = "leader"
MODE_ANY: Final = "any"
MODE_ALL: Final = "all"
MODES: Final = (MODE_LEADER, MODE_ANY, MODE_ALL)
DEFAULT_MODE: Final = MODE_LEADER

# Label-facing (case-sensitive) spellings of the modes.
MODE_LABEL_VALUES: Final = ("Leader", "Any", "All")

# ── Script call modes ────────────────────────────────────────────────────────
SCRIPT_CALL_MODE_BLOCKING: Final = "Blocking"
SCRIPT_CALL_MODE_NONBLOCKING: Final = "NonBlocking"
SCRIPT_CALL_MODES: Final = (SCRIPT_CALL_MODE_BLOCKING, SCRIPT_CALL_MODE_NONBLOCKING)
DEFAULT_SCRIPT_CALL_MODE: Final = SCRIPT_CALL_MODE_BLOCKING

# ── Error modes ──────────────────────────────────────────────────────────────
ERROR_MODE_SILENT: Final = "silent"
ERROR_MODE_LOG: Final = "log"
ERROR_MODE_ALERT: Final = "alert"
ERROR_MODE_STOP: Final = "stop"
ERROR_MODES: Final = (
    ERROR_MODE_SILENT,
    ERROR_MODE_LOG,
    ERROR_MODE_ALERT,
    ERROR_MODE_STOP,
)
DEFAULT_ERROR_MODE: Final = ERROR_MODE_LOG
DEFAULT_ERROR_SOURCE: Final = "Labeled Feature"
DEFAULT_ERROR_SEVERITY: Final = "medium"
ERROR_SEVERITIES: Final = ("low", "medium", "high")

ALERT_SCRIPT_ENTITY_ID: Final = "script.send_alert"
DEFAULT_ALERT_ACTION: Final = ALERT_SCRIPT_ENTITY_ID
DEFAULT_ALERT_SEVERITY: Final = DEFAULT_ERROR_SEVERITY

# ── Scopes ───────────────────────────────────────────────────────────────────
SCOPE_AREA: Final = "area"
SCOPE_FLOOR: Final = "floor"
SCOPE_GLOBAL: Final = "global"
# The areas sensor uses `none` where the features sensor uses `global` for the
# bare (unprefixed) label form. Both are part of the downstream contract.
SCOPE_NONE: Final = "none"
FEATURE_SCOPES: Final = (SCOPE_AREA, SCOPE_FLOOR, SCOPE_GLOBAL)

# Label scope prefix -> scope value, for `(Area |Floor |)Leader: <F>` labels.
SCOPE_PREFIXES: Final = {"Area": SCOPE_AREA, "Floor": SCOPE_FLOOR, "": SCOPE_GLOBAL}
# Reverse map: scope value -> label prefix (with trailing space) used when
# building scoped optional-label keys such as `Area Night Invert: True`.
SCOPE_LABEL_PREFIX: Final = {
    SCOPE_AREA: "Area ",
    SCOPE_FLOOR: "Floor ",
    SCOPE_GLOBAL: "",
    SCOPE_NONE: "",
}

# ── Config subentries ────────────────────────────────────────────────────────
# UI-driven alternative to authoring labels. Labels win on conflict: a
# subentry only fills in what no label declares for the same thing.
SUBENTRY_TYPE_LEADER: Final = "leader"
SUBENTRY_TYPE_PROVIDES: Final = "provides"
SUBENTRY_TYPE_MODE: Final = "mode"

SUBCONF_AREA_ID: Final = "area_id"
SUBCONF_FEATURE: Final = "feature"
SUBCONF_SCOPE: Final = "scope"
SUBCONF_ENABLE_VALUE: Final = "enable_value"
SUBCONF_DISABLE_VALUE: Final = "disable_value"
SUBCONF_DIRECTION: Final = "direction"
SUBCONF_INVERT: Final = "invert"
SUBCONF_MODE: Final = "mode"
SUBCONF_COMPONENT: Final = "component"

# Subentry scope vocabularies: leader uses the features sensor's `global`,
# provides uses the areas sensor's `none` for the bare (unprefixed) form.
LEADER_SCOPES: Final = (SCOPE_AREA, SCOPE_FLOOR, SCOPE_GLOBAL)
PROVIDES_SCOPES: Final = (SCOPE_AREA, SCOPE_FLOOR, SCOPE_NONE)

DIRECTION_NONE: Final = "none"
DIRECTION_INCREASING: Final = "increasing"
DIRECTION_DECREASING: Final = "decreasing"
DIRECTION_BOTH: Final = "both"
DIRECTIONS: Final = (
    DIRECTION_NONE,
    DIRECTION_INCREASING,
    DIRECTION_DECREASING,
    DIRECTION_BOTH,
)

# Components a provides subentry can hint, mirroring the MQTT-discovery set
# `script.labeled_feature_entities` supports.
PROVIDES_COMPONENTS: Final = (
    "select",
    "number",
    "sensor",
    "switch",
    "text",
    "binary_sensor",
)

# ── Truth function ──────────────────────────────────────────────────────────
# Generic truthy states for boolean-ish leaders. Compared case-insensitively.
TRUTHY_STATES: Final = frozenset(
    {"on", "true", "home", "open", "detected", "active", "unlocked"}
)
# States that never represent a real value.
UNREAL_STATES: Final = frozenset({"unknown", "unavailable", "none"})
# Event names that are not "the user did the thing" and are skipped.
SKIP_EVENT_SUFFIX: Final = "_initial_press"
# Domains whose entities carry no persistent boolean state; every change fires.
FIRE_ALWAYS_DOMAINS: Final = frozenset({"event", "button"})

# ── Events ───────────────────────────────────────────────────────────────────
EVENT_SET_FEATURE: Final = "labeled_feature_set"
EVENT_SET_SNAPSHOT: Final = "labeled_feature_snapshot_set"

# ── Services ─────────────────────────────────────────────────────────────────
SERVICE_SET_FEATURE: Final = "set_feature"
SERVICE_SET_SNAPSHOT: Final = "set_snapshot"
SERVICE_ERROR_MODE: Final = "error_mode"

# ── Attribute names (downstream contract) ────────────────────────────────────
ATTR_FEATURE_META: Final = "feature_meta"
ATTR_LEADERS: Final = "leaders"
ATTR_FEATURES: Final = "features"
ATTR_SNAPSHOTS: Final = "snapshots"
ATTR_LABEL_MAP: Final = "label_map"
ATTR_CONFIG: Final = "config"

ATTR_ENABLED: Final = "enabled"
ATTR_MODE: Final = "mode"
ATTR_LAST_CHANGED_TIMESTAMP: Final = "last_changed_timestamp"
ATTR_TRIGGERING_LEADER: Final = "triggering_leader"
ATTR_CURRENT_VALUE: Final = "current_value"
ATTR_PREVIOUS_VALUE: Final = "previous_value"

# ── Area based features ──────────────────────────────────────────────────────
DEFAULT_AREA_COMPONENT: Final = "select"
LABEL_MAP_KEY_SEPARATOR: Final = "||"
# `Provides <Feature> <Keyword>: <value>` modifier labels must not register as
# features in their own right.
PROVIDES_MODIFIER_KEYWORDS: Final = (
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

# ── Feature catalog ─────────────────────────────────────────────────────────
# Single source of truth for the generic-feature catalog, byte-compatible with
# the `feature_meta` attribute of the legacy template sensor.
#   domain       - HA domain used as the fallback target pool ('' = none)
#   kind         - internal action key consumed by labeled_feature_generics
#   domain_label - provider grouping for the `Provides: <DomainLabel>` shorthand
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

# ── Misc ─────────────────────────────────────────────────────────────────────
# Debounce window for registry-driven recomputes, in seconds.
REGISTRY_DEBOUNCE_SECONDS: Final = 1.0

"""Constants for the Labeled Features integration.

Part 1 scope: the two state sensors (Labeled Features State, Labeled
Feature Areas State) plus internal error handling. All configuration is
label-driven; config-entry subentry inputs are deferred to a later part.

Behavior spec: the Label Based Features documentation plus the legacy
trigger-based template sensors this component replaces.
"""

from __future__ import annotations

DOMAIN = "labeled_features"

PLATFORMS: list[str] = ["sensor"]

# Sensor entity ids (fixed — downstream automations/scripts reference
# these exact ids; see automation.labeled_feature_leaders and the
# labeled_feature_* scripts).
FEATURES_SENSOR_STEM = "labeled_features_state"
AREAS_SENSOR_STEM = "labeled_feature_areas_state"

FEATURES_SENSOR_ENTITY_ID = f"sensor.{FEATURES_SENSOR_STEM}"
AREAS_SENSOR_ENTITY_ID = f"sensor.{AREAS_SENSOR_STEM}"

# Labels
LABEL_FEATURE_LEADER = "feature_leader"

# Events (fired by script.labeled_feature_generics)
EVENT_LABELED_FEATURE_SET = "labeled_feature_set"
EVENT_LABELED_FEATURE_SNAPSHOT_SET = "labeled_feature_snapshot_set"

# Error modes
ERROR_SILENT = "silent"
ERROR_LOG = "log"
ERROR_ALERT = "alert"
ERROR_STOP = "stop"
ERROR_MODES = (ERROR_SILENT, ERROR_LOG, ERROR_ALERT, ERROR_STOP)

# Config entry options
CONF_ENABLED = "enabled"

# Guardrails against unbounded attribute growth from event payloads
# (labeled_feature_set / labeled_feature_snapshot_set can be fired by
# any automation; entries persist via restore and have no expiry).
MAX_SNAPSHOTS = 50
MAX_SNAPSHOT_PAYLOAD_CHARS = 16384
MAX_MANUAL_FEATURES = 100
MAX_EVENT_FIELD_LENGTH = 255

# Feature scopes (second-level key of the `features` attribute)
SCOPE_AREA = "area"
SCOPE_FLOOR = "floor"
SCOPE_GLOBAL = "global"
SCOPES = (SCOPE_AREA, SCOPE_FLOOR, SCOPE_GLOBAL)

# States considered "not real" — used both to gate boot-restore noise
# and to skip leader value updates.
UNREAL_STATES = frozenset({"unknown", "unavailable", "none"})

# Default truth function: generic truthy values (compared lowercased).
TRUTHY_STATES = frozenset(
    {"on", "true", "home", "open", "detected", "active", "unlocked"}
)

# Domains whose leaders always evaluate to enabled=True (no persistent
# boolean state — every change is a "fire") and whose accepted ticks
# always bump last_changed_timestamp.
MOMENTARY_DOMAINS = frozenset({"event", "button"})

# ── feature_meta ─────────────────────────────────────────────────────
# Single source of truth for the generic-feature catalog. Consumed via
# `state_attr('sensor.labeled_features_state', 'feature_meta')` by
# script.labeled_feature_generics and automation.labeled_feature_leaders.
# Each entry carries:
#   - domain: HA domain used as fallback target pool ('' = no fallback)
#   - kind: internal action key used by labeled_feature_generics
#   - domain_label: human-readable provider grouping for the
#     `Provides: <DomainLabel>` entity-context shorthand
# Must stay byte-identical to the legacy template sensor's catalog.
FEATURE_META: dict[str, dict[str, str]] = {
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
    "Lights On": {
        "domain": "light",
        "kind": "light_on",
        "domain_label": "Light",
    },
    "Lights Off": {
        "domain": "light",
        "kind": "light_off",
        "domain_label": "Light",
    },
    "Lights Up": {
        "domain": "light",
        "kind": "light_up",
        "domain_label": "Light",
    },
    "Lights Down": {
        "domain": "light",
        "kind": "light_down",
        "domain_label": "Light",
    },
    "Fan On": {
        "domain": "fan",
        "kind": "fan_on",
        "domain_label": "Fan",
    },
    "Fan Off": {
        "domain": "fan",
        "kind": "fan_off",
        "domain_label": "Fan",
    },
    "Fan Up": {
        "domain": "fan",
        "kind": "fan_up",
        "domain_label": "Fan",
    },
    "Fan Down": {
        "domain": "fan",
        "kind": "fan_down",
        "domain_label": "Fan",
    },
}

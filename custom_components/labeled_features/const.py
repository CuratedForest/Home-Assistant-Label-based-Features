"""Constants for the Labeled Features integration.

Minimal config — all configuration is label-driven.
"""

from __future__ import annotations

DOMAIN = "labeled_features"

PLATFORMS: list[str] = ["sensor"]

# Sensor entity IDs (fixed, no suffix)
FEATURES_SENSOR_STEM = "labeled_features_state"
AREAS_SENSOR_STEM = "labeled_feature_areas_state"

# Labels
LABEL_FEATURE_LEADER = "feature_leader"

# Events
EVENT_LABELED_FEATURE_SET = "labeled_feature_set"
EVENT_LABELED_FEATURE_SNAPSHOT_SET = "labeled_feature_snapshot_set"

# Error modes
ERROR_SILENT = "silent"
ERROR_LOG = "log"
ERROR_ALERT = "alert"
ERROR_STOP = "stop"

# Config entry options
CONF_ENABLED = "enabled"

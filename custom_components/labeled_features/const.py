DOMAIN = "labeled_features"

CONF_INSTANCE_NAME = "instance_name"
CONF_LEADER_LABEL = "leader_label"
CONF_FEATURE_PREFIX = "feature_prefix"

DEFAULT_LEADER_LABEL = "feature_leader"
DEFAULT_FEATURE_PREFIX = ""

TRUTHY_STATES = frozenset({"on", "true", "home", "open", "detected", "active", "unlocked"})
FALSY_STATES = frozenset({"off", "false", "away", "closed", "clear", "inactive", "locked"})
SKIP_STATES = frozenset({"unknown", "unavailable", "none"})

EVENT_LABELED_FEATURE_SET = "labeled_feature_set"
EVENT_LABELED_FEATURE_SNAPSHOT_SET = "labeled_feature_snapshot_set"

FEATURE_META = {
    "Media Toggle":       {"domain": "media_player", "kind": "media_toggle",       "domain_label": "Media Player"},
    "Media Play":         {"domain": "media_player", "kind": "media_play",         "domain_label": "Media Player"},
    "Media Pause":        {"domain": "media_player", "kind": "media_pause",        "domain_label": "Media Player"},
    "Media Next":         {"domain": "media_player", "kind": "media_next",         "domain_label": "Media Player"},
    "Media Previous":     {"domain": "media_player", "kind": "media_previous",     "domain_label": "Media Player"},
    "Media Seek Back":    {"domain": "media_player", "kind": "media_seek_back",    "domain_label": "Media Player"},
    "Media Seek Forward": {"domain": "media_player", "kind": "media_seek_forward", "domain_label": "Media Player"},
    "Volume Up":          {"domain": "media_player", "kind": "volume_up",          "domain_label": "Media Player"},
    "Volume Down":        {"domain": "media_player", "kind": "volume_down",        "domain_label": "Media Player"},
    "Lights On":          {"domain": "light",        "kind": "light_on",           "domain_label": "Light"},
    "Lights Off":         {"domain": "light",        "kind": "light_off",          "domain_label": "Light"},
    "Lights Up":          {"domain": "light",        "kind": "light_up",           "domain_label": "Light"},
    "Lights Down":        {"domain": "light",        "kind": "light_down",         "domain_label": "Light"},
    "Fan On":             {"domain": "fan",          "kind": "fan_on",             "domain_label": "Fan"},
    "Fan Off":            {"domain": "fan",          "kind": "fan_off",            "domain_label": "Fan"},
    "Fan Up":             {"domain": "fan",          "kind": "fan_up",             "domain_label": "Fan"},
    "Fan Down":           {"domain": "fan",          "kind": "fan_down",           "domain_label": "Fan"},
}

MODIFIER_KEYWORDS = frozenset({
    "Component", "Min", "Max", "Step", "Unit", "Icon",
    "Initial", "Static", "Mode", "Device Class",
})

"""Tests for the config and options flow."""

from __future__ import annotations

from custom_components.labeled_features.const import (
    CONF_ALERT_ACTION,
    CONF_ALERT_SEVERITY,
    CONF_DEFAULT_ERROR_MODE,
    CONF_DEFAULT_MODE,
    CONF_DEFAULT_SCRIPT_CALL_MODE,
    CONF_LEADER_LABEL,
    CONF_MODE_OVERRIDES,
    CONF_NAME,
    CONF_PREFIX,
    CONF_SCRIPT_CALL_MODE_OVERRIDES,
    DEFAULT_LEADER_LABEL,
    DEFAULT_PREFIX,
    DOMAIN,
    SUBCONF_AREA_ID,
    SUBCONF_COMPONENT,
    SUBCONF_DIRECTION,
    SUBCONF_DISABLE_VALUE,
    SUBCONF_ENABLE_VALUE,
    SUBCONF_FEATURE,
    SUBCONF_INVERT,
    SUBCONF_MODE,
    SUBCONF_SCOPE,
)
from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.selector import SelectSelector, SelectSelectorMode

from .conftest import make_entry, setup_entry

BASE_INPUT = {
    CONF_NAME: "Labeled Features",
    CONF_PREFIX: DEFAULT_PREFIX,
    CONF_LEADER_LABEL: DEFAULT_LEADER_LABEL,
    CONF_DEFAULT_MODE: "leader",
    CONF_DEFAULT_SCRIPT_CALL_MODE: "Blocking",
    CONF_DEFAULT_ERROR_MODE: "log",
    CONF_ALERT_ACTION: "script.send_alert",
    CONF_ALERT_SEVERITY: "medium",
    CONF_MODE_OVERRIDES: "",
    CONF_SCRIPT_CALL_MODE_OVERRIDES: "",
}

OPTIONS_INPUT = {
    CONF_LEADER_LABEL: DEFAULT_LEADER_LABEL,
    CONF_DEFAULT_MODE: "leader",
    CONF_DEFAULT_SCRIPT_CALL_MODE: "Blocking",
    CONF_DEFAULT_ERROR_MODE: "log",
    CONF_ALERT_ACTION: "script.send_alert",
    CONF_ALERT_SEVERITY: "medium",
    CONF_MODE_OVERRIDES: "",
    CONF_SCRIPT_CALL_MODE_OVERRIDES: "",
}


async def start_flow(hass: HomeAssistant, user_input: dict | None = None):
    """Start the user flow and optionally submit input."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    if user_input is None:
        return result
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """The happy path stores the prefix in data and settings in options."""
    result = await start_flow(hass, BASE_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Labeled Features"
    assert result["data"] == {
        CONF_NAME: "Labeled Features",
        CONF_PREFIX: DEFAULT_PREFIX,
    }
    assert result["options"][CONF_LEADER_LABEL] == DEFAULT_LEADER_LABEL
    assert result["options"][CONF_DEFAULT_MODE] == "leader"


async def test_user_flow_shows_form(hass: HomeAssistant) -> None:
    """The first step is a form."""
    result = await start_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_invalid_prefix(hass: HomeAssistant) -> None:
    """A non-slug prefix is refused."""
    result = await start_flow(hass, {**BASE_INPUT, CONF_PREFIX: "Not A Slug"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PREFIX: "invalid_prefix"}


async def test_empty_prefix(hass: HomeAssistant) -> None:
    """An empty prefix is refused."""
    result = await start_flow(hass, {**BASE_INPUT, CONF_PREFIX: ""})
    assert result["errors"] == {CONF_PREFIX: "invalid_prefix"}


async def test_duplicate_prefix(hass: HomeAssistant, leader_label) -> None:
    """Two instances cannot share a prefix."""
    await setup_entry(hass)
    result = await start_flow(hass, BASE_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PREFIX: "prefix_in_use"}


async def test_blank_leader_label(hass: HomeAssistant) -> None:
    """A leader label is mandatory."""
    result = await start_flow(hass, {**BASE_INPUT, CONF_LEADER_LABEL: "   "})
    assert result["errors"] == {CONF_LEADER_LABEL: "leader_label_required"}


async def test_valid_overrides_accepted(hass: HomeAssistant) -> None:
    """Well-formed override lines pass validation."""
    result = await start_flow(
        hass,
        {
            **BASE_INPUT,
            CONF_MODE_OVERRIDES: "Area Night Mode: All\nOpen Door Mode: Any\n",
            CONF_SCRIPT_CALL_MODE_OVERRIDES: (
                "Area Sleep Timer Script Call Mode: NonBlocking"
            ),
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_invalid_mode_override(hass: HomeAssistant) -> None:
    """A bad mode value is rejected with a field error."""
    result = await start_flow(
        hass, {**BASE_INPUT, CONF_MODE_OVERRIDES: "Area Night Mode: Sometimes"}
    )
    assert result["errors"] == {CONF_MODE_OVERRIDES: "invalid_mode_override"}


async def test_invalid_mode_override_missing_keyword(hass: HomeAssistant) -> None:
    """A line without the keyword is rejected."""
    result = await start_flow(
        hass, {**BASE_INPUT, CONF_MODE_OVERRIDES: "Area Night: All"}
    )
    assert result["errors"] == {CONF_MODE_OVERRIDES: "invalid_mode_override"}


async def test_invalid_script_call_mode_override(hass: HomeAssistant) -> None:
    """A bad script call mode value is rejected."""
    result = await start_flow(
        hass,
        {
            **BASE_INPUT,
            CONF_SCRIPT_CALL_MODE_OVERRIDES: "Area Sleep Timer Script Call Mode: Fast",
        },
    )
    assert result["errors"] == {
        CONF_SCRIPT_CALL_MODE_OVERRIDES: "invalid_script_call_mode_override"
    }


async def test_options_flow_updates_options(hass: HomeAssistant, leader_label) -> None:
    """Options can be edited; the prefix is not part of the form."""
    entry = await setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert CONF_PREFIX not in result["data_schema"].schema

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **OPTIONS_INPUT,
            CONF_LEADER_LABEL: "other_leader",
            CONF_DEFAULT_MODE: "any",
            CONF_ALERT_ACTION: "notify.mobile_app_phone",
            CONF_ALERT_SEVERITY: "high",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LEADER_LABEL] == "other_leader"
    assert entry.options[CONF_DEFAULT_MODE] == "any"
    assert entry.options[CONF_ALERT_ACTION] == "notify.mobile_app_phone"
    assert entry.options[CONF_ALERT_SEVERITY] == "high"


async def test_options_flow_rejects_bad_override(
    hass: HomeAssistant, leader_label
) -> None:
    """Validation also runs in the options flow."""
    entry = await setup_entry(hass, make_entry(prefix="lf_test", name="Test"))

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**OPTIONS_INPUT, CONF_MODE_OVERRIDES: "nonsense"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_MODE_OVERRIDES: "invalid_mode_override"}


async def test_invalid_alert_action(hass: HomeAssistant) -> None:
    """The alert action must be a domain.service string."""
    result = await start_flow(hass, {**BASE_INPUT, CONF_ALERT_ACTION: "send_alert"})
    assert result["errors"] == {CONF_ALERT_ACTION: "alert_action_invalid"}


async def test_alert_action_is_stripped(hass: HomeAssistant) -> None:
    """Whitespace around the alert action is not stored."""
    result = await start_flow(
        hass, {**BASE_INPUT, CONF_ALERT_ACTION: "  script.send_alert  "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_ALERT_ACTION] == "script.send_alert"


async def test_selects_render_as_dropdowns(hass: HomeAssistant) -> None:
    """Every select in the settings form is an explicit dropdown, not a list."""
    result = await start_flow(hass)
    selects = [
        value
        for value in result["data_schema"].schema.values()
        if isinstance(value, SelectSelector)
    ]
    assert selects, "expected the settings form to contain select selectors"
    for select in selects:
        assert select.config.get("mode") == SelectSelectorMode.DROPDOWN


# ── subentry flows ───────────────────────────────────────────────────────────

LEADER_INPUT = {
    CONF_ENTITY_ID: "binary_sensor.front_door",
    SUBCONF_FEATURE: "Night",
    SUBCONF_SCOPE: "area",
    SUBCONF_ENABLE_VALUE: "on",
    SUBCONF_DISABLE_VALUE: "off",
    SUBCONF_DIRECTION: "none",
    SUBCONF_INVERT: False,
}

PROVIDES_INPUT = {
    SUBCONF_AREA_ID: "kitchen",
    SUBCONF_FEATURE: "Audio Mode",
    SUBCONF_SCOPE: "area",
    SUBCONF_COMPONENT: "select",
}

MODE_INPUT = {
    SUBCONF_FEATURE: "Night",
    SUBCONF_SCOPE: "global",
    SUBCONF_MODE: "any",
}


async def start_subentry_flow(hass: HomeAssistant, subentry_type: str, user_input):
    """Start a subentry flow and submit input."""
    entry = await setup_entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, subentry_type),
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )
    return entry, result


async def test_leader_subentry_flow_creates(hass: HomeAssistant, leader_label) -> None:
    """Adding a leader subentry stores its data with a stable unique id."""
    entry, result = await start_subentry_flow(hass, "leader", LEADER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = next(iter(entry.subentries.values()))
    assert sub.subentry_type == "leader"
    assert sub.title == "Night (binary_sensor.front_door)"
    assert sub.unique_id == "binary_sensor.front_door|Night|area"
    assert sub.data[SUBCONF_ENABLE_VALUE] == "on"


async def test_leader_subentry_duplicate_aborts(
    hass: HomeAssistant, leader_label
) -> None:
    """The same entity/feature/scope leader cannot be added twice."""
    entry = await setup_entry(hass)
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=LEADER_INPUT,
            subentry_type="leader",
            title="Night (binary_sensor.front_door)",
            unique_id="binary_sensor.front_door|Night|area",
        ),
    )
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "leader"), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], LEADER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_leader_subentry_requires_feature(
    hass: HomeAssistant, leader_label
) -> None:
    """A whitespace-only feature name is rejected with a field error."""
    _, result = await start_subentry_flow(
        hass, "leader", {**LEADER_INPUT, SUBCONF_FEATURE: "   "}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {SUBCONF_FEATURE: "feature_required"}


async def test_leader_subentry_reconfigure(hass: HomeAssistant, leader_label) -> None:
    """Editing a leader subentry updates it; unchanged values are not a dupe."""
    entry = await setup_entry(hass)
    subentry = ConfigSubentry(
        data=LEADER_INPUT,
        subentry_type="leader",
        title="Night (binary_sensor.front_door)",
        unique_id="binary_sensor.front_door|Night|area",
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    [sub] = [s for s in entry.subentries.values() if s.subentry_type == "leader"]

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "leader"),
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "subentry_id": sub.subentry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**LEADER_INPUT, SUBCONF_ENABLE_VALUE: "playing"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert sub.data[SUBCONF_ENABLE_VALUE] == "playing"


async def test_provides_subentry_flow_creates(
    hass: HomeAssistant, leader_label
) -> None:
    """Adding a provides subentry stores its data with a stable unique id."""
    entry, result = await start_subentry_flow(hass, "provides", PROVIDES_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = next(iter(entry.subentries.values()))
    assert sub.subentry_type == "provides"
    assert sub.unique_id == "kitchen|Audio Mode|area"


async def test_mode_subentry_flow_creates(hass: HomeAssistant, leader_label) -> None:
    """Adding a mode subentry stores its data with a stable unique id."""
    entry, result = await start_subentry_flow(hass, "mode", MODE_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    sub = next(iter(entry.subentries.values()))
    assert sub.subentry_type == "mode"
    assert sub.title == "Night (global: any)"
    assert sub.unique_id == "Night|global"


async def test_mode_subentry_duplicate_aborts(
    hass: HomeAssistant, leader_label
) -> None:
    """The same feature/scope mode cannot be added twice."""
    entry = await setup_entry(hass)
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=MODE_INPUT,
            subentry_type="mode",
            title="Night (global: any)",
            unique_id="Night|global",
        ),
    )
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "mode"), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], MODE_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"

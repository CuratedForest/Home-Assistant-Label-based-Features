"""Tests for the config and options flow."""

from __future__ import annotations

from custom_components.labeled_features.const import (
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
)
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import make_entry, setup_entry

BASE_INPUT = {
    CONF_NAME: "Labeled Features",
    CONF_PREFIX: DEFAULT_PREFIX,
    CONF_LEADER_LABEL: DEFAULT_LEADER_LABEL,
    CONF_DEFAULT_MODE: "leader",
    CONF_DEFAULT_SCRIPT_CALL_MODE: "Blocking",
    CONF_DEFAULT_ERROR_MODE: "log",
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
            CONF_LEADER_LABEL: "other_leader",
            CONF_DEFAULT_MODE: "any",
            CONF_DEFAULT_SCRIPT_CALL_MODE: "NonBlocking",
            CONF_DEFAULT_ERROR_MODE: "alert",
            CONF_MODE_OVERRIDES: "Area Night Mode: All",
            CONF_SCRIPT_CALL_MODE_OVERRIDES: "",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LEADER_LABEL] == "other_leader"
    assert entry.options[CONF_DEFAULT_MODE] == "any"


async def test_options_flow_rejects_bad_override(
    hass: HomeAssistant, leader_label
) -> None:
    """Validation also runs in the options flow."""
    entry = await setup_entry(hass, make_entry(prefix="lf_test", name="Test"))

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_LEADER_LABEL: DEFAULT_LEADER_LABEL,
            CONF_DEFAULT_MODE: "leader",
            CONF_DEFAULT_SCRIPT_CALL_MODE: "Blocking",
            CONF_DEFAULT_ERROR_MODE: "log",
            CONF_MODE_OVERRIDES: "nonsense",
            CONF_SCRIPT_CALL_MODE_OVERRIDES: "",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_MODE_OVERRIDES: "invalid_mode_override"}

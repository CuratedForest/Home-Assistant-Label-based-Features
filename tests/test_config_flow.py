"""Tests for the config flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.labeled_features.const import (
    CONF_AREAS_STATE_ENTITY_ID,
    CONF_ERROR_MODE_DEFAULT,
    CONF_FEATURES_STATE_ENTITY_ID,
    CONF_INSTANCE_NAME,
    CONF_LEADER_LABEL,
    CONF_SCRIPT_CALL_MODE_DEFAULT,
    DEFAULT_AREAS_STATE_ENTITY_ID,
    DEFAULT_FEATURES_STATE_ENTITY_ID,
    DEFAULT_LEADER_LABEL,
    DOMAIN,
)


def _valid_input(**overrides) -> dict:
    base = {
        CONF_INSTANCE_NAME: "Labeled Features",
        CONF_LEADER_LABEL: DEFAULT_LEADER_LABEL,
        CONF_FEATURES_STATE_ENTITY_ID: DEFAULT_FEATURES_STATE_ENTITY_ID,
        CONF_AREAS_STATE_ENTITY_ID: DEFAULT_AREAS_STATE_ENTITY_ID,
        CONF_ERROR_MODE_DEFAULT: "log",
        CONF_SCRIPT_CALL_MODE_DEFAULT: "Blocking",
    }
    base.update(overrides)
    return base


async def test_user_flow_happy_path(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _valid_input()
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Labeled Features"
    assert result["data"][CONF_LEADER_LABEL] == DEFAULT_LEADER_LABEL


async def test_second_instance_rejects_duplicate_leader_label(
    hass: HomeAssistant,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], _valid_input())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _valid_input(
            instance_name="Test",
            features_state_entity_id="sensor.labeled_features_state_test",
            areas_state_entity_id="sensor.labeled_feature_areas_state_test",
        ),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_LEADER_LABEL: "duplicate_leader_label"}


async def test_second_instance_rejects_duplicate_entity_id(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(result["flow_id"], _valid_input())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _valid_input(
            instance_name="Test",
            leader_label="feature_leader_test",
        ),
    )
    assert result["type"] == FlowResultType.FORM
    assert (
        result["errors"].get(CONF_FEATURES_STATE_ENTITY_ID)
        == "duplicate_entity_id"
    )


async def test_invalid_entity_id_rejected(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _valid_input(features_state_entity_id="not-a-valid-id"),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"][CONF_FEATURES_STATE_ENTITY_ID] == "invalid_entity_id"


async def test_features_and_areas_must_differ(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _valid_input(areas_state_entity_id=DEFAULT_FEATURES_STATE_ENTITY_ID),
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"][CONF_AREAS_STATE_ENTITY_ID] == "entity_id_conflict"

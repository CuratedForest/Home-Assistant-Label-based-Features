"""Tests for override parsing, the debounced registry path and diagnostics."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.labeled_features.const import (
    CONF_MODE_OVERRIDES,
    DEFAULT_LEADER_LABEL,
    DOMAIN,
    REGISTRY_DEBOUNCE_SECONDS,
)
from custom_components.labeled_features.coordinator import (
    parse_overrides,
    validate_overrides,
)
from custom_components.labeled_features.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .conftest import create_area, make_entry, register_entity, setup_entry

MODE_VALUES = {"Leader": "leader", "Any": "any", "All": "all"}
FEATURES_SENSOR = "sensor.labeled_features_state"
AREAS_SENSOR = "sensor.labeled_feature_areas_state"


# ── override parsing ─────────────────────────────────────────────────────────


def test_parse_overrides_handles_scopes_and_blank_lines() -> None:
    """Scoped, unscoped and instance-wide forms all parse."""
    raw = "\nArea Night Mode: All\nOpen Door Mode: Any\nMode: Leader\n\n"
    assert parse_overrides(raw, "Mode", MODE_VALUES) == {
        "Area Night": "all",
        "Open Door": "any",
        "": "leader",
    }


def test_parse_overrides_skips_invalid_lines() -> None:
    """Unparsable lines are dropped rather than raising."""
    assert parse_overrides("Area Night Mode: Sometimes", "Mode", MODE_VALUES) == {}
    assert parse_overrides(None, "Mode", MODE_VALUES) == {}


def test_validate_overrides_reports_bad_lines() -> None:
    """Validation surfaces exactly the offending lines."""
    raw = "Area Night Mode: All\ngarbage\nOpen Door Mode: nope"
    assert validate_overrides(raw, "Mode", MODE_VALUES) == [
        "garbage",
        "Open Door Mode: nope",
    ]
    assert validate_overrides("", "Mode", MODE_VALUES) == []


def test_parse_overrides_is_case_sensitive() -> None:
    """Label values keep the documented capitalization."""
    assert parse_overrides("Area Night Mode: all", "Mode", MODE_VALUES) == {}


# ── debounced registry reconcile ─────────────────────────────────────────────


async def test_registry_change_reconciles_after_debounce(
    hass: HomeAssistant, leader_label
) -> None:
    """A label edit reconciles without waiting for a leader state change."""
    await setup_entry(hass)
    assert hass.states.get(AREAS_SENSOR).attributes["label_map"] == {}

    area = create_area(
        hass, "Kitchen", labels=[DEFAULT_LEADER_LABEL, "Area Provides: Audio Mode"]
    )
    await hass.async_block_till_done()
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=REGISTRY_DEBOUNCE_SECONDS + 1)
    )
    await hass.async_block_till_done()

    assert (
        f"{area.id}||Audio Mode"
        in hass.states.get(AREAS_SENSOR).attributes["label_map"]
    )


async def test_new_leader_appears_in_leaders_after_debounce(
    hass: HomeAssistant, leader_label
) -> None:
    """Newly labeled leaders are seeded into `leaders`, not into `features`."""
    await setup_entry(hass)
    register_entity(
        hass,
        "binary_sensor.front_door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="on",
    )
    await hass.async_block_till_done()
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=REGISTRY_DEBOUNCE_SECONDS + 1)
    )
    await hass.async_block_till_done()

    state = hass.states.get(FEATURES_SENSOR)
    assert state.state == "1"
    assert state.attributes["leaders"]["binary_sensor.front_door"] == {
        "current_value": "on",
        "previous_value": "",
        "last_changed_timestamp": pytest.approx(
            state.attributes["leaders"]["binary_sensor.front_door"][
                "last_changed_timestamp"
            ]
        ),
    }
    assert state.attributes["features"] == {}


# ── config attribute ────────────────────────────────────────────────────────


async def test_config_attribute_exposes_resolved_settings(
    hass: HomeAssistant, leader_label
) -> None:
    """The diagnostic `config` attribute reflects the entry options."""
    await setup_entry(hass, make_entry(**{CONF_MODE_OVERRIDES: "Area Night Mode: All"}))
    config = hass.states.get(FEATURES_SENSOR).attributes["config"]
    assert config["leader_label"] == DEFAULT_LEADER_LABEL
    assert config["prefix"] == "labeled_feature"
    assert config["mode_overrides"] == {"Area Night": "all"}
    assert config["default_script_call_mode"] == "Blocking"


# ── diagnostics ─────────────────────────────────────────────────────────────


async def test_diagnostics(hass: HomeAssistant, leader_label) -> None:
    """Diagnostics dump the resolved config and every attribute."""
    register_entity(
        hass,
        "binary_sensor.front_door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"],
        state="off",
    )
    entry = await setup_entry(hass)

    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["leader_entity_ids"] == ["binary_sensor.front_door"]
    assert data["triple_map"] == {"Open Door||global||": ["binary_sensor.front_door"]}
    assert data["entities"]["features_state"] == FEATURES_SENSOR
    assert set(data["attributes"]) == {
        "leaders",
        "features",
        "snapshots",
        "label_map",
    }


# ── error_mode action ───────────────────────────────────────────────────────


async def test_error_mode_action_logs(
    hass: HomeAssistant, leader_label, caplog: pytest.LogCaptureFixture
) -> None:
    """The action mirrors script.labeled_feature_error_mode."""
    await setup_entry(hass)
    await hass.services.async_call(
        DOMAIN,
        "error_mode",
        {"error_mode": "log", "message": "boom", "source": "Test"},
        blocking=True,
    )
    assert "Test: boom" in caplog.text


async def test_error_mode_action_stop_raises(hass: HomeAssistant, leader_label) -> None:
    """The stop tier surfaces as a service validation error."""
    await setup_entry(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "error_mode",
            {"error_mode": "stop", "message": "boom"},
            blocking=True,
        )


async def test_set_snapshot_action(hass: HomeAssistant, leader_label) -> None:
    """The snapshot action writes through the same path as the event."""
    await setup_entry(hass)
    await hass.services.async_call(
        DOMAIN,
        "set_snapshot",
        {"snapshot_name": "sleep_timeout", "payload": {"a": 1}},
        blocking=True,
    )
    assert hass.states.get(FEATURES_SENSOR).attributes["snapshots"] == {
        "sleep_timeout": {"a": 1}
    }

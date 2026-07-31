"""Tests for the tiered error handling."""

from __future__ import annotations

import logging

import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.labeled_features.errors import (
    LabeledFeatureStop,
    async_handle_error,
    normalize_error_mode,
    resolve_error_mode,
)
from homeassistant.core import HomeAssistant


async def test_silent_tier_is_a_noop(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Silent logs nothing."""
    with caplog.at_level(logging.DEBUG):
        await async_handle_error(hass, "silent", "boom")
    assert "boom" not in caplog.text


async def test_log_tier_warns(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Log warns with `source: message`."""
    await async_handle_error(hass, "log", "boom", source="Labeled Features Generics")
    assert "Labeled Features Generics: boom" in caplog.text
    assert caplog.records[-1].levelno == logging.WARNING


async def test_alert_tier_calls_send_alert(hass: HomeAssistant) -> None:
    """Alert dispatches script.send_alert when it exists."""
    hass.states.async_set("script.send_alert", "off")
    calls = async_mock_service(hass, "script", "send_alert")

    await async_handle_error(hass, "alert", "boom", source="Src", severity="high")
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data == {
        "alert_severity": "high",
        "alert_title": "Src",
        "alert_message": "boom",
    }


async def test_alert_tier_falls_back_to_logging(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Without script.send_alert the alert tier degrades to a warning."""
    await async_handle_error(hass, "alert", "boom", source="Src")
    assert "Src: boom" in caplog.text
    assert "script.send_alert does not exist" in caplog.text


async def test_alert_tier_uses_configured_action(hass: HomeAssistant) -> None:
    """The alert tier can call an action other than script.send_alert."""
    calls = async_mock_service(hass, "notify", "mobile_app_phone")

    await async_handle_error(
        hass,
        "alert",
        "boom",
        source="Src",
        severity="low",
        alert_action="notify.mobile_app_phone",
    )
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data == {
        "alert_severity": "low",
        "alert_title": "Src",
        "alert_message": "boom",
    }


async def test_alert_tier_malformed_action_falls_back(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A malformed alert action degrades to a warning, never a raise."""
    await async_handle_error(hass, "alert", "boom", source="Src", alert_action="bogus")
    assert "Src: boom" in caplog.text
    assert "not a valid action" in caplog.text


async def test_alert_tier_unregistered_action_falls_back(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """An unregistered alert action degrades to a warning."""
    await async_handle_error(
        hass, "alert", "boom", source="Src", alert_action="notify.nothing_here"
    )
    assert "Src: boom" in caplog.text
    assert "notify.nothing_here does not exist" in caplog.text


async def test_stop_tier_raises_and_logs(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Stop logs at error and raises so callers can halt."""
    with pytest.raises(LabeledFeatureStop):
        await async_handle_error(hass, "stop", "boom", source="Src")
    assert "Src: boom" in caplog.text
    assert caplog.records[-1].levelno == logging.ERROR


async def test_unknown_tier_falls_back_to_log(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """An unrecognized tier behaves as `log`."""
    await async_handle_error(hass, "nonsense", "boom")
    assert "Labeled Feature: boom" in caplog.text


def test_normalize_error_mode() -> None:
    """Normalization is case-insensitive with a default fallback."""
    assert normalize_error_mode("ALERT") == "alert"
    assert normalize_error_mode(None) == "log"
    assert normalize_error_mode("bogus", "silent") == "silent"


def test_resolve_error_mode_precedence() -> None:
    """Scoped label beats bare label beats the entry default."""
    labels = ["Error Mode: alert", "Area Night Error Mode: stop"]
    assert resolve_error_mode(labels, "silent", "Area Night") == "stop"
    assert resolve_error_mode(labels, "silent") == "alert"
    assert resolve_error_mode([], "silent") == "silent"
    assert resolve_error_mode([], None) == "log"


def test_resolve_error_mode_ignores_invalid_label_values() -> None:
    """A bogus label value falls through to the next source."""
    assert resolve_error_mode(["Error Mode: shout"], "alert") == "alert"

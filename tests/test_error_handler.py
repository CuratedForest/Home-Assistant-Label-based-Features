"""Tests for the shared error handler."""

from __future__ import annotations

import logging

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.labeled_features.const import DOMAIN, SERVICE_REPORT_ERROR
from custom_components.labeled_features.error_handler import (
    async_register_service,
    async_unregister_service_if_last,
    report_error,
)


async def test_silent_tier_is_noop(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    await report_error(hass, error_mode="silent", message="oops")
    assert "oops" not in caplog.text


async def test_log_tier_writes_warning(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    await report_error(
        hass, error_mode="log", message="a problem", source="Widget"
    )
    assert "Widget: a problem" in caplog.text


async def test_unknown_tier_falls_back_to_log(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    await report_error(hass, error_mode="banana", message="huh")
    assert "huh" in caplog.text


async def test_stop_tier_raises(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR)
    with pytest.raises(HomeAssistantError):
        await report_error(hass, error_mode="stop", message="halt")
    assert "halt" in caplog.text


async def test_alert_tier_calls_send_alert(hass: HomeAssistant) -> None:
    calls: list[dict] = []

    async def _capture(service_call) -> None:
        calls.append(dict(service_call.data))

    hass.services.async_register("script", "send_alert", _capture)
    await report_error(
        hass,
        error_mode="alert",
        message="wake up",
        source="Test",
        severity="high",
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0]["alert_title"] == "Test"
    assert calls[0]["alert_severity"] == "high"
    assert calls[0]["alert_message"] == "wake up"


async def test_alert_tier_falls_back_to_persistent_notification(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    # script.send_alert is not registered; expect fallback.
    calls: list[dict] = []

    async def _capture(service_call) -> None:
        calls.append(dict(service_call.data))

    hass.services.async_register("persistent_notification", "create", _capture)
    caplog.set_level(logging.WARNING)
    await report_error(
        hass, error_mode="alert", message="notify me", source="Test"
    )
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0]["title"] == "Test"
    assert calls[0]["message"] == "notify me"


async def test_service_registration_is_idempotent(hass: HomeAssistant) -> None:
    async_register_service(hass)
    async_register_service(hass)
    assert hass.services.has_service(DOMAIN, SERVICE_REPORT_ERROR)
    # Removing when last entry unloads.
    async_unregister_service_if_last(hass, active_entries=0)
    assert not hass.services.has_service(DOMAIN, SERVICE_REPORT_ERROR)


async def test_service_call_end_to_end(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    async_register_service(hass)
    caplog.set_level(logging.WARNING)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_REPORT_ERROR,
        {"message": "via-service", "source": "Test"},
        blocking=True,
    )
    assert "Test: via-service" in caplog.text

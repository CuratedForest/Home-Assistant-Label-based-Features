"""Error handling framework for Labeled Features.

Provides the silent/log/alert/stop error tiers. The `stop` tier raises
`ErrorStop` which callers catch to halt their action loop.

A service `labeled_features.handle_error` is exposed for backward
compatibility with the legacy `script.labeled_feature_error_mode`.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall

from .const import ERROR_ALERT, ERROR_LOG, ERROR_SILENT, ERROR_STOP

_LOGGER = logging.getLogger(__name__)


class ErrorStop(Exception):
    """Raised by the 'stop' error mode to halt execution."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def handle_error(
    error_mode: str,
    message: str,
    source: str = "Labeled Features",
    severity: str = "medium",
) -> None:
    """Route an error through the appropriate tier.

    Args:
        error_mode: One of silent, log, alert, stop.
        message: Human-readable error message.
        source: Short label for the error source.
        severity: Severity level for alert tier (low, medium, high).

    Raises:
        ErrorStop: When error_mode is 'stop'.
    """
    if error_mode == ERROR_SILENT:
        return

    formatted = f"[{source}] {message}"

    if error_mode == ERROR_LOG:
        _LOGGER.error(formatted)

    elif error_mode == ERROR_ALERT:
        _LOGGER.warning("Alert not implemented: %s", formatted)

    elif error_mode == ERROR_STOP:
        _LOGGER.error(formatted)
        raise ErrorStop(formatted)


async def async_handle_error_service(
    hass: HomeAssistant,
    service_call: ServiceCall,
) -> None:
    """Service handler for labeled_features.handle_error.

    Exposes error handling to scripts and automations for backward
    compatibility with the existing script.labeled_feature_error_mode.
    """
    error_mode = service_call.data.get("error_mode", ERROR_LOG)
    message = service_call.data.get("message", "")
    source = service_call.data.get("source", "Labeled Features")
    severity = service_call.data.get("severity", "medium")

    await handle_error(error_mode, message, source, severity)

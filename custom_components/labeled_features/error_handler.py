"""Error handling framework for Labeled Features.

Implements the documented Error Mode tiers inside the component:

- ``silent`` — no-op.
- ``log``    — write to the HA log at warning level
  (``"{source}: {message}"``, matching ``script.labeled_feature_error_mode``).
- ``alert``  — call ``script.send_alert`` when that script exists,
  falling back to a log entry when it does not.
- ``stop``   — log at error level and (optionally) raise
  :class:`ErrorStop` so the caller can halt its current unit of work.

This does NOT replace ``script.labeled_feature_error_mode`` — existing
scripts keep using that. A ``labeled_features.handle_error`` service is
registered for parity so future parts (and curious users) can route
through the component instead.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, ServiceCall, callback

from .const import ERROR_ALERT, ERROR_LOG, ERROR_SILENT, ERROR_STOP

_LOGGER = logging.getLogger(__name__)

ALERT_SCRIPT_DOMAIN = "script"
ALERT_SCRIPT_SERVICE = "send_alert"


class ErrorStop(Exception):
    """Raised by the 'stop' error mode to halt the caller's work."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@callback
def report_error(
    hass: HomeAssistant,
    error_mode: str,
    message: str,
    source: str = "Labeled Features",
    severity: str = "medium",
    *,
    raise_on_stop: bool = True,
) -> None:
    """Route an error through the appropriate tier (sync, loop-safe).

    Args:
        hass: Home Assistant instance (used for the alert tier).
        error_mode: One of silent, log, alert, stop (unknown → log).
        message: Human-readable error message.
        source: Short label prefixed onto logs/alerts.
        severity: Severity for the alert tier (low | medium | high).
        raise_on_stop: When False, the stop tier only logs — used by
            callers with no meaningful parent to halt (e.g. sensor
            recomputes, where aborting would corrupt state).

    Raises:
        ErrorStop: When ``error_mode`` is ``stop`` and ``raise_on_stop``.
    """
    mode = (error_mode or ERROR_LOG).lower()
    formatted = f"{source}: {message}"

    if mode == ERROR_SILENT:
        return

    if mode == ERROR_ALERT:
        if hass.services.has_service(ALERT_SCRIPT_DOMAIN, ALERT_SCRIPT_SERVICE):
            hass.async_create_task(
                hass.services.async_call(
                    ALERT_SCRIPT_DOMAIN,
                    ALERT_SCRIPT_SERVICE,
                    {
                        "alert_severity": severity,
                        "alert_title": source,
                        "alert_message": message,
                    },
                )
            )
        else:
            _LOGGER.warning(
                "%s (alert tier requested but script.%s is not available)",
                formatted,
                ALERT_SCRIPT_SERVICE,
            )
        return

    if mode == ERROR_STOP:
        _LOGGER.error(formatted)
        if raise_on_stop:
            raise ErrorStop(formatted)
        return

    # log tier (and unknown modes)
    _LOGGER.warning(formatted)


async def async_handle_error_service(call: ServiceCall) -> None:
    """Service handler for ``labeled_features.handle_error``.

    Parity helper mirroring ``script.labeled_feature_error_mode``. The
    stop tier only logs here — a service call cannot halt its caller.
    """
    report_error(
        call.hass,
        call.data.get("error_mode", ERROR_LOG),
        call.data.get("message", ""),
        source=call.data.get("source", "Labeled Features"),
        severity=call.data.get("severity", "medium"),
        raise_on_stop=False,
    )

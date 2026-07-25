"""Component-internal error handler mirroring script.labeled_feature_error_mode.

Four tiers: silent / log / alert / stop. Exposed both as a Python helper
callable from anywhere inside the component and as a public HA service
`labeled_features.report_error` so scripts (or downstream integrations)
can dispatch through the same code path if they want to.

Existing YAML scripts continue to call `script.labeled_feature_error_mode`
unchanged; this module does not delete or replace that script.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, ERROR_MODES, SERVICE_REPORT_ERROR

_LOGGER = logging.getLogger(__name__)

REPORT_ERROR_SCHEMA = vol.Schema(
    {
        vol.Optional("error_mode", default="log"): vol.In(ERROR_MODES),
        vol.Required("message"): cv.string,
        vol.Optional("source", default="Labeled Feature"): cv.string,
        vol.Optional("severity", default="medium"): cv.string,
    }
)


async def report_error(
    hass: HomeAssistant,
    *,
    error_mode: str = "log",
    message: str,
    source: str = "Labeled Feature",
    severity: str = "medium",
) -> None:
    """Report an error through the requested tier.

    ``stop`` raises `HomeAssistantError` after logging so callers that
    need to abort a task get the same halt semantics that
    `script.labeled_feature_error_mode` provides via ``stop: error: true``
    (the caller is still responsible for propagating; nothing outside
    this coroutine is halted).
    """

    mode = (error_mode or "log").strip().lower()
    if mode not in ERROR_MODES:
        # Match the script's default when handed an unknown tier.
        _LOGGER.warning(
            "%s: unknown error_mode '%s', falling back to 'log'", source, mode
        )
        mode = "log"

    if mode == "silent":
        return

    if mode == "log":
        _LOGGER.warning("%s: %s", source, message)
        return

    if mode == "alert":
        payload: dict[str, Any] = {
            "alert_severity": severity,
            "alert_title": source,
            "alert_message": message,
        }
        try:
            await hass.services.async_call(
                "script",
                "send_alert",
                payload,
                blocking=False,
            )
        except ServiceNotFound:
            # Fall back to a persistent notification so the alert is at
            # least visible in the UI.
            try:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": source,
                        "message": message,
                        "notification_id": f"{DOMAIN}_alert",
                    },
                    blocking=False,
                )
            except Exception:  # noqa: BLE001 - defensive last-ditch fallback
                _LOGGER.warning(
                    "%s: %s (alert fallback: persistent_notification unavailable)",
                    source,
                    message,
                )
                return
            _LOGGER.warning("%s: %s (script.send_alert unavailable)", source, message)
        return

    # mode == "stop"
    _LOGGER.error("%s: %s", source, message)
    raise HomeAssistantError(f"{source}: {message}")


def async_register_service(hass: HomeAssistant) -> None:
    """Register `labeled_features.report_error` if not already present.

    Safe to call multiple times — subsequent calls are no-ops.
    """

    if hass.services.has_service(DOMAIN, SERVICE_REPORT_ERROR):
        return

    async def _handle(call: ServiceCall) -> None:
        # Bounce any exception from `stop` back so HA logs the service
        # error correctly; callers awaiting `blocking=True` will see it.
        await report_error(
            hass,
            error_mode=call.data.get("error_mode", "log"),
            message=call.data["message"],
            source=call.data.get("source", "Labeled Feature"),
            severity=call.data.get("severity", "medium"),
        )

    hass.services.async_register(
        DOMAIN, SERVICE_REPORT_ERROR, _handle, schema=REPORT_ERROR_SCHEMA
    )


def async_unregister_service_if_last(hass: HomeAssistant, active_entries: int) -> None:
    """Remove the service when the final config entry is unloaded."""

    if active_entries > 0:
        return
    if hass.services.has_service(DOMAIN, SERVICE_REPORT_ERROR):
        hass.services.async_remove(DOMAIN, SERVICE_REPORT_ERROR)

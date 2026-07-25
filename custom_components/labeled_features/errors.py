"""Tiered error handling for the Labeled Features integration.

Mirrors ``script.labeled_feature_error_mode``:

===========  ==========================================================
Tier         Behavior
===========  ==========================================================
``silent``   No-op.
``log``      Log a warning ``"{source}: {message}"``.
``alert``    Call ``script.send_alert`` when it exists, else log a warning.
``stop``     Log an error and raise :class:`LabeledFeatureStop` so the
             caller can abort that unit of work.
===========  ==========================================================

The existing YAML scripts keep calling the script version; this module is used
by the component's own code paths and is also exposed as the
``labeled_features.error_mode`` action for future migrations.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .const import (
    ALERT_SCRIPT_ENTITY_ID,
    DEFAULT_ERROR_MODE,
    DEFAULT_ERROR_SEVERITY,
    DEFAULT_ERROR_SOURCE,
    ERROR_MODE_ALERT,
    ERROR_MODE_LOG,
    ERROR_MODE_SILENT,
    ERROR_MODE_STOP,
    ERROR_MODES,
)

_LOGGER = logging.getLogger(__package__)

ERROR_MODE_LABEL_PREFIX = "Error Mode: "


class LabeledFeatureStop(Exception):
    """Raised by the ``stop`` error tier to halt the current unit of work."""


def normalize_error_mode(value: str | None, default: str = DEFAULT_ERROR_MODE) -> str:
    """Normalize an error mode string, falling back to ``default``."""
    if value is None:
        return default
    mode = str(value).strip().lower()
    return mode if mode in ERROR_MODES else default


def resolve_error_mode(
    sensor_labels: list[str],
    option_default: str | None = None,
    scoped_feature_name: str | None = None,
) -> str:
    """Resolve the effective error mode.

    Precedence, highest first:

    1. ``<Scoped Feature> Error Mode: <tier>`` label on the sensor entity
    2. ``Error Mode: <tier>`` label on the sensor entity
    3. the config entry's default error mode
    4. ``log``
    """
    if scoped_feature_name:
        scoped_prefix = f"{scoped_feature_name} {ERROR_MODE_LABEL_PREFIX}"
        for label in sensor_labels:
            if label.startswith(scoped_prefix):
                mode = label[len(scoped_prefix) :].strip().lower()
                if mode in ERROR_MODES:
                    return mode

    for label in sensor_labels:
        if label.startswith(ERROR_MODE_LABEL_PREFIX):
            mode = label[len(ERROR_MODE_LABEL_PREFIX) :].strip().lower()
            if mode in ERROR_MODES:
                return mode

    return normalize_error_mode(option_default)


async def async_handle_error(
    hass: HomeAssistant,
    error_mode: str | None,
    message: str,
    source: str = DEFAULT_ERROR_SOURCE,
    severity: str = DEFAULT_ERROR_SEVERITY,
) -> None:
    """Dispatch an error through the requested tier.

    Raises :class:`LabeledFeatureStop` for the ``stop`` tier.
    """
    mode = normalize_error_mode(error_mode)
    text = f"{source}: {message}"

    if mode == ERROR_MODE_SILENT:
        return

    if mode == ERROR_MODE_LOG:
        _LOGGER.warning(text)
        return

    if mode == ERROR_MODE_ALERT:
        if hass.states.get(ALERT_SCRIPT_ENTITY_ID) is not None:
            await hass.services.async_call(
                "script",
                ALERT_SCRIPT_ENTITY_ID.split(".", 1)[1],
                {
                    "alert_severity": severity,
                    "alert_title": source,
                    "alert_message": message,
                },
                blocking=False,
            )
        else:
            _LOGGER.warning(
                "%s (alert tier requested but %s does not exist)",
                text,
                ALERT_SCRIPT_ENTITY_ID,
            )
        return

    if mode == ERROR_MODE_STOP:
        _LOGGER.error(text)
        raise LabeledFeatureStop(text)

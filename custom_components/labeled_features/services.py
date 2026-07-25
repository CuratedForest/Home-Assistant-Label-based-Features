"""Actions exposed by the Labeled Features integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_ERROR_MODE,
    DEFAULT_ERROR_SEVERITY,
    DEFAULT_ERROR_SOURCE,
    DOMAIN,
    ERROR_MODES,
    ERROR_SEVERITIES,
    FEATURE_SCOPES,
    SERVICE_ERROR_MODE,
    SERVICE_SET_FEATURE,
    SERVICE_SET_SNAPSHOT,
)
from .errors import LabeledFeatureStop, async_handle_error
from .routing import async_event_owner

SET_FEATURE_SCHEMA = vol.Schema(
    {
        vol.Required("target_feature"): cv.string,
        vol.Required("scope"): vol.In(FEATURE_SCOPES),
        vol.Optional("scope_id", default=""): cv.string,
        vol.Required("enabled"): cv.boolean,
        vol.Optional("instance"): cv.string,
    }
)

SET_SNAPSHOT_SCHEMA = vol.Schema(
    {
        vol.Required("snapshot_name"): cv.string,
        vol.Required("payload"): dict,
        vol.Optional("instance"): cv.string,
    }
)

ERROR_MODE_SCHEMA = vol.Schema(
    {
        vol.Optional("error_mode", default=DEFAULT_ERROR_MODE): vol.In(ERROR_MODES),
        vol.Required("message"): cv.string,
        vol.Optional("source", default=DEFAULT_ERROR_SOURCE): cv.string,
        vol.Optional("severity", default=DEFAULT_ERROR_SEVERITY): vol.In(
            ERROR_SEVERITIES
        ),
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions (idempotent)."""

    async def _async_set_feature(call: ServiceCall) -> None:
        data = dict(call.data)
        data.setdefault("timestamp", dt_util.utcnow().timestamp())
        coordinator = async_event_owner(hass, data, feature_event=True)
        if coordinator is None:
            raise ServiceValidationError(
                "No Labeled Features instance matched this call"
            )
        await coordinator.async_set_feature(data)

    async def _async_set_snapshot(call: ServiceCall) -> None:
        data = dict(call.data)
        coordinator = async_event_owner(hass, data, feature_event=False)
        if coordinator is None:
            raise ServiceValidationError(
                "No Labeled Features instance matched this call"
            )
        await coordinator.async_set_snapshot(data)

    async def _async_error_mode(call: ServiceCall) -> None:
        try:
            await async_handle_error(
                hass,
                call.data["error_mode"],
                call.data["message"],
                source=call.data["source"],
                severity=call.data["severity"],
            )
        except LabeledFeatureStop as err:
            # Surface the stop tier to the caller so their script can halt.
            raise ServiceValidationError(str(err)) from err

    if not hass.services.has_service(DOMAIN, SERVICE_SET_FEATURE):
        hass.services.async_register(
            DOMAIN, SERVICE_SET_FEATURE, _async_set_feature, SET_FEATURE_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_SNAPSHOT):
        hass.services.async_register(
            DOMAIN, SERVICE_SET_SNAPSHOT, _async_set_snapshot, SET_SNAPSHOT_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_ERROR_MODE):
        hass.services.async_register(
            DOMAIN, SERVICE_ERROR_MODE, _async_error_mode, ERROR_MODE_SCHEMA
        )


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the integration's actions when the last entry unloads."""
    for service in (SERVICE_SET_FEATURE, SERVICE_SET_SNAPSHOT, SERVICE_ERROR_MODE):
        hass.services.async_remove(DOMAIN, service)

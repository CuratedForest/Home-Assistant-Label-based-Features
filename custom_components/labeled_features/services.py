"""Services for Labeled Features."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service
import voluptuous as vol

from .const import DOMAIN, ERROR_LOG, ERROR_MODES
from .error_handler import async_handle_error_service

SERVICE_HANDLE_ERROR = "handle_error"

HANDLE_ERROR_SCHEMA = vol.Schema(
    {
        vol.Optional("error_mode", default=ERROR_LOG): vol.In(ERROR_MODES),
        vol.Required("message"): vol.All(cv.string, vol.Length(max=1024)),
        vol.Optional("source", default="Labeled Features"): vol.All(
            cv.string, vol.Length(max=255)
        ),
        vol.Optional("severity", default="medium"): vol.In(("low", "medium", "high")),
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Labeled Features.

    Registered admin-only: calls from automations/scripts (no user
    context) are unaffected, but interactive non-admin users cannot
    drive alert scripts or flood the log through this service.
    """
    if hass.services.has_service(DOMAIN, SERVICE_HANDLE_ERROR):
        return
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_HANDLE_ERROR,
        async_handle_error_service,
        schema=HANDLE_ERROR_SCHEMA,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Remove services when the last config entry unloads."""
    if hass.services.has_service(DOMAIN, SERVICE_HANDLE_ERROR):
        hass.services.async_remove(DOMAIN, SERVICE_HANDLE_ERROR)

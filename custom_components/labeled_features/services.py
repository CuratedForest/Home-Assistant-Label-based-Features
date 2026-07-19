"""Services for Labeled Features."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN
from .error_handler import async_handle_error_service


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Labeled Features."""
    async_register_admin_service(
        hass,
        DOMAIN,
        "handle_error",
        async_handle_error_service,
    )

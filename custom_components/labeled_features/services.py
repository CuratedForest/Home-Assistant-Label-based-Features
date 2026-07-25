from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_ERROR_MODE = "error_mode"

ATTR_ERROR_MODE = "error_mode"
ATTR_MESSAGE = "message"
ATTR_SOURCE = "source"
ATTR_SEVERITY = "severity"

ERROR_MODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ERROR_MODE): vol.In(
            ["silent", "log", "alert", "stop"]
        ),
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_SOURCE, default="Labeled Feature"): cv.string,
        vol.Optional(ATTR_SEVERITY, default="medium"): cv.string,
    }
)


async def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_ERROR_MODE):
        return

    async def handle_error_mode(call: ServiceCall) -> None:
        error_mode = call.data[ATTR_ERROR_MODE]
        message = call.data[ATTR_MESSAGE]
        source = call.data.get(ATTR_SOURCE, "Labeled Feature")
        severity = call.data.get(ATTR_SEVERITY, "medium")

        if error_mode == "silent":
            return

        if error_mode == "log":
            _LOGGER.warning("%s: %s", source, message)
            return

        if error_mode == "alert":
            _LOGGER.warning("%s: %s", source, message)
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": source,
                    "message": message,
                    "notification_id": f"{DOMAIN}_{source}_{severity}",
                },
            )
            return

        if error_mode == "stop":
            _LOGGER.error("%s: %s", source, message)
            return

    hass.services.async_register(
        DOMAIN,
        SERVICE_ERROR_MODE,
        handle_error_mode,
        schema=ERROR_MODE_SCHEMA,
    )


async def async_unregister_services(hass: HomeAssistant) -> None:
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_ERROR_MODE)

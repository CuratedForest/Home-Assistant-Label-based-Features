"""Config flow for Labeled Features.

Minimal — just enable/disable. All configuration is label-driven.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_ENABLED, DOMAIN


class LabeledFeaturesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Labeled Features."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a user init flow."""
        if user_input is not None:
            return self.async_create_entry(title="Labeled Features", data={})

        return self.async_show_form(
            step_id="user",
            last_step=True,
        )


class LabeledFeaturesOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, hass: HomeAssistant, entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.hass = hass
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            enabled = user_input.get(CONF_ENABLED, True)
            self.hass.data["labeled_features"]["features_coordinator"].is_disabled = (
                not enabled
            )
            self.hass.data["labeled_features"]["areas_coordinator"].is_disabled = (
                not enabled
            )
            return self.async_create_entry(
                title="Labeled Features", data=user_input
            )

        options = self.entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLED,
                        default=options.get(CONF_ENABLED, True),
                    ): bool,
                }
            ),
        )

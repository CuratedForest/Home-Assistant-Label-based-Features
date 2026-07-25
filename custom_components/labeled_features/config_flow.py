"""Config flow for Labeled Features.

Minimal, single-instance — just an enable/disable option. All feature
configuration is label-driven; config subentry inputs are deferred to a
later part.
"""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
import voluptuous as vol

from .const import CONF_ENABLED, DOMAIN


class LabeledFeaturesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Labeled Features."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a user init flow."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Labeled Features", data={})

        return self.async_show_form(step_id="user", last_step=True)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> LabeledFeaturesOptionsFlow:
        """Create the options flow."""
        return LabeledFeaturesOptionsFlow()


class LabeledFeaturesOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow (enable/disable only)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
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

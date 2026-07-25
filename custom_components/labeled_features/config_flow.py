from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_FEATURE_PREFIX,
    CONF_INSTANCE_NAME,
    CONF_LEADER_LABEL,
    DEFAULT_FEATURE_PREFIX,
    DEFAULT_LEADER_LABEL,
    DOMAIN,
)


class LabeledFeaturesConfigFlow(ConfigFlow, domain=DOMAIN):

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LabeledFeaturesOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input[CONF_INSTANCE_NAME].strip()
            leader_label = user_input[CONF_LEADER_LABEL].strip()
            feature_prefix = user_input.get(CONF_FEATURE_PREFIX, DEFAULT_FEATURE_PREFIX).strip()

            if not name:
                errors[CONF_INSTANCE_NAME] = "empty_name"
            elif not leader_label:
                errors[CONF_LEADER_LABEL] = "empty_leader_label"
            else:
                await self.async_set_unique_id(
                    f"{DOMAIN}_{name.lower().replace(' ', '_')}"
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_INSTANCE_NAME: name,
                        CONF_LEADER_LABEL: leader_label,
                        CONF_FEATURE_PREFIX: feature_prefix,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INSTANCE_NAME): str,
                    vol.Required(
                        CONF_LEADER_LABEL, default=DEFAULT_LEADER_LABEL
                    ): str,
                    vol.Optional(
                        CONF_FEATURE_PREFIX, default=DEFAULT_FEATURE_PREFIX
                    ): str,
                }
            ),
            errors=errors,
        )


class LabeledFeaturesOptionsFlow(OptionsFlow):

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            new_data = {**self._config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )
            return self.async_create_entry(title="", data=user_input)

        current_leader = self._config_entry.data.get(
            CONF_LEADER_LABEL, DEFAULT_LEADER_LABEL
        )
        current_prefix = self._config_entry.data.get(
            CONF_FEATURE_PREFIX, DEFAULT_FEATURE_PREFIX
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LEADER_LABEL, default=current_leader
                    ): str,
                    vol.Optional(
                        CONF_FEATURE_PREFIX, default=current_prefix
                    ): str,
                }
            ),
        )

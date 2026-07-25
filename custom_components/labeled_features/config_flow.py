"""Config and options flow for the Labeled Features integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_DEFAULT_ERROR_MODE,
    CONF_DEFAULT_MODE,
    CONF_DEFAULT_SCRIPT_CALL_MODE,
    CONF_LEADER_LABEL,
    CONF_MODE_OVERRIDES,
    CONF_NAME,
    CONF_PREFIX,
    CONF_SCRIPT_CALL_MODE_OVERRIDES,
    DEFAULT_ERROR_MODE,
    DEFAULT_LEADER_LABEL,
    DEFAULT_MODE,
    DEFAULT_NAME,
    DEFAULT_PREFIX,
    DEFAULT_SCRIPT_CALL_MODE,
    DOMAIN,
    ERROR_MODES,
    MODES,
    SCRIPT_CALL_MODES,
)
from .coordinator import validate_overrides

MODE_OVERRIDE_VALUES = {"Leader": "leader", "Any": "any", "All": "all"}
SCRIPT_CALL_MODE_OVERRIDE_VALUES = {
    "Blocking": "Blocking",
    "NonBlocking": "NonBlocking",
}


def _settings_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the schema shared by the config and options steps."""
    return vol.Schema(
        {
            vol.Required(
                CONF_LEADER_LABEL, default=defaults[CONF_LEADER_LABEL]
            ): selector.TextSelector(),
            vol.Required(
                CONF_DEFAULT_MODE, default=defaults[CONF_DEFAULT_MODE]
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(MODES),
                    translation_key="resolution_mode",
                )
            ),
            vol.Required(
                CONF_DEFAULT_SCRIPT_CALL_MODE,
                default=defaults[CONF_DEFAULT_SCRIPT_CALL_MODE],
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=list(SCRIPT_CALL_MODES))
            ),
            vol.Required(
                CONF_DEFAULT_ERROR_MODE, default=defaults[CONF_DEFAULT_ERROR_MODE]
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(ERROR_MODES),
                    translation_key="error_mode",
                )
            ),
            vol.Optional(
                CONF_MODE_OVERRIDES, default=defaults[CONF_MODE_OVERRIDES]
            ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            vol.Optional(
                CONF_SCRIPT_CALL_MODE_OVERRIDES,
                default=defaults[CONF_SCRIPT_CALL_MODE_OVERRIDES],
            ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
        }
    )


def _validate_settings(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate the shared settings, returning a field -> error-key mapping."""
    errors: dict[str, str] = {}

    if not str(user_input.get(CONF_LEADER_LABEL, "")).strip():
        errors[CONF_LEADER_LABEL] = "leader_label_required"

    if validate_overrides(
        user_input.get(CONF_MODE_OVERRIDES), "Mode", MODE_OVERRIDE_VALUES
    ):
        errors[CONF_MODE_OVERRIDES] = "invalid_mode_override"

    if validate_overrides(
        user_input.get(CONF_SCRIPT_CALL_MODE_OVERRIDES),
        "Script Call Mode",
        SCRIPT_CALL_MODE_OVERRIDE_VALUES,
    ):
        errors[CONF_SCRIPT_CALL_MODE_OVERRIDES] = "invalid_script_call_mode_override"

    return errors


class LabeledFeaturesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration of an instance."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a new instance."""
        errors: dict[str, str] = {}

        if user_input is not None:
            prefix = str(user_input.get(CONF_PREFIX, "")).strip()
            errors = _validate_settings(user_input)

            if not prefix or slugify(prefix) != prefix:
                errors[CONF_PREFIX] = "invalid_prefix"
            else:
                for entry in self._async_current_entries():
                    if entry.data.get(CONF_PREFIX) == prefix:
                        errors[CONF_PREFIX] = "prefix_in_use"
                        break

            if not errors:
                name = str(user_input.get(CONF_NAME, "")).strip() or DEFAULT_NAME
                return self.async_create_entry(
                    title=name,
                    data={CONF_NAME: name, CONF_PREFIX: prefix},
                    options={
                        CONF_LEADER_LABEL: str(user_input[CONF_LEADER_LABEL]).strip(),
                        CONF_DEFAULT_MODE: user_input[CONF_DEFAULT_MODE],
                        CONF_DEFAULT_SCRIPT_CALL_MODE: user_input[
                            CONF_DEFAULT_SCRIPT_CALL_MODE
                        ],
                        CONF_DEFAULT_ERROR_MODE: user_input[CONF_DEFAULT_ERROR_MODE],
                        CONF_MODE_OVERRIDES: user_input.get(CONF_MODE_OVERRIDES, ""),
                        CONF_SCRIPT_CALL_MODE_OVERRIDES: user_input.get(
                            CONF_SCRIPT_CALL_MODE_OVERRIDES, ""
                        ),
                    },
                )

        previous = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=previous.get(CONF_NAME, DEFAULT_NAME)
                ): selector.TextSelector(),
                vol.Required(
                    CONF_PREFIX, default=previous.get(CONF_PREFIX, DEFAULT_PREFIX)
                ): selector.TextSelector(),
            }
        ).extend(
            _settings_schema(
                {
                    CONF_LEADER_LABEL: previous.get(
                        CONF_LEADER_LABEL, DEFAULT_LEADER_LABEL
                    ),
                    CONF_DEFAULT_MODE: previous.get(CONF_DEFAULT_MODE, DEFAULT_MODE),
                    CONF_DEFAULT_SCRIPT_CALL_MODE: previous.get(
                        CONF_DEFAULT_SCRIPT_CALL_MODE, DEFAULT_SCRIPT_CALL_MODE
                    ),
                    CONF_DEFAULT_ERROR_MODE: previous.get(
                        CONF_DEFAULT_ERROR_MODE, DEFAULT_ERROR_MODE
                    ),
                    CONF_MODE_OVERRIDES: previous.get(CONF_MODE_OVERRIDES, ""),
                    CONF_SCRIPT_CALL_MODE_OVERRIDES: previous.get(
                        CONF_SCRIPT_CALL_MODE_OVERRIDES, ""
                    ),
                }
            ).schema
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return LabeledFeaturesOptionsFlow()


class LabeledFeaturesOptionsFlow(OptionsFlow):
    """Handle instance options.

    The slug prefix is intentionally absent: changing it would orphan the
    existing entity ids. Rename the entities in the entity registry instead.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_settings(user_input)
            if not errors:
                return self.async_create_entry(
                    data={
                        **user_input,
                        CONF_LEADER_LABEL: str(user_input[CONF_LEADER_LABEL]).strip(),
                    }
                )

        current = {**self.config_entry.options, **(user_input or {})}
        schema = _settings_schema(
            {
                CONF_LEADER_LABEL: current.get(CONF_LEADER_LABEL, DEFAULT_LEADER_LABEL),
                CONF_DEFAULT_MODE: current.get(CONF_DEFAULT_MODE, DEFAULT_MODE),
                CONF_DEFAULT_SCRIPT_CALL_MODE: current.get(
                    CONF_DEFAULT_SCRIPT_CALL_MODE, DEFAULT_SCRIPT_CALL_MODE
                ),
                CONF_DEFAULT_ERROR_MODE: current.get(
                    CONF_DEFAULT_ERROR_MODE, DEFAULT_ERROR_MODE
                ),
                CONF_MODE_OVERRIDES: current.get(CONF_MODE_OVERRIDES, ""),
                CONF_SCRIPT_CALL_MODE_OVERRIDES: current.get(
                    CONF_SCRIPT_CALL_MODE_OVERRIDES, ""
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

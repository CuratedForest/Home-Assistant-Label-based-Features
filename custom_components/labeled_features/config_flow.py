"""Config, options and subentry flows for the Labeled Features integration.

The instance settings are instance-level defaults only: labels on the created
sensor entities still win over them. Subentries (leader definitions, area
Provides declarations, feature Modes) are the UI-driven alternative to
authoring labels — a real label defining the same thing wins on conflict.
"""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_ALERT_ACTION,
    CONF_ALERT_SEVERITY,
    CONF_DEFAULT_ERROR_MODE,
    CONF_DEFAULT_MODE,
    CONF_DEFAULT_SCRIPT_CALL_MODE,
    CONF_LEADER_LABEL,
    CONF_MODE_OVERRIDES,
    CONF_NAME,
    CONF_PREFIX,
    CONF_SCRIPT_CALL_MODE_OVERRIDES,
    DEFAULT_ALERT_ACTION,
    DEFAULT_ALERT_SEVERITY,
    DEFAULT_ERROR_MODE,
    DEFAULT_LEADER_LABEL,
    DEFAULT_MODE,
    DEFAULT_NAME,
    DEFAULT_PREFIX,
    DEFAULT_SCRIPT_CALL_MODE,
    DIRECTION_NONE,
    DIRECTIONS,
    DOMAIN,
    ERROR_MODES,
    ERROR_SEVERITIES,
    LEADER_SCOPES,
    MODE_LEADER,
    MODES,
    PROVIDES_COMPONENTS,
    PROVIDES_SCOPES,
    SCOPE_AREA,
    SCRIPT_CALL_MODES,
    SUBCONF_AREA_ID,
    SUBCONF_COMPONENT,
    SUBCONF_DIRECTION,
    SUBCONF_DISABLE_VALUE,
    SUBCONF_ENABLE_VALUE,
    SUBCONF_FEATURE,
    SUBCONF_INVERT,
    SUBCONF_MODE,
    SUBCONF_SCOPE,
    SUBENTRY_TYPE_LEADER,
    SUBENTRY_TYPE_MODE,
    SUBENTRY_TYPE_PROVIDES,
)
from .coordinator import validate_overrides

MODE_OVERRIDE_VALUES = {"Leader": "leader", "Any": "any", "All": "all"}
SCRIPT_CALL_MODE_OVERRIDE_VALUES = {
    "Blocking": "Blocking",
    "NonBlocking": "NonBlocking",
}

_ALERT_ACTION_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def _select(
    options: list[str] | tuple[str, ...], **kwargs: Any
) -> selector.SelectSelector:
    """Build a dropdown selector (never a list, regardless of option count)."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(options),
            mode=selector.SelectSelectorMode.DROPDOWN,
            **kwargs,
        )
    )


def _settings_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the schema shared by the config and options steps."""
    return vol.Schema(
        {
            vol.Required(
                CONF_LEADER_LABEL, default=defaults[CONF_LEADER_LABEL]
            ): selector.TextSelector(),
            vol.Required(
                CONF_DEFAULT_MODE, default=defaults[CONF_DEFAULT_MODE]
            ): _select(MODES, translation_key="resolution_mode"),
            vol.Required(
                CONF_DEFAULT_SCRIPT_CALL_MODE,
                default=defaults[CONF_DEFAULT_SCRIPT_CALL_MODE],
            ): _select(SCRIPT_CALL_MODES),
            vol.Required(
                CONF_DEFAULT_ERROR_MODE, default=defaults[CONF_DEFAULT_ERROR_MODE]
            ): _select(ERROR_MODES, translation_key="error_mode"),
            vol.Required(
                CONF_ALERT_ACTION, default=defaults[CONF_ALERT_ACTION]
            ): selector.TextSelector(),
            vol.Required(
                CONF_ALERT_SEVERITY, default=defaults[CONF_ALERT_SEVERITY]
            ): _select(ERROR_SEVERITIES),
            vol.Optional(
                CONF_MODE_OVERRIDES, default=defaults[CONF_MODE_OVERRIDES]
            ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
            vol.Optional(
                CONF_SCRIPT_CALL_MODE_OVERRIDES,
                default=defaults[CONF_SCRIPT_CALL_MODE_OVERRIDES],
            ): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
        }
    )


def _settings_defaults(source: dict[str, Any]) -> dict[str, Any]:
    """Collect the settings defaults from stored data/options or input."""
    return {
        CONF_LEADER_LABEL: source.get(CONF_LEADER_LABEL, DEFAULT_LEADER_LABEL),
        CONF_DEFAULT_MODE: source.get(CONF_DEFAULT_MODE, DEFAULT_MODE),
        CONF_DEFAULT_SCRIPT_CALL_MODE: source.get(
            CONF_DEFAULT_SCRIPT_CALL_MODE, DEFAULT_SCRIPT_CALL_MODE
        ),
        CONF_DEFAULT_ERROR_MODE: source.get(
            CONF_DEFAULT_ERROR_MODE, DEFAULT_ERROR_MODE
        ),
        CONF_ALERT_ACTION: source.get(CONF_ALERT_ACTION, DEFAULT_ALERT_ACTION),
        CONF_ALERT_SEVERITY: source.get(CONF_ALERT_SEVERITY, DEFAULT_ALERT_SEVERITY),
        CONF_MODE_OVERRIDES: source.get(CONF_MODE_OVERRIDES, ""),
        CONF_SCRIPT_CALL_MODE_OVERRIDES: source.get(
            CONF_SCRIPT_CALL_MODE_OVERRIDES, ""
        ),
    }


def _validate_settings(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate the shared settings, returning a field -> error-key mapping."""
    errors: dict[str, str] = {}

    if not str(user_input.get(CONF_LEADER_LABEL, "")).strip():
        errors[CONF_LEADER_LABEL] = "leader_label_required"

    if not _ALERT_ACTION_RE.match(str(user_input.get(CONF_ALERT_ACTION, "")).strip()):
        errors[CONF_ALERT_ACTION] = "alert_action_invalid"

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


_SETTINGS_KEYS = (
    CONF_LEADER_LABEL,
    CONF_DEFAULT_MODE,
    CONF_DEFAULT_SCRIPT_CALL_MODE,
    CONF_DEFAULT_ERROR_MODE,
    CONF_ALERT_ACTION,
    CONF_ALERT_SEVERITY,
    CONF_MODE_OVERRIDES,
    CONF_SCRIPT_CALL_MODE_OVERRIDES,
)


def _clean_settings(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize free-text settings and keep only the settings keys."""
    cleaned = {
        CONF_LEADER_LABEL: str(user_input[CONF_LEADER_LABEL]).strip(),
        CONF_ALERT_ACTION: str(user_input[CONF_ALERT_ACTION]).strip(),
    }
    return {key: cleaned.get(key, user_input.get(key, "")) for key in _SETTINGS_KEYS}


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
                    options=_clean_settings(user_input),
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
        ).extend(_settings_schema(_settings_defaults(previous)).schema)

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return LabeledFeaturesOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the supported subentry flows."""
        return {
            SUBENTRY_TYPE_LEADER: LeaderSubentryFlow,
            SUBENTRY_TYPE_PROVIDES: ProvidesSubentryFlow,
            SUBENTRY_TYPE_MODE: ModeSubentryFlow,
        }


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
                return self.async_create_entry(data=_clean_settings(user_input))

        current = {**self.config_entry.options, **(user_input or {})}
        schema = _settings_schema(_settings_defaults(current))

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


class _BaseSubentryFlow(ConfigSubentryFlow):
    """Shared helpers for the subentry flows."""

    def _unique_id_taken(
        self, unique_id: str, ignore_subentry_id: str | None = None
    ) -> bool:
        """Return True when another subentry of this entry uses the id."""
        entry = self._get_entry()
        return any(
            sub.unique_id == unique_id and sub.subentry_id != ignore_subentry_id
            for sub in entry.subentries.values()
        )

    def _create_or_abort(
        self, user_input: dict[str, Any], unique_id: str, title: str
    ) -> SubentryFlowResult:
        """Create the subentry, aborting when the unique id is taken."""
        if self._unique_id_taken(unique_id):
            return self.async_abort(reason="already_configured")
        return self.async_create_entry(
            title=title, data=user_input, unique_id=unique_id
        )

    def _update_or_abort(
        self,
        user_input: dict[str, Any],
        unique_id: str,
        title: str,
    ) -> SubentryFlowResult:
        """Update the subentry being reconfigured, aborting on id collisions."""
        subentry = self._get_reconfigure_subentry()
        if self._unique_id_taken(unique_id, ignore_subentry_id=subentry.subentry_id):
            return self.async_abort(reason="already_configured")
        return self.async_update_and_abort(
            self._get_entry(),
            subentry,
            title=title,
            data=user_input,
            unique_id=unique_id,
        )


def _feature_or_error(
    flow: ConfigSubentryFlow,
    step_id: str,
    schema: vol.Schema,
    user_input: dict[str, Any],
) -> str | SubentryFlowResult:
    """Return the stripped feature name, or a form result with the error."""
    feature = str(user_input.get(SUBCONF_FEATURE, "")).strip()
    user_input[SUBCONF_FEATURE] = feature
    if not feature:
        return flow.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors={SUBCONF_FEATURE: "feature_required"},
        )
    return feature


class LeaderSubentryFlow(_BaseSubentryFlow):
    """Leader definition subentry (label-free alternative to Leader labels)."""

    def _schema(self, defaults: dict[str, Any]) -> vol.Schema:
        """Build the leader schema with defaults."""
        return vol.Schema(
            {
                vol.Required(
                    CONF_ENTITY_ID,
                    default=defaults.get(CONF_ENTITY_ID, vol.UNDEFINED),
                ): selector.EntitySelector(),
                vol.Required(
                    SUBCONF_FEATURE,
                    default=defaults.get(SUBCONF_FEATURE, ""),
                ): selector.TextSelector(),
                vol.Required(
                    SUBCONF_SCOPE,
                    default=defaults.get(SUBCONF_SCOPE, SCOPE_AREA),
                ): _select(LEADER_SCOPES),
                vol.Optional(
                    SUBCONF_ENABLE_VALUE,
                    default=defaults.get(SUBCONF_ENABLE_VALUE, ""),
                ): selector.TextSelector(),
                vol.Optional(
                    SUBCONF_DISABLE_VALUE,
                    default=defaults.get(SUBCONF_DISABLE_VALUE, ""),
                ): selector.TextSelector(),
                vol.Optional(
                    SUBCONF_DIRECTION,
                    default=defaults.get(SUBCONF_DIRECTION, DIRECTION_NONE),
                ): _select(DIRECTIONS),
                vol.Optional(
                    SUBCONF_INVERT,
                    default=defaults.get(SUBCONF_INVERT, False),
                ): selector.BooleanSelector(),
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a leader definition."""
        if user_input is not None:
            feature = _feature_or_error(
                self, "user", self._schema(user_input), user_input
            )
            if not isinstance(feature, str):
                return feature
            title = f"{feature} ({user_input[CONF_ENTITY_ID]})"
            unique_id = (
                f"{user_input[CONF_ENTITY_ID]}|{feature}|{user_input[SUBCONF_SCOPE]}"
            )
            return self._create_or_abort(user_input, unique_id, title)
        return self.async_show_form(step_id="user", data_schema=self._schema({}))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a leader definition."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            feature = _feature_or_error(
                self, "reconfigure", self._schema(user_input), user_input
            )
            if not isinstance(feature, str):
                return feature
            title = f"{feature} ({user_input[CONF_ENTITY_ID]})"
            unique_id = (
                f"{user_input[CONF_ENTITY_ID]}|{feature}|{user_input[SUBCONF_SCOPE]}"
            )
            return self._update_or_abort(user_input, unique_id, title)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._schema(dict(subentry.data)),
        )


class ProvidesSubentryFlow(_BaseSubentryFlow):
    """Provides declaration subentry (label-free alternative to Provides labels)."""

    def _schema(self, defaults: dict[str, Any]) -> vol.Schema:
        """Build the provides schema with defaults."""
        return vol.Schema(
            {
                vol.Required(
                    SUBCONF_AREA_ID,
                    default=defaults.get(SUBCONF_AREA_ID, vol.UNDEFINED),
                ): selector.AreaSelector(),
                vol.Required(
                    SUBCONF_FEATURE,
                    default=defaults.get(SUBCONF_FEATURE, ""),
                ): selector.TextSelector(),
                vol.Required(
                    SUBCONF_SCOPE,
                    default=defaults.get(SUBCONF_SCOPE, SCOPE_AREA),
                ): _select(PROVIDES_SCOPES),
                vol.Optional(
                    SUBCONF_COMPONENT,
                    default=defaults.get(SUBCONF_COMPONENT, "select"),
                ): _select(PROVIDES_COMPONENTS, custom_value=True),
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a Provides declaration."""
        if user_input is not None:
            feature = _feature_or_error(
                self, "user", self._schema(user_input), user_input
            )
            if not isinstance(feature, str):
                return feature
            title = f"{feature} ({user_input[SUBCONF_AREA_ID]})"
            unique_id = (
                f"{user_input[SUBCONF_AREA_ID]}|{feature}|{user_input[SUBCONF_SCOPE]}"
            )
            return self._create_or_abort(user_input, unique_id, title)
        return self.async_show_form(step_id="user", data_schema=self._schema({}))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a Provides declaration."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            feature = _feature_or_error(
                self, "reconfigure", self._schema(user_input), user_input
            )
            if not isinstance(feature, str):
                return feature
            title = f"{feature} ({user_input[SUBCONF_AREA_ID]})"
            unique_id = (
                f"{user_input[SUBCONF_AREA_ID]}|{feature}|{user_input[SUBCONF_SCOPE]}"
            )
            return self._update_or_abort(user_input, unique_id, title)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._schema(dict(subentry.data)),
        )


class ModeSubentryFlow(_BaseSubentryFlow):
    """Feature Mode subentry (label-free alternative to `Mode:` sensor labels)."""

    def _schema(self, defaults: dict[str, Any]) -> vol.Schema:
        """Build the mode schema with defaults."""
        return vol.Schema(
            {
                vol.Required(
                    SUBCONF_FEATURE,
                    default=defaults.get(SUBCONF_FEATURE, ""),
                ): selector.TextSelector(),
                vol.Required(
                    SUBCONF_SCOPE,
                    default=defaults.get(SUBCONF_SCOPE, SCOPE_AREA),
                ): _select(LEADER_SCOPES),
                vol.Required(
                    SUBCONF_MODE,
                    default=defaults.get(SUBCONF_MODE, MODE_LEADER),
                ): _select(MODES, translation_key="resolution_mode"),
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a feature mode."""
        if user_input is not None:
            feature = _feature_or_error(
                self, "user", self._schema(user_input), user_input
            )
            if not isinstance(feature, str):
                return feature
            title = (
                f"{feature} ({user_input[SUBCONF_SCOPE]}: {user_input[SUBCONF_MODE]})"
            )
            unique_id = f"{feature}|{user_input[SUBCONF_SCOPE]}"
            return self._create_or_abort(user_input, unique_id, title)
        return self.async_show_form(step_id="user", data_schema=self._schema({}))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a feature mode."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            feature = _feature_or_error(
                self, "reconfigure", self._schema(user_input), user_input
            )
            if not isinstance(feature, str):
                return feature
            title = (
                f"{feature} ({user_input[SUBCONF_SCOPE]}: {user_input[SUBCONF_MODE]})"
            )
            unique_id = f"{feature}|{user_input[SUBCONF_SCOPE]}"
            return self._update_or_abort(user_input, unique_id, title)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._schema(dict(subentry.data)),
        )

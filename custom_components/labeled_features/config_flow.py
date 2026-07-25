"""Config flow for the Labeled Features integration.

The plan calls for one entry per instance. Fields:

- instance_name (str)          — free-form title, slug used as unique_id.
- leader_label (str)           — the label a leader entity must carry to
                                 participate in this instance.
- features_state_entity_id     — the entity_id for `sensor.labeled_features_state`.
- areas_state_entity_id        — the entity_id for `sensor.labeled_feature_areas_state`.
- error_mode_default (select)  — silent | log | alert | stop.
- script_call_mode_default     — Blocking | NonBlocking.

Duplicate `leader_label` / entity_id across active entries are rejected.
An entity_id already owned by another entity (state present, not part of
this integration) is rejected too so the user removes the legacy YAML
template sensor before installing the component.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.util import slugify

from .const import (
    CONF_AREAS_STATE_ENTITY_ID,
    CONF_ERROR_MODE_DEFAULT,
    CONF_FEATURES_STATE_ENTITY_ID,
    CONF_INSTANCE_NAME,
    CONF_LEADER_LABEL,
    CONF_SCRIPT_CALL_MODE_DEFAULT,
    DEFAULT_AREAS_STATE_ENTITY_ID,
    DEFAULT_ERROR_MODE,
    DEFAULT_FEATURES_STATE_ENTITY_ID,
    DEFAULT_INSTANCE_NAME,
    DEFAULT_LEADER_LABEL,
    DEFAULT_SCRIPT_CALL_MODE,
    DOMAIN,
    ERROR_MODES,
    SCRIPT_CALL_MODES,
)


def _base_schema(
    *,
    include_instance_name: bool,
    defaults: dict[str, Any],
) -> vol.Schema:
    schema: dict[Any, Any] = {}
    if include_instance_name:
        schema[
            vol.Required(
                CONF_INSTANCE_NAME,
                default=defaults.get(CONF_INSTANCE_NAME, DEFAULT_INSTANCE_NAME),
            )
        ] = cv.string
    schema[
        vol.Required(
            CONF_LEADER_LABEL,
            default=defaults.get(CONF_LEADER_LABEL, DEFAULT_LEADER_LABEL),
        )
    ] = cv.string
    schema[
        vol.Required(
            CONF_FEATURES_STATE_ENTITY_ID,
            default=defaults.get(
                CONF_FEATURES_STATE_ENTITY_ID, DEFAULT_FEATURES_STATE_ENTITY_ID
            ),
        )
    ] = cv.string
    schema[
        vol.Required(
            CONF_AREAS_STATE_ENTITY_ID,
            default=defaults.get(
                CONF_AREAS_STATE_ENTITY_ID, DEFAULT_AREAS_STATE_ENTITY_ID
            ),
        )
    ] = cv.string
    schema[
        vol.Required(
            CONF_ERROR_MODE_DEFAULT,
            default=defaults.get(CONF_ERROR_MODE_DEFAULT, DEFAULT_ERROR_MODE),
        )
    ] = vol.In(ERROR_MODES)
    schema[
        vol.Required(
            CONF_SCRIPT_CALL_MODE_DEFAULT,
            default=defaults.get(
                CONF_SCRIPT_CALL_MODE_DEFAULT, DEFAULT_SCRIPT_CALL_MODE
            ),
        )
    ] = vol.In(SCRIPT_CALL_MODES)
    return vol.Schema(schema)


def _validate(
    hass_states,
    entries: list[ConfigEntry],
    user_input: dict[str, Any],
    *,
    self_entry_id: str | None = None,
) -> dict[str, str]:
    """Return a dict of {field: error_key} — empty when valid."""

    errors: dict[str, str] = {}

    leader_label = (user_input.get(CONF_LEADER_LABEL) or "").strip()
    if not leader_label:
        errors[CONF_LEADER_LABEL] = "leader_label_required"

    features_eid = (user_input.get(CONF_FEATURES_STATE_ENTITY_ID) or "").strip()
    areas_eid = (user_input.get(CONF_AREAS_STATE_ENTITY_ID) or "").strip()

    for field, eid in (
        (CONF_FEATURES_STATE_ENTITY_ID, features_eid),
        (CONF_AREAS_STATE_ENTITY_ID, areas_eid),
    ):
        try:
            cv.entity_id(eid)
        except vol.Invalid:
            errors[field] = "invalid_entity_id"
            continue
        if not eid.startswith("sensor."):
            errors[field] = "invalid_entity_id"

    if features_eid and areas_eid and features_eid == areas_eid:
        errors[CONF_AREAS_STATE_ENTITY_ID] = "entity_id_conflict"

    # Cross-entry duplicate checks.
    for entry in entries:
        if self_entry_id is not None and entry.entry_id == self_entry_id:
            continue
        data = {**entry.data, **entry.options}
        if data.get(CONF_LEADER_LABEL) == leader_label:
            errors[CONF_LEADER_LABEL] = "duplicate_leader_label"
        if data.get(CONF_FEATURES_STATE_ENTITY_ID) == features_eid:
            errors[CONF_FEATURES_STATE_ENTITY_ID] = "duplicate_entity_id"
        if data.get(CONF_AREAS_STATE_ENTITY_ID) == areas_eid:
            errors[CONF_AREAS_STATE_ENTITY_ID] = "duplicate_entity_id"

    # If a state already exists at either entity_id and it doesn't belong
    # to this integration, reject so the user removes the YAML template
    # sensor first (otherwise HA will suffix _2 onto the new sensor).
    if hass_states is not None:
        for field, eid in (
            (CONF_FEATURES_STATE_ENTITY_ID, features_eid),
            (CONF_AREAS_STATE_ENTITY_ID, areas_eid),
        ):
            if not eid:
                continue
            state = hass_states.get(eid)
            if state is None:
                continue
            # Ownership check: only reject if the state exists and is not
            # already owned by this integration's registry entry. We don't
            # have the entity registry here so we compare loosely against
            # the union of existing entries' configured IDs.
            other_managed = {
                (e.data.get(CONF_FEATURES_STATE_ENTITY_ID) or "")
                for e in entries
                if e.entry_id != self_entry_id
            } | {
                (e.data.get(CONF_AREAS_STATE_ENTITY_ID) or "")
                for e in entries
                if e.entry_id != self_entry_id
            }
            if eid not in other_managed and field not in errors:
                errors[field] = "entity_id_taken"

    return errors


class LabeledFeaturesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Labeled Features."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entries = list(self.hass.config_entries.async_entries(DOMAIN))
            errors = _validate(self.hass.states, entries, user_input)
            if not errors:
                instance_name = (
                    user_input.get(CONF_INSTANCE_NAME) or DEFAULT_INSTANCE_NAME
                ).strip()
                unique_id = slugify(instance_name) or DEFAULT_LEADER_LABEL
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                data = {
                    CONF_INSTANCE_NAME: instance_name,
                    CONF_LEADER_LABEL: user_input[CONF_LEADER_LABEL].strip(),
                    CONF_FEATURES_STATE_ENTITY_ID: user_input[
                        CONF_FEATURES_STATE_ENTITY_ID
                    ].strip(),
                    CONF_AREAS_STATE_ENTITY_ID: user_input[
                        CONF_AREAS_STATE_ENTITY_ID
                    ].strip(),
                    CONF_ERROR_MODE_DEFAULT: user_input[CONF_ERROR_MODE_DEFAULT],
                    CONF_SCRIPT_CALL_MODE_DEFAULT: user_input[
                        CONF_SCRIPT_CALL_MODE_DEFAULT
                    ],
                }
                return self.async_create_entry(title=instance_name, data=data)

        defaults = user_input if user_input is not None else {}
        return self.async_show_form(
            step_id="user",
            data_schema=_base_schema(include_instance_name=True, defaults=defaults),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LabeledFeaturesOptionsFlow(config_entry)


class LabeledFeaturesOptionsFlow(OptionsFlow):
    """Options flow: everything except instance_name."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        merged = {**self._entry.data, **self._entry.options}
        if user_input is not None:
            candidate = {**merged, **user_input}
            entries = list(self._entry.hass.config_entries.async_entries(DOMAIN))
            errors = _validate(
                self._entry.hass.states,
                entries,
                candidate,
                self_entry_id=self._entry.entry_id,
            )
            if not errors:
                # Persist into options so the entry title (instance_name)
                # stays clean; __init__.py reads {**data, **options}.
                normalised: dict[str, Any] = {
                    CONF_LEADER_LABEL: user_input[CONF_LEADER_LABEL].strip(),
                    CONF_FEATURES_STATE_ENTITY_ID: user_input[
                        CONF_FEATURES_STATE_ENTITY_ID
                    ].strip(),
                    CONF_AREAS_STATE_ENTITY_ID: user_input[
                        CONF_AREAS_STATE_ENTITY_ID
                    ].strip(),
                    CONF_ERROR_MODE_DEFAULT: user_input[CONF_ERROR_MODE_DEFAULT],
                    CONF_SCRIPT_CALL_MODE_DEFAULT: user_input[
                        CONF_SCRIPT_CALL_MODE_DEFAULT
                    ],
                }
                return self.async_create_entry(title="", data=normalised)

        defaults = user_input if user_input is not None else merged
        return self.async_show_form(
            step_id="init",
            data_schema=_base_schema(include_instance_name=False, defaults=defaults),
            errors=errors,
        )

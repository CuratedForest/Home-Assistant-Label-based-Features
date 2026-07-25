"""Test configuration for the Labeled Features integration."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.labeled_features.const import (
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
    DEFAULT_PREFIX,
    DEFAULT_SCRIPT_CALL_MODE,
    DOMAIN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None, None, None]:
    """Enable loading of custom integrations in every test."""
    yield


@pytest.fixture
def leader_label(hass: HomeAssistant) -> lr.LabelEntry:
    """Create the default leader label."""
    return lr.async_get(hass).async_create(DEFAULT_LEADER_LABEL)


def make_entry(
    prefix: str = DEFAULT_PREFIX,
    name: str = "Labeled Features",
    **options: Any,
) -> MockConfigEntry:
    """Build a config entry for the integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=name,
        data={CONF_NAME: name, CONF_PREFIX: prefix},
        options={
            CONF_LEADER_LABEL: DEFAULT_LEADER_LABEL,
            CONF_DEFAULT_MODE: DEFAULT_MODE,
            CONF_DEFAULT_SCRIPT_CALL_MODE: DEFAULT_SCRIPT_CALL_MODE,
            CONF_DEFAULT_ERROR_MODE: DEFAULT_ERROR_MODE,
            CONF_MODE_OVERRIDES: "",
            CONF_SCRIPT_CALL_MODE_OVERRIDES: "",
            **options,
        },
    )


async def setup_entry(
    hass: HomeAssistant, entry: MockConfigEntry | None = None
) -> MockConfigEntry:
    """Add and set up a config entry."""
    entry = entry or make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def label_ids(hass: HomeAssistant, names: list[str]) -> set[str]:
    """Create labels by name and return their ids."""
    registry = lr.async_get(hass)
    ids = set()
    for name in names:
        entry = registry.async_get_label_by_name(name) or registry.async_create(name)
        ids.add(entry.label_id)
    return ids


def register_entity(
    hass: HomeAssistant,
    entity_id: str,
    *,
    labels: list[str] | None = None,
    area_id: str | None = None,
    state: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> er.RegistryEntry:
    """Register an entity with labels/area and optionally set its state."""
    domain, object_id = entity_id.split(".", 1)
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        domain=domain,
        platform="test",
        unique_id=object_id,
        suggested_object_id=object_id,
    )
    entry = registry.async_update_entity(
        entry.entity_id,
        labels=label_ids(hass, labels or []),
        area_id=area_id,
    )
    if state is not None:
        hass.states.async_set(entry.entity_id, state, attributes or {})
    return entry


def create_area(
    hass: HomeAssistant,
    name: str,
    *,
    labels: list[str] | None = None,
    floor_id: str | None = None,
) -> ar.AreaEntry:
    """Create an area with labels and an optional floor."""
    registry = ar.async_get(hass)
    area = registry.async_get_area_by_name(name) or registry.async_create(name)
    return registry.async_update(
        area.id,
        labels=label_ids(hass, labels or []),
        floor_id=floor_id,
    )


def create_floor(hass: HomeAssistant, name: str) -> fr.FloorEntry:
    """Create a floor."""
    registry = fr.async_get(hass)
    return registry.async_get_floor_by_name(name) or registry.async_create(name)


def set_sensor_labels(hass: HomeAssistant, entity_id: str, labels: list[str]) -> None:
    """Apply labels to an already-created entity (e.g. our own sensor)."""
    er.async_get(hass).async_update_entity(entity_id, labels=label_ids(hass, labels))

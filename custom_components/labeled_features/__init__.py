"""Labeled Features custom component.

Minimal config — all configuration is label-driven.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PLATFORMS
from .coordinator import (
    LabeledFeatureAreasCoordinator,
    LabeledFeaturesCoordinator,
)
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Set up Labeled Features from a config entry."""
    _LOGGER.info("Setting up Labeled Features integration")

    # Create coordinators
    features_coordinator = LabeledFeaturesCoordinator(hass)
    areas_coordinator = LabeledFeatureAreasCoordinator(hass)

    # Set up coordinators (register event listeners)
    await features_coordinator.async_setup()
    await areas_coordinator.async_setup()

    # Store in hass.data for sensor access
    if "labeled_features" not in hass.data:
        hass.data["labeled_features"] = {}
    hass.data["labeled_features"]["features_coordinator"] = features_coordinator
    hass.data["labeled_features"]["areas_coordinator"] = areas_coordinator

    # Set up services
    await async_setup_services(hass)

    # Forward platform setup
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )

    if unload_ok:
        features_coordinator = hass.data["labeled_features"]["features_coordinator"]
        areas_coordinator = hass.data["labeled_features"]["areas_coordinator"]

        await features_coordinator.async_shutdown()
        await areas_coordinator.async_shutdown()

        # Clean up hass.data
        if "labeled_features" in hass.data:
            del hass.data["labeled_features"]

    return unload_ok


async def async_remove_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove a config entry."""
    if "labeled_features" in hass.data:
        del hass.data["labeled_features"]

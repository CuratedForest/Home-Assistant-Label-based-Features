"""Labeled Features custom component.

Part 1: drop-in replacements for the two legacy trigger-based template
sensors (Labeled Features State, Labeled Feature Areas State) plus
internal error handling. All configuration is label-driven.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENABLED, DOMAIN, PLATFORMS
from .coordinator import (
    LabeledFeatureAreasCoordinator,
    LabeledFeaturesCoordinator,
)
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Labeled Features from a config entry."""
    features_coordinator = LabeledFeaturesCoordinator(hass, entry)
    areas_coordinator = LabeledFeatureAreasCoordinator(hass, entry)

    enabled = entry.options.get(CONF_ENABLED, True)
    features_coordinator.is_disabled = not enabled
    areas_coordinator.is_disabled = not enabled

    await features_coordinator.async_setup()
    await areas_coordinator.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "features_coordinator": features_coordinator,
        "areas_coordinator": areas_coordinator,
    }

    await async_setup_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply the enable/disable option without a reload."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data is None:
        return
    enabled = entry.options.get(CONF_ENABLED, True)
    data["features_coordinator"].is_disabled = not enabled
    data["areas_coordinator"].is_disabled = not enabled


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data is not None:
            await data["features_coordinator"].async_shutdown()
            await data["areas_coordinator"].async_shutdown()
        if not hass.data.get(DOMAIN):
            hass.data.pop(DOMAIN, None)
            await async_unload_services(hass)

    return unload_ok

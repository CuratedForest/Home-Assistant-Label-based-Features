"""The Labeled Features integration.

Native implementation of the state layer of the Label Based Features system:
the ``Labeled Features State`` and ``Labeled Feature Areas State`` sensors,
plus tiered error handling. Every downstream consumer (the Leaders/Areas
automations and the ``labeled_feature_*`` scripts) keeps working unchanged.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import LabeledFeaturesCoordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__package__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Labeled Features instance."""
    coordinator = LabeledFeaturesCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Entities restore their attributes into the coordinator during platform
    # setup, so subscriptions and the first reconcile must come afterwards.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start()

    async_setup_services(hass)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Labeled Features instance."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Leave the instance intact: HA keeps the entry loaded, so tearing the
        # coordinator down here would leave a live-but-gutted entry whose next
        # reload fails in the sensor platform.
        return False

    coordinator: LabeledFeaturesCoordinator | None = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id, None
    )
    if coordinator is not None:
        coordinator.async_shutdown()
    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)
        async_unload_services(hass)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the instance when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)

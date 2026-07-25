from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_FEATURE_PREFIX,
    CONF_INSTANCE_NAME,
    CONF_LEADER_LABEL,
    DEFAULT_FEATURE_PREFIX,
    DEFAULT_LEADER_LABEL,
    DOMAIN,
)
from .coordinator import LabeledFeaturesCoordinator
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    instance_name = entry.data[CONF_INSTANCE_NAME]
    leader_label = entry.data.get(CONF_LEADER_LABEL, DEFAULT_LEADER_LABEL)
    feature_prefix = entry.data.get(CONF_FEATURE_PREFIX, DEFAULT_FEATURE_PREFIX)

    coordinator = LabeledFeaturesCoordinator(
        hass=hass,
        entry_id=entry.entry_id,
        instance_name=instance_name,
        leader_label=leader_label,
        feature_prefix=feature_prefix,
    )

    await coordinator.async_setup()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: LabeledFeaturesCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        await async_unregister_services(hass)

    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

"""The Labeled Features integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DATA_ENTRIES,
    DATA_SERVICE_REGISTERED,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import (
    LabeledFeatureAreasStateCoordinator,
    LabeledFeaturesStateCoordinator,
)
from .error_handler import (
    async_register_service,
    async_unregister_service_if_last,
)
from .label_sync import async_sync_labels, async_unbind_managed_labels

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """YAML setup is not supported; config entries only."""

    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Labeled Features instance."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    entries = domain_data.setdefault(DATA_ENTRIES, {})

    features_coord = LabeledFeaturesStateCoordinator(hass, entry)
    areas_coord = LabeledFeatureAreasStateCoordinator(hass, entry)

    features_coord.async_subscribe()
    areas_coord.async_subscribe()

    # Let both first-refresh failures propagate. `async_config_entry_first_refresh`
    # raises `ConfigEntryNotReady` on `UpdateFailed`, and HA will retry setup
    # with backoff. Swallowing the exception here would leave the areas
    # coordinator with an empty `data` dict, which — combined with a
    # recorder-restored non-empty prior `label_map` — would cause
    # `automation.labeled_feature_areas` to diff every previously-known entry
    # as removed and retract every dispatched MQTT-discovery topic.
    await areas_coord.async_config_entry_first_refresh()
    await features_coord.async_config_entry_first_refresh()

    entries[entry.entry_id] = {
        "features": features_coord,
        "areas": areas_coord,
    }

    # Public service (idempotent across entries).
    if not domain_data.get(DATA_SERVICE_REGISTERED):
        async_register_service(hass)
        domain_data[DATA_SERVICE_REGISTERED] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # After the sensor platform finishes, its entity registry entry
    # exists — sync managed labels onto it.
    await async_sync_labels(hass, entry)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change so context is re-read."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down an entry cleanly."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    domain_data = hass.data.setdefault(DOMAIN, {})
    entries = domain_data.setdefault(DATA_ENTRIES, {})
    entry_data = entries.pop(entry.entry_id, None)
    if entry_data is not None:
        entry_data["features"].async_unsubscribe()
        entry_data["areas"].async_unsubscribe()

    async_unregister_service_if_last(hass, len(entries))
    if not entries:
        domain_data[DATA_SERVICE_REGISTERED] = False
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up managed labels when the entry is deleted."""

    await async_unbind_managed_labels(hass, entry)

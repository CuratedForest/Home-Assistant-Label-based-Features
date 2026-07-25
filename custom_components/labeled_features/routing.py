"""Instance routing for the global write events.

``labeled_feature_set`` and ``labeled_feature_snapshot_set`` are plain bus
events fired by the existing YAML scripts with no instance targeting. When more
than one instance is configured exactly one of them must consume an untargeted
event, otherwise a test instance would double-write production state.

Resolution order:

1. an explicit ``instance`` field in the payload (entry id or entry title),
2. the only configured instance,
3. ownership — the instance that leads (or already tracks) the target triple,
   or already holds the named snapshot, when exactly one instance matches,
4. the instance using the default entity slug prefix, when exactly one does.

If several instances own the payload (the common case while a test instance
shares the production leader label) the payload is **dropped with a warning**
rather than silently applied to whichever entry happens to be first. Guessing
here is how a production override ends up written only to a test instance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback

from .const import DEFAULT_PREFIX, DOMAIN

if TYPE_CHECKING:
    from .coordinator import LabeledFeaturesCoordinator

_LOGGER = logging.getLogger(__package__)


@callback
def async_coordinators(hass: HomeAssistant) -> list[LabeledFeaturesCoordinator]:
    """Return every loaded coordinator, oldest entry first."""
    store: dict[str, LabeledFeaturesCoordinator] = hass.data.get(DOMAIN, {})
    return list(store.values())


@callback
def async_coordinator_for_instance(
    hass: HomeAssistant, instance: str
) -> LabeledFeaturesCoordinator | None:
    """Resolve an explicit ``instance`` reference (entry id or title)."""
    for coordinator in async_coordinators(hass):
        if instance in (coordinator.entry.entry_id, coordinator.entry.title):
            return coordinator
    return None


@callback
def async_event_owner(
    hass: HomeAssistant, data: dict[str, Any], *, feature_event: bool
) -> LabeledFeaturesCoordinator | None:
    """Return the single coordinator that should consume this payload."""
    coordinators = async_coordinators(hass)
    if not coordinators:
        return None

    if instance := str(data.get("instance", "") or "").strip():
        owner = async_coordinator_for_instance(hass, instance)
        if owner is None:
            _LOGGER.warning(
                "Labeled Features: no instance matches %r; ignoring event", instance
            )
        return owner

    if len(coordinators) == 1:
        return coordinators[0]

    if feature_event:
        feature = str(data.get("target_feature", "") or "").strip()
        scope = str(data.get("scope", "") or "").strip().lower()
        scope_id = str(data.get("scope_id", "") or "")
        description = f"feature {feature!r} ({scope}/{scope_id})"
        matches = [
            coordinator
            for coordinator in coordinators
            if feature and coordinator.owns_triple(feature, scope, scope_id)
        ]
    else:
        snapshot_name = str(data.get("snapshot_name", "") or "").strip()
        description = f"snapshot {snapshot_name!r}"
        matches = [
            coordinator
            for coordinator in coordinators
            if snapshot_name and coordinator.owns_snapshot(snapshot_name)
        ]

    if len(matches) == 1:
        return matches[0]

    if not matches:
        # Nothing owns it yet (e.g. a manual-only feature). Prefer the instance
        # using the default slug prefix, which is the production one.
        default_prefix = [
            coordinator
            for coordinator in coordinators
            if coordinator.prefix == DEFAULT_PREFIX
        ]
        if len(default_prefix) == 1:
            return default_prefix[0]

    _LOGGER.warning(
        "Labeled Features: %d of %d instances match %s; ignoring the event. "
        "Add an `instance` field (config entry title or id) to target one, or "
        "remove the extra instance",
        len(matches),
        len(coordinators),
        description,
    )
    return None

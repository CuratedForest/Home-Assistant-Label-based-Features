"""Coordinator for sensor.labeled_feature_areas_state.

Ports the Jinja `label_map` template in `configuration.yaml` to Python.
Output is a dict keyed `"<scope_id>||<label>"` whose values are the
serialised form of `LabelMapEntry`. The value shape matches what
`automation.labeled_feature_areas` currently consumes so the automation
diff logic keeps working unchanged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_START
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..const import (
    AREA_MODIFIER_KEYWORDS,
    CONF_LEADER_LABEL,
    DEFAULT_LEADER_LABEL,
    DOMAIN,
    EVENT_AREA_REGISTRY_UPDATED,
    EVENT_FLOOR_REGISTRY_UPDATED,
    EVENT_LABEL_REGISTRY_UPDATED,
    SCOPE_PREFIX_RE_ALT,
    prefix_for_provides_scope,
)
from ..models import LabelMapEntry
from ..registry_helpers import area_labels, floor_of_area, label_areas

_LOGGER = logging.getLogger(__name__)

_PROVIDES_RE = re.compile(rf"^({SCOPE_PREFIX_RE_ALT})Provides: (.+)$")
_MODIFIER_RE = re.compile(
    r"^[^:]+ (?:" + "|".join(re.escape(k) for k in AREA_MODIFIER_KEYWORDS) + r"): "
)


@dataclass
class AreasCoordinatorContext:
    """Runtime configuration for the areas coordinator."""

    leader_label: str


class LabeledFeatureAreasStateCoordinator(
    DataUpdateCoordinator[dict[str, dict[str, Any]]]
):
    """Rebuilds the `label_map` on any registry event that could affect it."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_areas_state_{entry.entry_id}",
            update_method=self._compute,
            # Registry events fire in bursts during startup and on bulk
            # renames. Coalesce them so a burst produces a single
            # rebuild instead of one rebuild per event.
            request_refresh_debouncer=Debouncer(
                hass,
                _LOGGER,
                cooldown=0.3,
                immediate=False,
            ),
        )
        merged = {**entry.data, **entry.options}
        self.context = AreasCoordinatorContext(
            leader_label=(
                merged.get(CONF_LEADER_LABEL) or DEFAULT_LEADER_LABEL
            ).strip()
        )
        # Seed `data` so a downstream consumer never sees `None` if the
        # first refresh is delayed. The sensor's `extra_state_attributes`
        # falls back on `self._coordinator.data or {}`, but keeping the
        # attribute a real (empty) dict from the start is safer against
        # future callers that assume mapping-shaped `.data`.
        self.data = {}
        self._unsubs: list[callable] = []

    # ── Public wiring ───────────────────────────────────────────────────
    def async_subscribe(self) -> None:
        bus = self.hass.bus.async_listen
        self._unsubs.append(bus(EVENT_LABEL_REGISTRY_UPDATED, self._on_event))
        self._unsubs.append(bus(EVENT_AREA_REGISTRY_UPDATED, self._on_event))
        self._unsubs.append(bus(EVENT_FLOOR_REGISTRY_UPDATED, self._on_event))
        self._unsubs.append(bus(EVENT_HOMEASSISTANT_START, self._on_event))

    def async_unsubscribe(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _on_event(self, _event: Event) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    # ── Core compute ────────────────────────────────────────────────────
    async def _compute(self) -> dict[str, dict[str, Any]]:
        return self._compute_sync()

    def _compute_sync(self) -> dict[str, dict[str, Any]]:
        """Synchronous path so tests can drive it directly."""

        result: dict[str, dict[str, Any]] = {}
        seen: set[tuple[str, str]] = set()

        gated_areas = label_areas(self.hass, self.context.leader_label)

        for aid in gated_areas:
            floor_id = floor_of_area(self.hass, aid)
            area_lbls = area_labels(self.hass, aid)
            for lbl in area_lbls:
                match = _PROVIDES_RE.match(lbl)
                if match is None:
                    continue
                prefix = match.group(1).strip()
                lname = match.group(2).strip()
                if not lname:
                    continue
                if _MODIFIER_RE.match(lname):
                    # `Feature Component: X` etc. — skip, this is a
                    # modifier label, not a feature declaration.
                    continue

                if prefix == "Area":
                    scope = "area"
                    scope_id = aid
                elif prefix == "Floor":
                    scope = "floor"
                    scope_id = floor_id
                else:
                    scope = "none"
                    scope_id = aid

                if not scope_id:
                    # Floor-scoped label but the area has no floor —
                    # cannot resolve, skip.
                    continue

                key = (scope_id, lname)
                if key in seen:
                    # Dedupe (matches the template's per-scope_id
                    # collapse for Floor-scoped labels on multiple
                    # areas within the same floor).
                    continue
                seen.add(key)

                # Component override on the *same* area's labels.
                scope_prefix = prefix_for_provides_scope(scope)
                comp_prefix = f"{scope_prefix}Provides {lname} Component: "
                component = "select"
                for candidate in area_lbls:
                    if candidate.startswith(comp_prefix):
                        override = candidate[len(comp_prefix) :].strip()
                        if override:
                            component = override
                        break

                entry = LabelMapEntry(
                    scope_id=scope_id,
                    label=lname,
                    scope=scope,
                    component=component,
                    declaring_area_id=aid,
                )
                result[f"{scope_id}||{lname}"] = entry.to_dict()

        return result

    # ── Config-change helper ────────────────────────────────────────────
    def apply_context(self, entry: ConfigEntry) -> None:
        merged = {**entry.data, **entry.options}
        self.context = AreasCoordinatorContext(
            leader_label=(
                merged.get(CONF_LEADER_LABEL) or DEFAULT_LEADER_LABEL
            ).strip()
        )

    @property
    def leader_area_count(self) -> int:
        return len(label_areas(self.hass, self.context.leader_label))

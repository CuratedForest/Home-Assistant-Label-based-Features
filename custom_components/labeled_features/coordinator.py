from __future__ import annotations

import logging
import re
import time
from typing import Any

from homeassistant.core import Event, HomeAssistant, State, callback

from .const import (
    DEFAULT_FEATURE_PREFIX,
    EVENT_LABELED_FEATURE_SET,
    EVENT_LABELED_FEATURE_SNAPSHOT_SET,
    FEATURE_META,
    MODIFIER_KEYWORDS,
    SKIP_STATES,
    TRUTHY_STATES,
)

_LOGGER = logging.getLogger(__name__)

_PROVIDES_RE = re.compile(r"^(Area |Floor |)Provides: (.+)$")
_PROVIDES_COMPONENT_RE = re.compile(
    r"^(Area |Floor |)Provides (.+) Component: (.+)$"
)
_MODIFIER_RE = re.compile(
    r"^[^:]+ (Component|Min|Max|Step|Unit|Icon|Initial|Static|Mode|Device Class): "
)
_LEADER_LABEL_RE = re.compile(r"^(Area |Floor |)Leader: (.+)$")
_MODE_LABEL_RE = re.compile(
    r"^(Area |Floor |)(.+) Mode: (Leader|Any|All)$"
)
_ENABLE_RE = re.compile(r"^(Area |Floor |)(.+) Enable: (.+)$")
_DISABLE_RE = re.compile(r"^(Area |Floor |)(.+) Disable: (.+)$")
_INCREASING_RE = re.compile(r"^(Area |Floor |)(.+) Increasing: True$")
_DECREASING_RE = re.compile(r"^(Area |Floor |)(.+) Decreasing: True$")
_INVERT_RE = re.compile(r"^(Area |Floor |)(.+) Invert: True$")


class LabeledFeaturesCoordinator:
    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        instance_name: str,
        leader_label: str,
        feature_prefix: str,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.instance_name = instance_name
        self.leader_label = leader_label
        self.feature_prefix = feature_prefix or DEFAULT_FEATURE_PREFIX

        self._listeners: list = []
        self._unsubs: list = []

        self.feature_meta: dict = dict(FEATURE_META)
        self.leaders: dict[str, dict] = {}
        self.features: dict[str, dict] = {}
        self.snapshots: dict[str, dict] = {}
        self.label_map: dict[str, dict] = {}

    async def async_setup(self) -> None:
        self._rebuild_all()
        self._unsubs.append(
            self.hass.bus.async_listen(
                "state_changed", self._handle_state_change
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                "label_registry_updated", self._handle_registry_event
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                "area_registry_updated", self._handle_registry_event
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                "floor_registry_updated", self._handle_registry_event
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_LABELED_FEATURE_SET, self._handle_feature_set
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_LABELED_FEATURE_SNAPSHOT_SET, self._handle_snapshot_set
            )
        )

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def async_add_listener(self, listener: Any) -> Any:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def _notify_listeners(self) -> None:
        for listener in self._listeners:
            listener()

    # ── Registry helpers ─────────────────────────────────────────────

    def _get_label_registry(self):
        from homeassistant.helpers import label_registry as lr
        return lr.async_get(self.hass)

    def _get_area_registry(self):
        from homeassistant.helpers import area_registry as ar
        return ar.async_get(self.hass)

    def _get_floor_registry(self):
        from homeassistant.helpers import floor_registry as fr
        return fr.async_get(self.hass)

    def _get_entity_registry(self):
        from homeassistant.helpers import entity_registry as er
        return er.async_get(self.hass)

    def _all_label_ids(self) -> list[str]:
        reg = self._get_label_registry()
        return [entry.label_id for entry in reg.labels.values()] if reg else []

    def _label_name(self, label_id: str) -> str | None:
        reg = self._get_label_registry()
        if reg is None:
            return None
        entry = reg.async_get_label(label_id)
        return entry.name if entry else None

    def _label_entities(self, label_id: str) -> list[str]:
        ent_reg = self._get_entity_registry()
        if ent_reg is None:
            return []
        return [
            entry.entity_id
            for entry in ent_reg.entities.values()
            if label_id in (entry.labels or set())
        ]

    def _label_areas(self, label_id: str) -> list[str]:
        area_reg = self._get_area_registry()
        if area_reg is None:
            return []
        return [
            entry.id
            for entry in area_reg.areas.values()
            if label_id in (entry.labels or set())
        ]

    def _entity_labels(self, entity_id: str) -> list[str]:
        ent_reg = self._get_entity_registry()
        if ent_reg is None:
            return []
        entry = ent_reg.async_get(entity_id)
        if entry is None:
            return []
        return list(entry.labels or set())

    def _entity_label_names(self, entity_id: str) -> list[str]:
        label_ids = self._entity_labels(entity_id)
        names = []
        for lid in label_ids:
            n = self._label_name(lid)
            if n is not None:
                names.append(n)
        return names

    def _area_labels(self, area_id: str) -> list[str]:
        area_reg = self._get_area_registry()
        if area_reg is None:
            return []
        entry = area_reg.async_get_area(area_id)
        if entry is None:
            return []
        return list(entry.labels or set())

    def _area_label_names(self, area_id: str) -> list[str]:
        label_ids = self._area_labels(area_id)
        names = []
        for lid in label_ids:
            n = self._label_name(lid)
            if n is not None:
                names.append(n)
        return names

    def _area_id_for_entity(self, entity_id: str) -> str | None:
        ent_reg = self._get_entity_registry()
        if ent_reg is None:
            return None
        entry = ent_reg.async_get(entity_id)
        if entry is None or entry.area_id is None:
            from homeassistant.helpers import device_registry as dr
            dev_reg = dr.async_get(self.hass)
            if entry and entry.device_id:
                dev = dev_reg.async_get(entry.device_id)
                if dev and dev.area_id:
                    return dev.area_id
            return None
        return entry.area_id

    def _floor_id_for_area(self, area_id: str) -> str | None:
        area_reg = self._get_area_registry()
        if area_reg is None:
            return None
        entry = area_reg.async_get_area(area_id)
        if entry is None:
            return None
        return entry.floor_id

    def _floor_areas(self, floor_id: str) -> list[str]:
        area_reg = self._get_area_registry()
        if area_reg is None:
            return []
        return [
            entry.id
            for entry in area_reg.areas.values()
            if entry.floor_id == floor_id
        ]

    def _leader_entities(self) -> list[str]:
        return self._label_entities(self.leader_label)

    # ── State helpers ────────────────────────────────────────────────

    def _get_state(self, entity_id: str) -> State | None:
        return self.hass.states.get(entity_id)

    def _state_value(self, entity_id: str) -> str:
        st = self._get_state(entity_id)
        if st is None:
            return "unknown"
        domain = entity_id.split(".")[0]
        if domain == "event":
            return str(st.attributes.get("event_type", st.state))
        return st.state

    def _state_last_changed_timestamp(self, entity_id: str) -> float:
        st = self._get_state(entity_id)
        if st is None:
            return 0.0
        return st.last_changed.timestamp() if st.last_changed else time.time()

    # ── Rebuild orchestrator ─────────────────────────────────────────

    def _rebuild_all(self) -> None:
        self.label_map = self._build_label_map()
        self.leaders = self._build_leaders_full()
        self.features = self._build_features_full()
        self._notify_listeners()

    def _rebuild_on_state_change(self, changed_eid: str, new_state: State | None, old_state: State | None) -> None:
        all_leaders = self._leader_entities()
        if changed_eid not in all_leaders:
            return
        if old_state is None:
            return
        old_val = str(old_state.state).lower()
        if old_val in SKIP_STATES:
            return

        self._update_leader_on_change(changed_eid, new_state, old_state)
        self._update_features_on_change(changed_eid, new_state, old_state)
        self._notify_listeners()

    # ── Event handlers ───────────────────────────────────────────────

    @callback
    def _handle_state_change(self, event: Event) -> None:
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        self._rebuild_on_state_change(entity_id, new_state, old_state)

    @callback
    def _handle_registry_event(self, event: Event) -> None:
        self._rebuild_all()

    @callback
    def _handle_feature_set(self, event: Event) -> None:
        data = event.data
        target_feature = (data.get("target_feature") or "").strip()
        scope = (data.get("scope") or "").lower().strip()
        scope_id = str(data.get("scope_id", ""))
        enabled = bool(data.get("enabled", False))
        timestamp = float(data.get("timestamp", time.time()))

        if not target_feature or scope not in ("area", "floor", "global"):
            return

        existing_entry = (
            self.features.get(target_feature, {})
            .get(scope, {})
            .get(scope_id, {})
        )
        mode = existing_entry.get("mode", "leader")

        new_entry = {
            "enabled": enabled,
            "mode": mode,
            "last_changed_timestamp": timestamp,
            "triggering_leader": "",
        }

        if target_feature not in self.features:
            self.features[target_feature] = {}
        if scope not in self.features[target_feature]:
            self.features[target_feature][scope] = {}
        self.features[target_feature][scope][scope_id] = new_entry
        self._notify_listeners()

    @callback
    def _handle_snapshot_set(self, event: Event) -> None:
        data = event.data
        snapshot_name = (data.get("snapshot_name") or "").strip()
        payload = data.get("payload")

        if not snapshot_name:
            return

        self.snapshots.pop(snapshot_name, None)

        if isinstance(payload, dict) and len(payload) > 0:
            self.snapshots[snapshot_name] = payload

        self._notify_listeners()

    # ── Label map builder (area-based features) ──────────────────────

    def _build_label_map(self) -> dict[str, dict]:
        leader_label_id = self.leader_label
        gated_areas = self._label_areas(leader_label_id)

        scopes: dict[str, dict] = {}

        for aid in gated_areas:
            floor_id = self._floor_id_for_area(aid) or ""
            scopes[aid] = {
                "kind": "area",
                "floor_id": floor_id,
                "labels": {},
            }

        for aid in gated_areas:
            this_floor_id = scopes[aid]["floor_id"]
            area_lbls = self._area_label_names(aid)

            for lbl in area_lbls:
                m = _PROVIDES_RE.match(lbl)
                if not m:
                    continue

                prefix = m.group(1).strip()
                lname = m.group(2).strip()

                if not lname:
                    continue
                if _MODIFIER_RE.match(lname):
                    continue

                if prefix == "Area":
                    scope_val = "area"
                    scope_id_val = aid
                elif prefix == "Floor":
                    scope_val = "floor"
                    scope_id_val = this_floor_id
                else:
                    scope_val = "none"
                    scope_id_val = aid

                if not scope_id_val:
                    continue

                scope_prefix = ""
                if scope_val == "area":
                    scope_prefix = "Area "
                elif scope_val == "floor":
                    scope_prefix = "Floor "

                comp_override = ""
                comp_pattern = f"^{re.escape(scope_prefix)}Provides {re.escape(lname)} Component: .+$"
                for albl in area_lbls:
                    if re.match(comp_pattern, albl):
                        comp_override = re.sub(r"^.+: ", "", albl).strip()
                        break

                component = comp_override if comp_override else "select"

                lentry = {
                    "scope": scope_val,
                    "scope_id": scope_id_val,
                    "component": component,
                    "declaring_area_id": aid,
                }

                if scope_id_val not in scopes:
                    scopes[scope_id_val] = {
                        "kind": "floor",
                        "floor_id": scope_id_val,
                        "labels": {lname: lentry},
                    }
                elif lname not in scopes[scope_id_val].get("labels", {}):
                    if "labels" not in scopes[scope_id_val]:
                        scopes[scope_id_val]["labels"] = {}
                    scopes[scope_id_val]["labels"][lname] = lentry

        result: dict[str, dict] = {}
        for sid, sdat in scopes.items():
            for lname, ldat in sdat.get("labels", {}).items():
                key = f"{sid}||{lname}"
                result[key] = {
                    "scope_id": sid,
                    "label": lname,
                    "scope": ldat.get("scope", "area"),
                    "component": ldat.get("component"),
                    "declaring_area_id": ldat.get("declaring_area_id"),
                    "label_data": ldat,
                }

        return result

    # ── Leaders builder ──────────────────────────────────────────────

    def _build_leaders_full(self) -> dict[str, dict]:
        all_leaders = self._leader_entities()
        result: dict[str, dict] = {}
        for eid in all_leaders:
            st = self._state_value(eid)
            lct = self._state_last_changed_timestamp(eid)
            result[eid] = {
                "current_value": st,
                "previous_value": "",
                "last_changed_timestamp": lct,
            }
        return result

    def _update_leader_on_change(
        self, changed_eid: str, new_state: State | None, old_state: State | None
    ) -> None:
        all_leaders = self._leader_entities()

        new_leaders: dict[str, dict] = {}
        for eid, ldat in self.leaders.items():
            if eid in all_leaders and eid != changed_eid:
                new_leaders[eid] = ldat

        for eid in all_leaders:
            if eid not in new_leaders and eid != changed_eid:
                st = self._state_value(eid)
                lct = self._state_last_changed_timestamp(eid)
                new_leaders[eid] = {
                    "current_value": st,
                    "previous_value": "",
                    "last_changed_timestamp": lct,
                }

        if changed_eid in all_leaders and new_state is not None:
            domain = changed_eid.split(".")[0]
            if domain == "event":
                cv_raw = str(
                    new_state.attributes.get("event_type", new_state.state)
                )
            else:
                cv_raw = new_state.state

            is_skip = bool(
                re.search(r"_initial_press$", cv_raw)
                or cv_raw.lower() in SKIP_STATES
            )

            prev_l = self.leaders.get(changed_eid, {})
            if is_skip:
                cv = prev_l.get("current_value", cv_raw)
                cv_ts = prev_l.get(
                    "last_changed_timestamp",
                    new_state.last_changed.timestamp()
                    if new_state.last_changed
                    else time.time(),
                )
            else:
                cv = cv_raw
                cv_ts = (
                    new_state.last_changed.timestamp()
                    if new_state.last_changed
                    else time.time()
                )

            old_cv_l = prev_l.get("current_value", "")
            old_pv_l = prev_l.get("previous_value", "")
            prev_cv_l_raw = old_cv_l if cv != old_cv_l else old_pv_l
            if (
                re.search(r"_initial_press$", str(prev_cv_l_raw))
                or str(prev_cv_l_raw).lower() in SKIP_STATES
            ):
                prev_cv_l = ""
            else:
                prev_cv_l = prev_cv_l_raw

            new_leaders[changed_eid] = {
                "current_value": cv,
                "previous_value": prev_cv_l,
                "last_changed_timestamp": cv_ts,
            }

        self.leaders = new_leaders

    # ── Features builder ─────────────────────────────────────────────

    def _eval_leader(
        self,
        eid: str,
        scope_pfx: str,
        fname: str,
        cv: str,
        prev_cv: str,
    ) -> bool:
        lbls = self._entity_label_names(eid)
        st = self._state_value(eid)
        domain = eid.split(".")[0]

        inc_lbl = f"{scope_pfx}{fname} Increasing: True" in lbls
        dec_lbl = f"{scope_pfx}{fname} Decreasing: True" in lbls

        if inc_lbl or dec_lbl:
            try:
                cur_n = float(cv) if cv else None
            except (ValueError, TypeError):
                cur_n = None
            try:
                prev_n = float(prev_cv) if prev_cv else None
            except (ValueError, TypeError):
                prev_n = None
            has_mov = cur_n is not None and prev_n is not None
            is_inc = has_mov and cur_n > prev_n
            is_dec = has_mov and cur_n < prev_n
            base = (inc_lbl and is_inc) or (dec_lbl and is_dec)
        else:
            en_val = ""
            dis_val = ""
            for lbl in lbls:
                m = re.match(
                    rf"^{re.escape(scope_pfx)}{re.escape(fname)} Enable: (.+)$", lbl
                )
                if m:
                    en_val = m.group(1)
                m = re.match(
                    rf"^{re.escape(scope_pfx)}{re.escape(fname)} Disable: (.+)$", lbl
                )
                if m:
                    dis_val = m.group(1)

            if en_val or dis_val:
                by_en = en_val and st == en_val
                by_dis = dis_val and st == dis_val
                if en_val and dis_val:
                    base = by_en and not by_dis
                elif en_val:
                    base = bool(by_en)
                else:
                    base = not by_dis
            else:
                if domain in ("event", "button"):
                    base = True
                else:
                    base = (st == fname) or (st.lower() in TRUTHY_STATES)

        inverted = f"{scope_pfx}{fname} Invert: True" in lbls
        return (not base) if inverted else base

    def _build_triples(self, all_leaders: list[str]) -> dict[str, list[str]]:
        triples: dict[str, list[str]] = {}
        for eid in all_leaders:
            aid = self._area_id_for_entity(eid) or ""
            fid = ""
            if aid:
                fid = self._floor_id_for_area(aid) or ""

            lbls = self._entity_label_names(eid)
            for lbl in lbls:
                m = _LEADER_LABEL_RE.match(lbl)
                if not m:
                    continue
                prefix = m.group(1).strip()
                fname = m.group(2).strip()

                if prefix == "Area":
                    scope_val = "area"
                    scope_id_val = aid
                elif prefix == "Floor":
                    scope_val = "floor"
                    scope_id_val = fid
                else:
                    scope_val = "global"
                    scope_id_val = ""

                if scope_val == "area" and not scope_id_val:
                    continue
                if scope_val == "floor" and not scope_id_val:
                    continue

                key = f"{fname}||{scope_val}||{scope_id_val}"
                if key not in triples:
                    triples[key] = []
                if eid not in triples[key]:
                    triples[key].append(eid)

        return triples

    def _resolve_modes(
        self, triples: dict[str, list[str]]
    ) -> dict[str, str]:
        sensor_entity_id = f"sensor.{self.instance_name.lower().replace(' ', '_')}_labeled_features_state"
        sensor_labels = self._entity_label_names(sensor_entity_id)

        mode_for: dict[str, str] = {}
        for key in triples:
            parts = key.split("||")
            fname = parts[0]
            scope_val = parts[1]

            if scope_val == "area":
                scope_pfx = "Area "
            elif scope_val == "floor":
                scope_pfx = "Floor "
            else:
                scope_pfx = ""

            mode_val = "leader"
            pattern = re.compile(
                rf"^{re.escape(scope_pfx)}{re.escape(fname)} Mode: (Leader|Any|All)$"
            )
            for slbl in sensor_labels:
                if pattern.match(slbl):
                    mode_val = re.sub(r"^.+: ", "", slbl).lower()
                    break

            mode_for[key] = mode_val

        return mode_for

    def _build_features_full(self) -> dict[str, dict]:
        all_leaders = self._leader_entities()
        triples = self._build_triples(all_leaders)
        mode_for = self._resolve_modes(triples)

        result: dict[str, dict] = {}
        for key, leaders_list in triples.items():
            parts = key.split("||")
            fname = parts[0]
            scope_val = parts[1]
            scope_id_val = parts[2]

            scope_pfx = ""
            if scope_val == "area":
                scope_pfx = "Area "
            elif scope_val == "floor":
                scope_pfx = "Floor "

            mode = mode_for.get(key, "leader")

            leader_values: list[bool] = []
            for eid in leaders_list:
                ldat = self.leaders.get(eid, {})
                cv = ldat.get("current_value", "")
                prev_cv = ldat.get("previous_value", "")
                truth = self._eval_leader(eid, scope_pfx, fname, cv, prev_cv)
                leader_values.append(truth)

            if mode == "all":
                enabled = all(leader_values) if leader_values else False
            elif mode == "any":
                enabled = any(leader_values) if leader_values else False
            else:
                enabled = leader_values[0] if leader_values else False

            triggering_leader = leaders_list[0] if leaders_list else ""
            ts = time.time()

            if fname not in result:
                result[fname] = {}
            if scope_val not in result[fname]:
                result[fname][scope_val] = {}
            result[fname][scope_val][scope_id_val] = {
                "enabled": enabled,
                "mode": mode,
                "last_changed_timestamp": ts,
                "triggering_leader": triggering_leader,
            }

        return result

    def _update_features_on_change(
        self, changed_eid: str, new_state: State | None, old_state: State | None
    ) -> None:
        all_leaders = self._leader_entities()
        if changed_eid not in all_leaders:
            return

        triples = self._build_triples(all_leaders)
        mode_for = self._resolve_modes(triples)

        result: dict[str, dict] = {}

        for fname, scopes_map in self.features.items():
            if not isinstance(scopes_map, dict):
                continue
            for scope_val, sids in scopes_map.items():
                if not isinstance(sids, dict):
                    continue
                for scope_id_val, entry in sids.items():
                    if not isinstance(entry, dict):
                        continue
                    key = f"{fname}||{scope_val}||{scope_id_val}"
                    has_leader = key in triples
                    is_manual = entry.get("triggering_leader", "") == ""
                    if has_leader or is_manual:
                        if fname not in result:
                            result[fname] = {}
                        if scope_val not in result[fname]:
                            result[fname][scope_val] = {}
                        result[fname][scope_val][scope_id_val] = entry

        if new_state is not None:
            domain = changed_eid.split(".")[0]
            if domain == "event":
                cv_raw = str(
                    new_state.attributes.get("event_type", new_state.state)
                )
            else:
                cv_raw = new_state.state

            is_skip = bool(
                re.search(r"_initial_press$", cv_raw)
                or cv_raw.lower() in SKIP_STATES
            )

            if not is_skip:
                ts = (
                    new_state.last_changed.timestamp()
                    if new_state.last_changed
                    else time.time()
                )
                prev_l = self.leaders.get(changed_eid, {})
                prev_cv = prev_l.get("previous_value", "")

                for key, leaders_list in triples.items():
                    if changed_eid not in leaders_list:
                        continue

                    parts = key.split("||")
                    fname = parts[0]
                    scope_val = parts[1]
                    scope_id_val = parts[2]

                    scope_pfx = ""
                    if scope_val == "area":
                        scope_pfx = "Area "
                    elif scope_val == "floor":
                        scope_pfx = "Floor "

                    mode = mode_for.get(key, "leader")

                    this_truth = self._eval_leader(
                        changed_eid, scope_pfx, fname, cv_raw, prev_cv
                    )

                    if mode == "leader":
                        new_enabled = this_truth
                    else:
                        lns: list[bool] = []
                        for other_eid in leaders_list:
                            if other_eid == changed_eid:
                                lns.append(this_truth)
                            else:
                                other_leader = self.leaders.get(other_eid, {})
                                other_cv = other_leader.get("current_value", "")
                                other_prev = other_leader.get("previous_value", "")
                                other_truth = self._eval_leader(
                                    other_eid, scope_pfx, fname, other_cv, other_prev
                                )
                                lns.append(other_truth)
                        if mode == "all":
                            new_enabled = all(lns) if lns else False
                        else:
                            new_enabled = any(lns) if lns else False

                    existing_entry = (
                        result.get(fname, {})
                        .get(scope_val, {})
                        .get(scope_id_val, {})
                    )
                    prev_enabled = existing_entry.get("enabled")
                    prev_ts = existing_entry.get("last_changed_timestamp", ts)

                    leader_dom = changed_eid.split(".")[0]
                    is_button_leader = leader_dom in ("event", "button")
                    flipped = (
                        prev_enabled is None
                        or prev_enabled != new_enabled
                        or is_button_leader
                    )
                    new_ts = ts if flipped else prev_ts

                    new_entry = {
                        "enabled": new_enabled,
                        "mode": mode,
                        "last_changed_timestamp": new_ts,
                        "triggering_leader": changed_eid,
                    }

                    if fname not in result:
                        result[fname] = {}
                    if scope_val not in result[fname]:
                        result[fname][scope_val] = {}
                    result[fname][scope_val][scope_id_val] = new_entry

        self.features = result

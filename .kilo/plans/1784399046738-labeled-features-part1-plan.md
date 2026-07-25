# Labeled Features Custom Component — Part 1 Plan

**Scope:** Replace two production template sensors with native sensors inside a `labeled_features` custom component, plus integrated error handling. This is Part 1 of a multi-part conversion; the automations and scripts remain YAML for now.

## Goal

Produce `custom_components/labeled_features/` that creates:

1. **`sensor.labeled_features_state`** — byte-compatible replacement for the trigger-based template sensor. State = count of leader entities. Attributes: `feature_meta`, `leaders`, `features`, `snapshots`.
2. **`sensor.labeled_feature_areas_state`** — byte-compatible replacement for the area state template sensor. State = count of areas with `feature_leader` label. Attribute: `label_map`.
3. **Error handling** — tiered error mode (`silent`/`log`/`alert`/`stop`) integrated throughout the coordinator, with a `labeled_features.error_mode` service for external callers.

All label-driven. No `configuration.yaml`. Config flow only.

## Constraints & Design Decisions

| Decision | Rationale |
|----------|-----------|
| Domain: `labeled_features` | Matches existing work, user-specified name |
| Config flow only, no YAML | User requirement; labels are primary config surface |
| Multi-instance with entity ID suffix | Allows `_dev` instance for side-by-side validation against template sensors. Each instance maintains independent state. |
| Byte-compatible attributes | Downstream automations and scripts diff these attributes. Shape must match exactly. |
| Event-driven (no polling) | Coordinator listens to registry events + state_changed + custom events. No `update_interval`. |
| `entry.runtime_data` | Modern pattern (HA 2024.1+). Typed `ConfigEntry[Coordinator]`. |
| `config_entry=entry` on coordinator | Required since HA 2025.11. Min version: 2025.11+. |
| `iot_class: "calculated"` | No external communication — all data from HA registries + state. |
| Start fresh | Don't build on existing partial code; structural issues warrant clean implementation. |

## Data Flow

```
Registry events (label/area/floor) ─┐
                                     │
state_changed (gated)              ──┼──► Coordinator
                                     │
labeled_feature_set event          ──┤
                                     │
labeled_feature_snapshot_set event ──┘
                                          │
                                    _build_all() / _update_leader_state()
                                          │
                            ┌─────────────┴─────────────┐
                            ▼                           ▼
              leaders + features + snapshots      label_map
                            │                           │
                            ▼                           ▼
              sensor.labeled_features_state      sensor.labeled_feature_areas_state
              (extra_state_attributes)           (extra_state_attributes)
```

## Failure Modes

| Failure | Handling |
|---------|----------|
| Label registry returns None for label ID | Skip label, log via error mode |
| Entity has no area/floor when scope requires it | Skip triple, report via error mode |
| `state_changed` event for unknown entity | Gate rejects (not in `feature_leader` label) |
| Corrupt legacy `leaders`/`features`/`snapshots` on restore | Coerce to `{}`, rebuild on next tick |
| Error mode `stop` during coordinator update | Log + create Repair issue; do NOT abort the update (other leaders/labels still process) |
| `script.send_alert` doesn't exist | Fallback to `persistent_notification.create` |

## File Structure

```
custom_components/labeled_features/
├── manifest.json              # Metadata, iot_class: calculated
├── __init__.py                # Setup/unload, typed ConfigEntry, event listeners
├── const.py                   # DOMAIN, FEATURE_META, label constants, error modes
├── coordinator.py             # LabeledFeaturesCoordinator — core logic
├── sensor.py                  # Two sensor entities
├── config_flow.py             # Config + Options + Reconfigure flows
├── error_mode.py              # ErrorModeHandler + service
├── services.py                # labeled_feature_set + labeled_feature_snapshot_set services
├── services.yaml              # Service schema definitions
├── strings.json               # Config flow UI strings
└── translations/
    └── en.json                # English translations
```

## Implementation Tasks

### 1. `manifest.json`

- Set `iot_class` to `"calculated"` (no external communication)
- Add `integration_type: "service"` (background service with sensors)
- Keep `config_flow: true`
- Version `1.0.0`

### 2. `const.py`

- `DOMAIN = "labeled_features"`
- `FEATURE_META` — static catalog copied from template sensor (Media Toggle/Play/Pause/Next/Previous/Seek Back/Seek Forward, Volume Up/Down, Lights On/Off/Up/Down, Fan On/Off/Up/Down)
- Error mode constants: `ERROR_MODE_SILENT/LOG/ALERT/STOP`, `DEFAULT_ERROR_MODE = "log"`
- Label constants: `LABEL_FEATURE_LEADER = "Feature Leader"`
- Event types: `EVENT_LABELED_FEATURE_SET`, `EVENT_LABELED_FEATURE_SNAPSHOT_SET`
- State gate constants: `STATE_UNAVAILABLE`, `STATE_TRUTHY`, `BUTTON_DOMAINS`
- Feature modes: `MODE_LEADER/ANY/ALL`
- Scope values: `SCOPE_AREA/FLOOR/GLOBAL`
- Config entry keys: `CONF_DEFAULT_ERROR_MODE`, `CONF_ALERT_ACTION`

### 3. `coordinator.py` — Core Logic

**Class:** `LabeledFeaturesCoordinator(DataUpdateCoordinator[dict])`

**Constructor:**
```python
def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
    super().__init__(
        hass, _LOGGER, name=DOMAIN, config_entry=entry
    )
    self._entry = entry
    self._listeners: list[Callable[[], None]] = []
    self._features: dict[str, Any] = {}
    self._label_map: dict[str, Any] = {}
    self._snapshots: dict[str, Any] = {}
    self._leaders: dict[str, Any] = {}
```

**`async_setup()` — Register listeners:**
- `label_registry_updated` → `_on_registry_changed`
- `area_registry_updated` → `_on_registry_changed`
- `floor_registry_updated` → `_on_registry_changed`
- `entity_registry_updated` → `_on_registry_changed` (for label assignments on entities)
- `state_changed` → `_on_state_changed` (gated — see below)
- `labeled_feature_set` → `_on_labeled_feature_set`
- `labeled_feature_snapshot_set` → `_on_labeled_feature_snapshot_set`
- `homeassistant_start` → `_on_homeassistant_start` (reconcile label_map on boot)

After registering listeners, call `_build_all()` then `self.async_set_updated_data()`.

**State change gate (CRITICAL):**
The `state_changed` event is a firehose. The gate must match the template sensor's logic exactly:

```python
@callback
def _on_state_changed(self, event: Event) -> None:
    eid = event.data.get("entity_id", "")
    if not eid:
        return
    # Check entity carries feature_leader label
    if not self._is_feature_leader(eid):
        # Also check if OLD attributes carried an entry (label removal cleanup)
        old_state = event.data.get("old_state")
        if eid not in self._leaders:
            return
    old_state = event.data.get("old_state")
    # Reject boot-restore noise
    if old_state is None:
        return
    old_str = str(getattr(old_state, "state", "")).lower()
    if old_str in STATE_UNAVAILABLE:
        return
    # Process the change
    self._update_leader_state(eid, event.data.get("new_state"))
    self._rebuild_features(event.data)
    self.async_set_updated_data()
```

**Leader evaluation (`_eval_leader`):**
Matches the template sensor's `eval_leader` macro exactly:
1. Check `Increasing: True` / `Decreasing: True` labels (direction takes precedence)
2. Check `Enable: <value>` / `Disable: <value>` labels
3. Default truth: `state == feature_name` OR `state.lower() in STATE_TRUTHY`
4. `event`/`button` domains always evaluate to `True`
5. Apply `Invert: True` last

**Feature rebuild (`_rebuild_features`):**
1. Build triple map: `(feature, scope, scope_id)` → `[leader_entity_ids]`
2. Resolve modes from labels on the sensor entity itself (`<pfx><F> Mode: Leader|Any|All`)
3. On `state_changed`: carry through existing entries, rebuild changed leader's triples
4. On `labeled_feature_set`: write manual override with `triggering_leader: ""`
5. Drop orphans (no leader mapped, not manual override)
6. Timestamp bump logic: bump when `enabled` flips OR when leader is button/event domain

**Label map rebuild (`_rebuild_label_map`):**
1. Find areas with `feature_leader` label
2. For each gated area, parse `(Area |Floor |)Provides: <Label>` labels
3. Skip modifier labels (`Provides <F> Component:`, `Min:`, `Max:`, etc.)
4. Resolve `Component:` override from sibling labels
5. Flatten to `<scope_id>||<label>` → `{scope_id, label, scope, component, declaring_area_id, label_data}`

**Label resolution helpers:**
- `_is_feature_leader(entity_id)` → check entity registry entry labels
- `_get_entity_label_names(entity_id)` → resolve label IDs to names from entity registry
- `_get_area_label_names(area_id)` → resolve label IDs to names from area registry
- `_get_area_id(entity_id)` → from entity registry
- `_get_floor_id_for_area(area_id)` → from area registry
- `_resolve_label_entities(label_name)` → iterate entity registry, collect matching entity_ids
- `_resolve_label_areas(label_name)` → collect area_ids where entities carry the label

**Restart persistence:**
On `homeassistant_start`, call `_rebuild_label_map()` to reconcile against live registries. The `leaders`/`features`/`snapshots` dicts are rebuilt from scratch on first tick (they're transient state derived from labels + entity states).

**`async_unload()` — Clean up:**
```python
@callback
def async_unload(self) -> None:
    for listener in self._listeners:
        listener()
    self._listeners.clear()
```

### 4. `sensor.py` — Two Sensor Entities

**`LabeledFeaturesStateSensor`:**
- `_attr_unique_id = "labeled_features_state"`
- `_attr_name = "Labeled Features State"`
- `_attr_state_class = SensorStateClass.MEASUREMENT`
- `_attr_native_unit_of_measurement = "leaders"`
- `native_value` → `len(coordinator._leaders)`
- `extra_state_attributes` → `{feature_meta, leaders, features, snapshots}`

**`LabeledFeatureAreasStateSensor`:**
- `_attr_unique_id = "labeled_feature_areas_state"`
- `_attr_name = "Labeled Feature Areas State"`
- `_attr_state_class = SensorStateClass.MEASUREMENT`
- `_attr_native_unit_of_measurement = "areas"`
- `native_value` → count of unique area_ids in `label_map`
- `extra_state_attributes` → `{label_map}`

Both sensors use `available` → `coordinator.last_update_success`.

### 5. `config_flow.py`

**Config flow:**
- `async_step_user`: Show form with `default_error_mode` (select: silent/log/alert/stop, default "log") and `alert_action` (text, default "script.send_alert")
- Singleton: abort if entry already exists (`self._async_abort_entries_match({})`)

**Options flow:**
- Edit `default_error_mode` and `alert_action`
- Triggers reload on change

**Reconfigure flow:**
- Same as options (for HA 2024.10+ reconfigure UI path)

### 6. `error_mode.py`

**`ErrorModeHandler`:**
- Constructor takes `default_mode` and `alert_action` from config entry
- `async_handle(message, mode=None, source="Labeled Feature", severity="medium")` → returns `"stop"` if mode is STOP, else `None`
- Tiers:
  - `silent` → no-op
  - `log` → `_LOGGER.warning("[%s] %s", source, message)`
  - `alert` → call `alert_action` service with `alert_severity`/`alert_title`/`alert_message`; fallback to `persistent_notification.create`
  - `stop` → `_LOGGER.error()` + return `"stop"` (caller decides whether to halt)

**Service registration:**
- `labeled_features.error_mode` → schema: `error_mode` (required, select), `message` (required, string), `source` (optional, string, default "Labeled Feature"), `severity` (optional, select: low/medium/high, default "medium")

### 7. `services.py`

- `labeled_feature_set` → fires `labeled_feature_set` event with `{target_feature, scope, scope_id, enabled, timestamp}`
- `labeled_feature_snapshot_set` → fires `labeled_feature_snapshot_set` event with `{snapshot_name, payload, timestamp}`
- Both services use voluptuous schema validation

### 8. `services.yaml`

Define service schemas for the UI:
```yaml
labeled_feature_set:
  fields:
    target_feature:
      required: true
      selector: text
    scope:
      required: true
      selector:
        select:
          options:
            - area
            - floor
            - global
    scope_id:
      required: false
      selector: text
    enabled:
      required: true
      selector: boolean
labeled_feature_snapshot_set:
  fields:
    snapshot_name:
      required: true
      selector: text
    payload:
      required: true
      selector: object
error_mode:
  fields:
    error_mode:
      required: true
      selector:
        select:
          options:
            - silent
            - log
            - alert
            - stop
    message:
      required: true
      selector: text
    source:
      required: false
      selector: text
    severity:
      required: false
      selector:
        select:
          options:
            - low
            - medium
            - high
```

### 9. `__init__.py`

- Typed `ConfigEntry[LabeledFeaturesCoordinator]`
- `async_setup_entry`: create coordinator, `await coordinator.async_setup()`, store in `entry.runtime_data`, forward to `[Platform.SENSOR]`, register services
- `async_unload_entry`: `coordinator.async_unload()`, unload platforms, unregister services
- Options update listener → reload entry

### 10. `strings.json` + `translations/en.json`

Config flow strings for `default_error_mode`, `alert_action`, options flow, reconfigure flow.

## Validation Plan

1. **Side-by-side comparison:** Install component alongside template sensors (use a dev HA instance). Compare `features`, `leaders`, `label_map`, `snapshots` attributes after:
   - Leader state flips
   - Button presses (event domain)
   - Direction labels (Increasing/Decreasing)
   - Invert labels
   - Any/All mode resolution
   - Manual Set Feature
   - Snapshot round-trips
   - HA restart
   - Label removal from entity
   - Area label changes

2. **Downstream compatibility:** Verify `automation.labeled_feature_leaders` and `automation.labeled_feature_areas` still fire correctly when pointing at the new sensors.

3. **Error mode tiers:** Trigger each tier (silent/log/alert/stop) and verify behavior.

## Resolved Design Decisions

1. **HA minimum version: 2025.11+** — Required for `config_entry=entry` on `DataUpdateCoordinator`. Update `hacs.json` accordingly.

2. **Start fresh** — Don't build on existing partial code. Existing code has structural issues (data property override, wrong label resolution, missing gate logic) that are easier to fix from scratch.

3. **Entity ID stability** — Component sensors use `unique_id: labeled_features_state` and `unique_id: labeled_feature_areas_state` (matching template sensors). HA preserves entity IDs across migration. Existing automations/scripts referencing `sensor.labeled_features_state` continue working.

4. **Multi-instance with suffix** — Config flow accepts optional `entity_id_suffix` (e.g. `_dev`). Suffix appends to unique_id and entity name. Production instance uses empty suffix. Each instance maintains independent coordinator state.

5. **Config flow fields** — `default_error_mode` (select: silent/log/alert/stop, default "log"), `alert_action` (text, default "script.send_alert"), `entity_id_suffix` (text, optional, default "").

## Risks

- **Label registry API:** The Python API for resolving label names from label IDs needs to be verified against the user's HA version. The `label_registry` module is relatively new and may have changed.
- **State change event firehose:** Even with the gate, the `state_changed` listener fires for EVERY entity state change. The gate filters quickly, but under heavy load this could add overhead. Mitigation: the gate is a simple dict lookup + string comparison.
- **Attribute size:** The `features` attribute can grow large with many leaders × features × scopes. HA has no hard limit on attribute size, but very large attributes slow down the recorder. The template sensor has the same limitation — this is a known trade-off.
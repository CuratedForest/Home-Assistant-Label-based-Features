# Labeled Features Custom Component — Part 1

Rewrite `custom_components/labeled_features` from scratch to own the two
production template sensors plus a shared error handler. Existing scripts and
automations in `/home/coder/HomeAssistant/` continue to reference the entities
by their historical IDs and continue to call `script.labeled_feature_error_mode`
unchanged; nothing outside the component is edited in this pass.

## Scope for this PR

In scope:

1. `sensor.labeled_features_state` — replaces the trigger-based template sensor
   in `configuration.yaml` lines ~189–693. Same attributes: `feature_meta`,
   `leaders`, `features`, `snapshots`. Same events and same input filtering.
2. `sensor.labeled_feature_areas_state` — replaces the trigger-based template
   sensor in `configuration.yaml` lines ~24–187. Same single public attribute:
   `label_map` keyed `"<scope_id>||<label>"`.
3. Component-internal error handler mirroring the four tiers of
   `script.labeled_feature_error_mode` and a public
   `labeled_features.report_error` service.
4. Config flow + options flow (instance name, leader label, sensor-wide
   defaults, entity_id overrides).
5. Multi-instance support (prod + test side-by-side).
6. Unit tests via `pytest-homeassistant-custom-component`.

Out of scope (later PRs): moving automations / scripts into Python. Downstream
scripts still call `script.labeled_feature_error_mode`. The leaders /
areas / follower / generics / somrig / styrbar / symfonisk / area / entities
/ sleep-timeout / button scripts stay in `scripts.yaml` and `automations.yaml`.

Also out of scope for this pass: any code inside
`/home/coder/HomeAssistant/custom_components/` (user asked us to ignore) and
the current `custom_components/labeled_features/` tree in this repo (rewrite
entirely, do not consult).

## Design decisions (resolved)

| Decision                              | Answer                                                                                                                                                                                                                                                                                                                    |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Config-flow surface for sensor labels | **Sensor-wide defaults only.** Fields: instance name, leader label, `Script Call Mode` default, `Error Mode` default, entity_id override for each of the two sensors. Per-feature `<Scoped F> Mode:` / `<Scoped F> Script Call Mode:` overrides continue to live as labels on the sensor entity, resolved at render time. |
| Per-instance leader identification    | **Configurable leader label**, default `feature_leader`. Two instances → two different labels, disjoint entity/area sets.                                                                                                                                                                                                 |
| Entity IDs                            | **Fully user-configurable per instance**, defaulted to the legacy IDs (`sensor.labeled_features_state`, `sensor.labeled_feature_areas_state`) so instance 1 is a drop-in replacement.                                                                                                                                     |
| Cross-instance references             | Existing automations/scripts reference the legacy IDs and continue to work against instance 1. Test instance is isolated by a different leader label + different entity IDs.                                                                                                                                              |
| Error handling exposure               | Python helper + a public HA service `labeled_features.report_error` mirroring the four tiers. Existing scripts still call `script.labeled_feature_error_mode`.                                                                                                                                                            |
| Update model                          | Two `DataUpdateCoordinator`s per instance. Refreshes are event-driven via `hass.bus.async_listen`, subscribing to exactly the events the template sensors watched. No polling.                                                                                                                                            |
| Persistence                           | `LabeledFeaturesState` inherits `RestoreEntity`. On restart it restores `leaders`, `features`, and `snapshots` from `extra_restore_state_data`. `feature_meta` is code-owned and rebuilt every boot.                                                                                                                      |
| Defaults exposed to downstream        | Component synchronizes the configured Script Call Mode / Error Mode defaults into labels on the sensor entity via the label/label-map registries so `labels('sensor.labeled_features_state')` in existing scripts keeps returning them. Only the two managed keys are written; user-placed labels are left alone.        |
| Testing                               | `pytest-homeassistant-custom-component` unit tests for config flow, both coordinators, error handler, and event integration. `hassfest` + Ruff in CI/Makefile.                                                                                                                                                            |

## Deliverables

Package layout under `custom_components/labeled_features/`:

```
custom_components/labeled_features/
  __init__.py                     # setup_entry / unload_entry, wire coordinators, register service, sync labels
  manifest.json                   # domain=labeled_features, config_flow: true, iot_class: local_push, dependencies: []
  const.py                        # DOMAIN, CONF_*, DEFAULT_*, event names, label keys
  config_flow.py                  # ConfigFlow + OptionsFlowHandler
  strings.json                    # config-flow labels & descriptions
  translations/en.json            # matches strings.json
  services.yaml                   # labeled_features.report_error service schema
  error_handler.py                # 4-tier Python helper + service registration
  label_sync.py                   # write/refresh managed labels on the sensor entity
  coordinator/
    __init__.py
    features.py                   # LabeledFeaturesStateCoordinator
    areas.py                      # LabeledFeatureAreasStateCoordinator
  sensor.py                       # LabeledFeaturesStateSensor (RestoreEntity), LabeledFeatureAreasStateSensor
  models.py                       # dataclasses: LeaderEntry, FeatureEntry, LabelMapEntry, Triple, EvalResult
tests/
  conftest.py
  test_config_flow.py
  test_coordinator_features.py    # golden-path scenarios per docs
  test_coordinator_areas.py       # label_map, component overrides, scope resolution
  test_error_handler.py           # 4 tiers + service call
  test_restore.py                 # snapshots/features/leaders survive restart
  fixtures/                       # small area/label/entity registry snapshots
Makefile / pyproject-adjacent script for `hassfest` + `ruff` + `pytest`.
```

The current `custom_components/labeled_features/` tree is removed in the first
task and does not inform the new layout.

## Data model (sensor.labeled_features_state)

Match the existing template sensor byte-for-byte on the attribute shape so
downstream scripts and substitutions keep working.

**State**: integer count of entities carrying the configured leader label
(`unit_of_measurement: leaders`, `state_class: measurement`).

**Attributes**:

- `feature_meta` — static dict, exact same 17 entries currently in
  `configuration.yaml` (Media Toggle/Play/Pause/Next/Previous/Seek
  Back/Seek Forward, Volume Up/Down, Lights On/Off/Up/Down, Fan
  On/Off/Up/Down). Each value: `{domain, kind, domain_label}`. Code-owned.
- `leaders` — `{entity_id: {current_value, previous_value,
  last_changed_timestamp}}`. `previous_value` only advances when
  `current_value` actually changes. Skip logic (`_initial_press`,
  unknown/unavailable/none) matches the template.
- `features` — nested `{feature: {scope: {scope_id: {enabled, mode,
  last_changed_timestamp, triggering_leader}}}}`. `scope` ∈
  `area|floor|global`. `last_changed_timestamp` bumps when `enabled` flips
  or when the triggering leader is on the `event`/`button` domain (every
  accepted press is a distinct "user did the thing" tick). Orphan drop:
  entries with no mapped leader and empty `triggering_leader` are dropped
  on the next tick; manual entries (`triggering_leader: ''`) are exempt.
- `snapshots` — `{snapshot_name: <arbitrary mapping>}`. Written via
  `labeled_feature_snapshot_set` event; empty-payload = delete.

## Event surface (both directions)

Subscribed events (per instance):

| Event                             | Trigger for                          | Filter                                                                                                                                                                              |
| --------------------------------- | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `state_changed`                   | `labeled_features_state` coordinator | Only when `entity_id` is in `label_entities(<configured_leader_label>)` AND `old_state` is not `unknown`/`unavailable`/`none`. Mirrors the `conditions:` block in configuration.yaml. |
| `labeled_feature_set`             | `labeled_features_state` coordinator | Manual override; always processed.                                                                                                                                                  |
| `labeled_feature_snapshot_set`    | `labeled_features_state` coordinator | Snapshot write/delete; always processed.                                                                                                                                            |
| `label_registry_updated`          | `labeled_feature_areas_state` coordinator | Always processed. Also triggers `labeled_features_state` because the set of gated leaders may have changed. |
| `area_registry_updated`           | `labeled_feature_areas_state` coordinator | Always processed.                                                                                                                                                                   |
| `floor_registry_updated`          | `labeled_feature_areas_state` coordinator | Always processed.                                                                                                                                                                   |
| `homeassistant_start` (via `EVENT_HOMEASSISTANT_START`) | Both coordinators                    | Publishes the current label_map (idempotent MQTT-discovery re-publish path in existing automation).                                                                                 |

Emitted: none new. Existing external events (`labeled_feature_set`,
`labeled_feature_snapshot_set`) are unchanged — the component only reads them.

## Coordinator: LabeledFeaturesStateCoordinator

`DataUpdateCoordinator[LabeledFeaturesStateData]` where the data-class carries
`feature_meta`, `leaders`, `features`, `snapshots`.

Public methods:

- `handle_state_changed(event)` — refresh for one leader.
- `handle_manual_override(event)` — merge `labeled_feature_set` payload.
- `handle_snapshot_set(event)` — merge/delete `labeled_feature_snapshot_set`.
- `handle_registry_updated(event)` — force full re-eval (label/area/floor).

Each handler mutates the in-memory data-class and calls
`async_set_updated_data(new)`. No `async_update_data` polling function.

Internal Python re-implementation of the Jinja logic, ported one-to-one:

1. **`_build_triple_index()`**: iterate `label_entities(<leader_label>)`; for
   each, parse `(Area|Floor|)Leader: <F>` labels; resolve area_id / floor_id
   from the entity's device/area registry; build
   `{(feature, scope, scope_id): [leader_entity_ids]}`.
2. **`_resolve_mode(triple)`**: read `<Scoped F> Mode: (Leader|Any|All)` from
   the sensor entity's labels; default `leader`. Sensor label lookups go
   through the label registry, not the state machine.
3. **`_eval_leader(entity_id, feature, scope_prefix, current_value,
   previous_value)`**: port of the `eval_leader` macro. Direction
   (Increasing/Decreasing) → Enable/Disable → default truth (`state == fname`
   OR truthy list `on/true/home/open/detected/active/unlocked` OR
   button/event domain = always true) → Invert. Same order as the template.
4. **`_rebuild_leader(entity_id, event)`**: update the entity's entry in
   `leaders` (respecting the `_initial_press` / unknown skip); for each
   triple the leader participates in, recompute `enabled` per the mode
   (`leader` → this leader's value; `any` / `all` → fold across the current
   value of every leader mapped to the triple).
5. **`_orphan_drop()`**: after a rebuild, iterate `features`; drop entries
   with no mapped triple AND `triggering_leader != ''`.
6. **`_apply_manual_override(event)`**: write the payload into
   `features[target_feature][scope][scope_id]` preserving `mode`, setting
   `triggering_leader = ''`.
7. **`_apply_snapshot(event)`**: merge into `snapshots[<snapshot_name>]`;
   empty mapping deletes.

## Coordinator: LabeledFeatureAreasStateCoordinator

Simpler: `data` is a `dict[str, LabelMapEntry]` keyed `"<scope_id>||<label>"`.

`_build_label_map()`:

1. `label_areas(<leader_label>)` → gated area set (Pass 1). Each area's
   `floor_id` is looked up once via `floor_areas()` iteration.
2. For each gated area, iterate `labels(area_id)`; match against the regex
   `^(Area |Floor |)Provides: (.+)$`. Skip modifier labels
   (`Component|Min|Max|Step|Unit|Icon|Initial|Static|Mode|Device Class`)
   before treating the string as a feature name.
3. Resolve `scope` (`area | floor | none`) from the prefix; resolve
   `scope_id` (`area_id | floor_id | area_id` respectively).
4. Component override: look on the same area for
   `<scope_prefix>Provides <lname> Component: <comp>`; default `select`.
5. Deduplicate by `scope_id||label` so multiple areas on the same floor
   collapse to one entry.

The entity `state` is `len(label_areas(<leader_label>))`.

## Sensor entities

`LabeledFeaturesStateSensor(CoordinatorEntity, RestoreEntity, SensorEntity)`:

- `_attr_state_class = "measurement"`
- `_attr_native_unit_of_measurement = "leaders"`
- `unique_id = f"{config_entry.entry_id}_features_state"`
- `entity_id` seeded from the config flow (defaults to
  `sensor.labeled_features_state`).
- `async_added_to_hass()` restores `leaders`, `features`, `snapshots` from
  `await self.async_get_last_extra_data()`, hands them to the coordinator
  before the first refresh so the initial tick uses the restored context.
- `extra_restore_state_data` serialises the same three fields.
- `extra_state_attributes` returns coordinator.data flattened.

`LabeledFeatureAreasStateSensor(CoordinatorEntity, SensorEntity)`:

- Same shape without `RestoreEntity` (the `label_map` is a pure function of
  the label/area/floor registries — recomputable at boot).
- `_attr_native_unit_of_measurement = "areas"`.

## Error handler

`error_handler.py`:

- Python-level helper `async def report_error(hass, mode, message, source,
  severity)` with tiers:
  - `silent` — no-op.
  - `log` — `_LOGGER.warning("%s: %s", source, message)`.
  - `alert` — attempt `hass.services.async_call("script", "send_alert",
    {alert_severity, alert_title=source, alert_message=message})`; on
    `ServiceNotFound` fall back to `persistent_notification.create` and a
    `warning`-level log.
  - `stop` — `_LOGGER.error(...)` and raise `HomeAssistantError` so the
    caller's task terminates. Callers that need to survive should catch.
- Service registration in `__init__.py`:
  `hass.services.async_register(DOMAIN, "report_error", handle_report_error,
  schema=REPORT_ERROR_SCHEMA)`. Schema mirrors
  `script.labeled_feature_error_mode` fields: `error_mode` (str, default
  `log`), `message` (str, required), `source` (str, default `Labeled
  Feature`), `severity` (str, default `medium`).
- `services.yaml` describes the service for the UI.

## Config flow

`ConfigFlow(domain=DOMAIN)`:

- Step `user`:
  - `instance_name` (str, required, default `Labeled Features`) — used as the
    HA entry title.
  - `leader_label` (str, required, default `feature_leader`).
  - `features_state_entity_id` (str, required, default
    `sensor.labeled_features_state`).
  - `areas_state_entity_id` (str, required, default
    `sensor.labeled_feature_areas_state`).
  - `error_mode_default` (select `silent|log|alert|stop`, default `log`).
  - `script_call_mode_default` (select `Blocking|NonBlocking`, default
    `Blocking`).
- Validation:
  - Reject duplicate `leader_label` across active entries.
  - Reject duplicate `features_state_entity_id` / `areas_state_entity_id`
    across active entries.
  - Validate entity_id format via `cv.entity_id`.
  - Verify the label exists in the label registry; if not, warn (via
    a `description_placeholders` note) but allow — user may add it later.
- `unique_id` = slug of `instance_name` (so re-add fails clearly).

`OptionsFlowHandler`:

- Same fields except `instance_name`, which becomes read-only (the entry
  title is renamed via `async_update_entry`).
- On save, `async_reload_entry(entry_id)` so the coordinators pick up the
  new leader label / entity_ids / defaults.

## Label sync (`label_sync.py`)

On `async_setup_entry` and whenever options change:

1. Ensure the two managed labels exist in the label registry:
   `Script Call Mode: <default>`, `Error Mode: <default>` (both created via
   `label_registry.async_create` if missing). Their `label_id`s are stored
   in the config entry's `data['managed_label_ids']`.
2. Apply exactly one managed `Script Call Mode: *` label and one managed
   `Error Mode: *` label to the features-state sensor entity. Remove any
   previously-applied managed labels for the same key when they no longer
   match the current default.
3. Never remove user-authored labels. Distinguish managed vs unmanaged by
   the stored `label_id` set.

On `async_unload_entry`:

- If the entry is being removed (not just reloaded), unbind managed labels
  from the sensor entity. Do not delete the labels themselves — other
  entities may still reference them.

## Ordered task list

1. **Wipe the existing `custom_components/labeled_features/` tree.** No
   inspection first (per instructions). `git rm -rf`.
2. **Manifest + skeleton.** Create `manifest.json` (domain, name,
   `config_flow: true`, `iot_class: local_push`, `codeowners`, empty
   `dependencies`), empty `__init__.py`, `const.py` with `DOMAIN =
   "labeled_features"` plus every literal event/label key documented above.
3. **models.py** — dataclasses for the entries (`LeaderEntry`,
   `FeatureEntry`, `LabelMapEntry`) plus `LabeledFeaturesStateData`
   holding the four attribute dicts.
4. **error_handler.py + services.yaml.** Implement the async helper and
   register the `labeled_features.report_error` service. Unit test the
   four tiers with a HA-instance fixture.
5. **config_flow.py + strings.json + translations/en.json.** Implement
   `ConfigFlow` with the fields and validation above. Unit test happy path,
   duplicate leader-label, duplicate entity_id, invalid entity_id.
6. **label_sync.py.** Implement the label create-if-missing and apply /
   unapply logic. Unit test with the label registry fixture.
7. **coordinator/areas.py.** Port the `label_map` template to Python.
   Coordinator subscribes to `label_registry_updated`, `area_registry_updated`,
   `floor_registry_updated`, `EVENT_HOMEASSISTANT_START`. Unit tests: (a)
   Area, Floor, and bare Provides labels; (b) `Component:` override; (c)
   modifier-label filtering; (d) floor-scope dedupe; (e) an area with no
   floor still resolves for `Area` and bare scopes but is skipped for
   `Floor`.
8. **sensor.py — `LabeledFeatureAreasStateSensor`.** Wire the coordinator,
   expose `label_map` as the single public attribute, honour the configured
   `entity_id`. Unit tests: state-count reflects `label_areas(...)`;
   attribute exposes the entire dict.
9. **coordinator/features.py.** Port the two big template blocks (`leaders`,
   `features`) to Python. The `_eval_leader` port is the risky bit; write
   its unit tests first (table-driven: Direction with numeric / non-numeric
   / first-tick, Enable-only / Disable-only / both, default truth for
   button/event vs boolean vs option-state vs numeric, Invert applied
   last).
10. **sensor.py — `LabeledFeaturesStateSensor`.** RestoreEntity path,
    `extra_restore_state_data`, and hand-off of restored data to the
    coordinator before `async_config_entry_first_refresh`.
11. **`__init__.py` wire-up.** `async_setup_entry`: create coordinators,
    subscribe event listeners, register the `report_error` service if it's
    not already registered (idempotent across multiple entries), forward
    `sensor` platform, run initial `label_sync`. `async_unload_entry`:
    cancel listeners, unforward platform, unbind managed labels if the
    entry is being removed. `async_reload_entry` on options change.
12. **Integration tests.** Load a config entry into a real HA instance,
    seed the label/area/floor registries with a fixture, fire the events
    documented above, assert sensor state and attributes match golden
    outputs derived from the current template sensor's behaviour.
13. **CI plumbing.** `Makefile` targets: `lint` (ruff + hassfest), `test`
    (pytest). Confirm `hassfest` passes.
14. **README update.** One paragraph in the repo root explaining the
    component's scope in this PR and pointing at the CuratedForest docs for
    the wider system.

## Validation

- `pytest -q` clean under `pytest-homeassistant-custom-component`.
- `ruff check` clean.
- `hassfest` clean (`python -m script.hassfest --requirements
  --action validate` if not available, at minimum a manifest.json schema
  check locally).
- Manual smoke on a live HA instance: install the component, add the
  default instance, verify `sensor.labeled_features_state` and
  `sensor.labeled_feature_areas_state` render, then confirm
  `automation.labeled_feature_leaders`, `script.labeled_feature_follower`,
  `script.labeled_feature_generics`, and `script.labeled_feature_sleep_timeout`
  behave the same as before (spot-check via existing dashboards / button
  entities).
- Multi-instance smoke: add a second entry with `leader_label:
  feature_leader_test` and suffixed entity_ids; label a single leader with
  `feature_leader_test`, confirm only the test sensor picks it up.

## Risks & mitigations

- **Template → Python parity.** Missing an edge case in `_eval_leader`
  silently breaks features. Mitigation: table-driven unit tests seeded
  directly from the docs' Direction / Enable / Disable / default-truth /
  Invert examples, plus a fixture-driven end-to-end test that replays a
  captured sequence of state_changed events and compares the resulting
  `features` dict.
- **Attribute-restore drift.** `RestoreEntity` restores only what
  `extra_restore_state_data` returns; if we add a new sensor attribute we
  must remember to restore it. Mitigation: single dataclass
  `LabeledFeaturesStateData` is the source of truth for both the coordinator
  state and the restore payload, and both round-trip through the same
  serialiser.
- **Label-sync fighting the user.** If a user manually removes the managed
  label the component would re-add it on next reload. Mitigation: the
  managed labels are treated as "authoritative when the config entry is
  loaded"; document that behaviour clearly in the strings.json helper text
  and the README.
- **Entity ID conflict on install.** If the user installs the component
  while the legacy template sensor still exists, HA appends `_2` to the new
  entity's ID and downstream scripts break. Mitigation: config-flow
  validation checks `hass.states.get(entity_id)`; if a state already exists
  and its `entity_id` is not owned by this integration, fail with a clear
  message instructing the user to remove the YAML template sensor first.
- **Timing on boot for events emitted before setup finishes.** Manual
  overrides fired during `homeassistant_started` may miss the sensor if the
  entry hasn't finished setup. Mitigation: the coordinator subscribes to
  events in `async_setup_entry` before returning; also the first refresh
  runs after subscription so any event that fires during setup queues
  naturally.

## Open questions (none blocking)

All important decisions above are resolved. Any additional refinement can
happen at implementation time — flag anything surprising in the PR.

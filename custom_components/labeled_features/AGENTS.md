<!-- Managed by agent: keep sections and order; edit content, not structure. Last updated: 2026-07-25 -->

# AGENTS.md — custom_components/labeled_features

## Overview
The `labeled_features` integration. It publishes two sensors that are consumed by **unchanged
YAML** outside this repo, so their state and attributes are a frozen contract. Everything here
is local-push: no polling, no network, no dependencies (`manifest.json` requirements is `[]`).

## Key Files
| File | Purpose | Touch it when |
|------|---------|---------------|
| `const.py` | Config keys, defaults, label keywords, scope maps, `FEATURE_META` catalog | Adding a setting or a catalog entry |
| `labels.py` | Registry access + label parsing. Mirrors HA's template helpers | Resolving labels, areas, floors |
| `features.py` | Pure logic: truth function, triple map, mode fold, entry builders | Changing behavior rules |
| `areas.py` | Pure `build_label_map()` for the areas sensor | Changing `Provides:` parsing |
| `errors.py` | `silent`/`log`/`alert`/`stop` tiers + precedence resolution | Reporting an internal error |
| `coordinator.py` | Per-entry state machine, event wiring, publication | Wiring events, changing when state is written |
| `sensor.py` | The two `SensorEntity` + `RestoreEntity` classes | Entity naming, restore, attribute exposure |
| `config_flow.py` | Config + options flow, override-line validation | Adding a setting to the UI |
| `routing.py` | Which instance consumes an untargeted compat event | Multi-instance behavior |
| `services.py` / `services.yaml` | `set_feature`, `set_snapshot`, `error_mode` actions | Adding or changing an action |
| `diagnostics.py` | Config-entry diagnostics dump | Adding debuggable state |
| `strings.json` + `translations/en.json` | UI text. **Keep these two identical** | Any flow/action change |

## Golden Samples (follow these patterns)
| For | Reference |
|-----|-----------|
| A pure behavior rule | `features.evaluate_leader` — takes a `LeaderInfo` + `Triple`, returns a bool, no `hass` |
| Publishing state safely | `coordinator._publish_features` + `_write_features` |
| A guarded event handler | `coordinator._async_state_changed` (cheap filters first, registry never) |
| Label parsing | `areas.build_label_map` (rejects modifier labels before registering a feature) |
| Error handling on a fallible path | `coordinator._async_refresh_registry`'s `try/except` → `_async_error` |

## Attribute contract (do not change without asking)

`sensor.<prefix>s_state` — state = leader count, unit `leaders`:

| Attribute | Shape |
|-----------|-------|
| `feature_meta` | `{<Feature>: {domain, kind, domain_label}}` — static, byte-compatible with the legacy sensor |
| `leaders` | `{entity_id: {current_value, previous_value, last_changed_timestamp}}` |
| `features` | `{feature: {scope: {scope_id: {enabled, mode, last_changed_timestamp, triggering_leader}}}}` |
| `snapshots` | `{snapshot_name: <mapping>}` |
| `config` | Diagnostic view of resolved settings (ours, not consumed by YAML) |

`sensor.<prefix>_areas_state` — state = gated-area count, unit `areas`, single attribute
`label_map`: `{"<scope_id>||<label>": {scope_id, label, scope, component, declaring_area_id, label_data}}`.

Invariants: global `scope_id` is `''` (empty string, not `None`); `last_changed_timestamp` is a
`float`; `enabled` is a real `bool`; `mode` is lowercase (`leader`/`any`/`all`); `triggering_leader`
is `''` for manual overrides, which is also what exempts them from the orphan drop.

## Publication rules (the trap that bit us once)
Home Assistant compares state attributes **shallowly**. If a published attribute is the same
object the coordinator later mutates, the previous `State` aliases it, `async_set` sees equal
attributes, and **no `state_changed` event fires at all** — silently breaking
`automation.labeled_feature_leaders`, which triggers on the `features` attribute.

Therefore:
- Working state (`self.leaders`, `.features`, `.snapshots`, `.label_map`) is **private by
  convention**. Entities read `published_features_attributes` / `published_label_map`.
- Every write goes through `_write_features()` / `_write_areas()`, which call
  `snapshot_tree()` first. Never call a listener directly.
- Any new mutating path must replace, not mutate (see `async_set_feature`,
  `async_set_snapshot`).
- **One write per logical tick.** Consumers diff `from_state`/`to_state`; extra writes
  double-dispatch and a missing write drops a transition.

## Hot-path rules
`_async_state_changed` runs for **every** state change in Home Assistant. Order of the guards
matters and none of them may touch a registry:
1. skip when not started, or when the entity is one of our own sensors
2. skip when `new_state` is `None`
3. skip when `old_state` is missing or unreal (boot restore / reconnect — not a user action)
4. skip when the entity is not in the cached `_leader_ids`

Registry-derived data (`_leader_ids`, `_gated_area_ids`, `_leader_meta`, `_triple_map`) is
rebuilt only in `_async_refresh_registry`, which is debounced behind
`REGISTRY_DEBOUNCE_SECONDS`. `_leader_info()` reads that cache plus the live state, nothing else.

## Label semantics
- Matching is **case-sensitive**; only the leader-label *lookup* accepts a label name or a
  label id (`resolve_label_id`), which is why the `Feature Leader` default still resolves an
  existing `feature_leader` id.
- `labels(entity)` returns the entity's own labels — device labels are **not** inherited.
  `area_id(entity)` **does** fall back to the entity's device's area. Both mirror the HA
  template helpers; keep them that way or the component resolves a different entity set than
  the sensors it replaces.
- Optional labels must carry the grouping label's scope prefix: `Area Leader: Night` pairs with
  `Area Night Enable: …`, never bare `Night Enable: …`. Use `SCOPE_LABEL_PREFIX` /
  `Triple.label_prefix`, never hand-written `"Area "` literals.

## Setup & environment
- Python 3.12, Home Assistant 2025.1+. No runtime dependencies.
- Async throughout; nothing here may block the event loop.
- `hass.data[DOMAIN][entry.entry_id]` holds the coordinator; setup order is
  **forward platforms → `coordinator.async_start()`** so entities restore their attributes
  before the first reconcile.
- Unload only tears down when `async_unload_platforms` succeeded; otherwise HA keeps the entry
  loaded and a half-unloaded instance would fail its next reload.

## Boundaries

### Always Do
- Put behavior rules in `features.py` / `areas.py` as pure functions
- Route internal failures through `errors.async_handle_error` so a bad label can never break a sensor
- Keep `strings.json` and `translations/en.json` byte-identical
- Update `services.yaml` and the `services` block of both translation files together

### Ask First
- Changing an attribute key, nesting level, or value type
- Adding a `manifest.json` requirement
- Changing the default `leader_label`, slug prefix, or any option default
- Making the slug prefix editable after setup

### Never Do
- Expose `self.features` / `.leaders` / `.snapshots` / `.label_map` directly to an entity
- Call `Registries.async_get()` (or any registry) from `_async_state_changed` or `_leader_info`
- Seed a new `features` triple from a registry reconcile — a label edit would look like a
  first-seed entry to the Leaders automation and dispatch followers
- Add a second state write to a single tick
- Re-implement a label prefix, mode value list, or truthy-state set that already exists in `const.py`

## Commands
| Task | Command |
|------|---------|
| Lint this package | `ruff check custom_components` |
| Format | `black --line-length 88 custom_components` |
| Fastest meaningful check | `pytest tests/test_features.py tests/test_publication.py -q` |
| Full suite | `pytest -q` |

There is no build step and no local manifest validation; hassfest and the HACS action run in CI.

## Code style
- `from __future__ import annotations` in every module; full type hints on public functions.
- Docstrings on every module, class, and function — `ruff` enforces the `D` rules.
- 88-column limit, `black`-formatted, `ruff`-sorted imports (`homeassistant` is first-party here).
- Prefix internal helpers with `_`. Constants live in `const.py`, never inline.
- Comments explain *why* (especially the HA quirks); don't restate the code.
- Log through `_LOGGER = logging.getLogger(__package__)`; never `print`.

## Security
- No network calls, no secrets, no `requirements`. Keep it that way.
- Compat bus events (`labeled_feature_set`, `labeled_feature_snapshot_set`) are **untrusted
  input**: any script can fire them. Coerce and validate every field
  (`async_set_feature` checks the feature name and scope) and never let a bad payload raise out
  of a handler — route it through `errors.async_handle_error`.
- Actions are the validated path; keep their voluptuous schemas in `services.py` authoritative.
- `diagnostics.py` intentionally redacts nothing: only local label/area/feature metadata is
  exposed. If a future field could carry user data, redact it there.

## Examples

Publishing state — the only correct shape:
```python
# GOOD: replace, then let _write_features() snapshot and notify once
features = snapshot_tree(self.features)
set_entry(features, triple, build_manual_entry(get_entry(features, triple), enabled, ts))
self.features = features
self._write_features()

# BAD: mutates the dict the previous State still references -> no state_changed event
set_entry(self.features, triple, ...)
self._write_features()
```

Scope-prefixed label lookup:
```python
# GOOD
prefix = triple.label_prefix          # "Area Night"
enabled = f"{prefix} Enable: {value}" in leader.labels

# BAD: breaks for floor/global scope and drifts from SCOPE_LABEL_PREFIX
enabled = f"Area {feature} Enable: {value}" in leader.labels
```

## Commit checklist
- [ ] `ruff check custom_components` and `black --line-length 88 custom_components` clean
- [ ] `pytest -q` passes, output pasted into the response
- [ ] No attribute key, nesting, or type changed (or explicitly approved)
- [ ] New write paths publish exactly one detached snapshot per tick, with a test that counts events
- [ ] `strings.json` and `translations/en.json` still identical
- [ ] Behavior divergence from the legacy YAML recorded in README `KNOWN_DIVERGENCES`

## When stuck
Compare against the sensor being replaced: `/home/coder/HomeAssistant/configuration.yaml`
(areas sensor lines 67-187, features sensor lines 214-693) and its consumers in
`automations.yaml` (Leaders 2094-2802, Areas 2846-3035). Reproduce the YAML, then document the
divergence in README `KNOWN_DIVERGENCES`.

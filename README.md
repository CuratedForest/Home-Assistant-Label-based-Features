# Labeled Features (Home Assistant custom integration)

A native implementation of the **state layer** of the
[Label Based Features](https://curatedforest.com/tech/home-assistant/label-based-features/)
system. Phase 1 replaces the two production trigger-based template sensors with
real entities and adds tiered error handling, while every downstream consumer —
the Leaders/Areas automations and the `labeled_feature_*` scripts — keeps
working unchanged.

| Replaced | Downstream consumers that keep working |
|---|---|
| `sensor.labeled_features_state` | `automation.labeled_feature_leaders`, `script.labeled_feature_follower`, `script.labeled_feature_generics`, `script.labeled_feature_sleep_timeout` |
| `sensor.labeled_feature_areas_state` | `automation.labeled_feature_areas`, `script.labeled_feature_area` |

Leaders, features and followers are still configured **entirely with labels**.
The config flow only carries the instance-level settings that used to live as
labels on the template sensors — and labels on the new sensor entities still
win over the config entry.

Not in scope for Phase 1: the Leaders/Areas automations, the dispatch loop, the
follower/button/generics/area/entities/sleep-timeout scripts. Those stay in YAML.

## What it creates

Two sensors per instance:

### `sensor.<prefix>s_state` — Labeled Features State

State is the number of entities carrying the leader label. Attributes:

- **`feature_meta`** — the static generic-feature catalog, keyed by feature
  name with `domain`, `kind` and `domain_label`.
- **`leaders`** — `{entity_id: {current_value, previous_value,
  last_changed_timestamp}}`. `event`-domain entities track their
  `event_type` attribute rather than their (timestamp) state, and skip-values
  (`*_initial_press`, `unknown`/`unavailable`/`none`) carry the previous value
  and timestamp forward.
- **`features`** — `feature → scope → scope_id → {enabled, mode,
  last_changed_timestamp, triggering_leader}`. Scope is `area`, `floor` or
  `global`; the global scope_id is the empty string `''`.
- **`snapshots`** — persisted mapping surface for scripts that must survive
  `mode: restart` (e.g. `sleep_timeout`).
- **`config`** — diagnostic view of the resolved instance settings.

### `sensor.<prefix>_areas_state` — Labeled Feature Areas State

State is the number of areas carrying the leader label. The single attribute
**`label_map`** is the flat `<scope_id>||<label>` registry of
`(Area |Floor |)Provides:` declarations, each entry carrying `scope_id`,
`label`, `scope`, `component`, `declaring_area_id` and the nested `label_data`
copy the Areas automation forwards verbatim. `component` defaults to `select`
and is only overridden by a sibling
`(Area |Floor |)Provides <Feature> Component: <comp>` label on the declaring
area. Floor-scoped declarations dedupe by floor.

## Behavior

Recompute triggers:

- a `state_changed` event for an entity carrying the leader label — ignored
  when there is no real previous state, so boot restores and integration
  reconnects never look like a user action;
- the `labeled_feature_set` and `labeled_feature_snapshot_set` compat events;
- label / area / floor / entity registry changes and `homeassistant_start`
  (debounced), which rebuild `label_map` and reconcile the leader set.

Per-leader truth function, in order: Direction
(`<pfx><F> Increasing|Decreasing: True`) → `<pfx><F> Enable:` / `Disable:` →
`event`/`button` domains always fire → default truth (`state == <F>`
case-sensitively, or a generic truthy state) → `<pfx><F> Invert: True` flips
the result. Optional labels must carry the same scope prefix as the grouping
label.

Resolution modes fold the per-leader values per triple: `Leader` (default) uses
only the leader that drove the tick, `Any` ORs and `All` ANDs across every
leader mapped to the triple.

`last_changed_timestamp` bumps when `enabled` flips, when the entry is new, or
whenever the triggering leader is an `event`/`button` entity — every accepted
press is a distinct dispatch. Triples whose leaders lost their labels are
dropped; manual overrides (`triggering_leader: ''`) are exempt.

## Configuration

Add the integration from **Settings → Devices & Services → Add integration →
Labeled Features**.

| Setting | Default | Notes |
|---|---|---|
| Instance name | `Labeled Features` | Config entry title, also usable as the `instance` target of the actions. |
| Entity slug prefix | `labeled_feature` | Sensors become `sensor.<prefix>s_state` and `sensor.<prefix>_areas_state`. The default reproduces the legacy entity IDs. **Cannot be changed later.** |
| Leader label | `Feature Leader` | Identifies leader entities *and* the areas scanned for `Provides:` declarations. Accepts a label name or a label id, so an existing `feature_leader` label id also resolves. |
| Default resolution mode | `leader` | Used when no `Mode` label or override matches. |
| Default script call mode | `Blocking` | Forward-looking; see below. |
| Default error mode | `log` | `silent` / `log` / `alert` / `stop`. |
| Per-feature resolution modes | — | One per line in label syntax: `Area Night Mode: All`. |
| Per-feature script call modes | — | One per line: `Area Sleep Timer Script Call Mode: NonBlocking`. |

**Precedence: labels win, options are defaults.** A
`<Scoped Feature> Mode: Leader|Any|All` or `Error Mode: <tier>` label on the
sensor entity always beats the config entry, which in turn beats the hardcoded
fallback.

> **Script Call Mode is a forward-looking option in Phase 1.** The YAML
> `automation.labeled_feature_leaders` reads Script Call Mode directly from
> labels on `sensor.labeled_features_state`, so the option only shows up in the
> `config` attribute until that automation is migrated. `Mode` is the one
> setting the sensor itself consumes.

## Actions

- `labeled_features.set_feature` — validated equivalent of the `Set Feature`
  catalog entry (`target_feature`, `scope`, `scope_id`, `enabled`, optional
  `instance`).
- `labeled_features.set_snapshot` — `snapshot_name`, `payload` (empty deletes),
  optional `instance`.
- `labeled_features.error_mode` — mirrors `script.labeled_feature_error_mode`
  (`error_mode`, `message`, `source`, `severity`). The `stop` tier raises so the
  caller halts.

The compat events `labeled_feature_set` and `labeled_feature_snapshot_set` keep
working, so no existing script needs editing.

### Multiple instances

Run a second instance (different prefix) to A/B against the first. Because the
compat events are global and untargeted, at most **one** instance consumes each
payload:

1. an explicit `instance` field (config entry title or id) wins;
2. otherwise the only configured instance;
3. otherwise the single instance that leads or already tracks the target triple
   (or already holds the named snapshot);
4. otherwise, when nothing owns it yet, the instance using the default
   `labeled_feature` prefix.

If several instances match — which is exactly what happens while a test
instance shares the production leader label — the payload is **dropped with a
warning** rather than guessed at. Add an `instance` field, or remove the extra
instance, to resolve it.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/CuratedForest/Home-Assistant-Label-based-Features`
   with category **Integration**.
3. Install **Labeled Features**, then restart Home Assistant.

### Manual

Copy `custom_components/labeled_features/` into your `config/custom_components/`
directory and restart Home Assistant.

## Migration from the template sensors

The component cannot claim `sensor.labeled_features_state` /
`sensor.labeled_feature_areas_state` while the template sensors still own those
entity IDs — Home Assistant would append `_2`. Migrate in this order:

1. **Test first.** Create an instance with a non-default prefix (e.g.
   `lf_test`) and the same leader label. Nothing consumes it, so it runs
   harmlessly beside the template sensors.
2. **Manual A/B.** Exercise each leader shape and compare the attributes in
   Developer Tools → Template:

   ```jinja
   {{ state_attr('sensor.labeled_features_state', 'features')
      == state_attr('sensor.lf_tests_state', 'features') }}
   {{ state_attr('sensor.labeled_feature_areas_state', 'label_map')
      == state_attr('sensor.lf_test_areas_state', 'label_map') }}
   ```

   Cover: a boolean leader, an `input_select` option leader, a button/`event`
   leader (including a repeat press), a Direction leader, an `Any`/`All`
   feature, a manual `Set Feature`, a `Set Snapshot`, and an area `Provides:`
   add/remove.
3. **Cut over.** Delete both `template:` sensor blocks from
   `configuration.yaml`, **remove the test instance** (while it shares the
   production leader label, untargeted `Set Feature` / `Set Snapshot` events
   match both instances and are dropped with a warning), restart, then create
   the production instance with the default `labeled_feature` prefix so it
   claims the legacy entity IDs.
4. **Re-apply the sensor labels.** Labels live on the entity, and the new
   registry entries start unlabeled — any `<Scoped F> Mode:`,
   `Script Call Mode:` or `Error Mode:` labels you had on the template sensors
   must be re-applied (or moved into the options flow). Without this every
   feature silently falls back to `Leader` / `Blocking` / `log`.
5. **Rollback** by removing the config entry and restoring the two `template:`
   blocks from git history.

## KNOWN_DIVERGENCES

Phase 1 reproduces the *YAML* behavior wherever it differs from the docs, so
parity comes first and cleanup later.

1. **Enable/Disable compares the entity state, not `current_value`.** On
   `event`-domain leaders the state is an ISO timestamp, so
   `<pfx><F> Enable: 1_short_release` never matches. Faithful to the template
   sensor. Direction labels *do* use `current_value`/`previous_value`.
2. **New triples are not seeded on a label edit.** Adding a
   `(Area |Floor |)Leader: <F>` label makes the leader appear in `leaders`, but
   the `features` entry only appears on that leader's next state change.
   Seeding immediately would look like a first-seed entry to
   `automation.labeled_feature_leaders` and dispatch followers purely because a
   label was edited.
3. **`leaders` seeding happens on the debounced registry reconcile**, not on the
   next unrelated leader tick as in the template sensor. The resulting content
   is the same, just sooner.
4. **Areas sensor scope naming.** The bare `Provides: <F>` form reports
   `scope: none` (matching the Areas stack), while the features sensor's bare
   `Leader: <F>` form reports `scope: global`. Both are part of the existing
   downstream contract and are preserved as-is.
5. **`Error Mode` on the automations is unchanged.** The YAML automations still
   read their own `Error Mode:` labels; the component's default error mode
   applies only to the component's own code paths.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install pytest-homeassistant-custom-component
pytest
```

## License

GPL-3.0 — see [LICENSE](LICENSE).

# Labeled Features

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

A Home Assistant custom integration implementing the state layer of the
[Label Based Features](https://curatedforest.com/tech/home-assistant/label-based-features/)
system: drive automations from entity labels and area/floor metadata via a
leader/follower pattern, with no per-device automation sprawl.

This first release **replaces the two production trigger-based template
sensors** (`sensor.labeled_features_state` and
`sensor.labeled_feature_areas_state`) with byte-compatible native sensors
and adds a shared, tiered error handler. The existing
`automation.labeled_feature_leaders`, `automation.labeled_feature_areas`,
and every `script.labeled_feature_*` (Follower, Generics, Somrig,
Styrbar, Symfonisk, Area, Entities, Sleep Timeout, Error Mode) continue
to work unchanged.

## What this does

Two sensors per config entry (default entity IDs, fully configurable per
instance so a production and testing instance can co-exist):

- **`sensor.labeled_features_state`** — state is the count of leader
  entities. Attributes:
  - `feature_meta` — static catalog of the built-in generic features
    (Media *, Volume *, Lights *, Fan *).
  - `leaders` — per-leader `{current_value, previous_value,
    last_changed_timestamp}`. Skip values (`*_initial_press`,
    unknown/unavailable/none) preserve the previous entry.
  - `features` — `feature → scope → scope_id → {enabled, mode,
    last_changed_timestamp, triggering_leader}`. Global scope uses `''`
    as the `scope_id` key. `mode` is resolved from
    `<Scoped F> Mode: Leader|Any|All` labels on the sensor entity itself.
  - `snapshots` — persisted mapping surface for long-running scripts
    (`labeled_feature_sleep_timeout`) that need working state to survive
    `mode: restart`.
- **`sensor.labeled_feature_areas_state`** — state is the count of areas
  labeled `feature_leader`. Its `label_map` attribute is the flat
  `<scope_id>||<label>` registry of `(Area |Floor |)Provides:`
  declarations that `automation.labeled_feature_areas` diffs.

Leaders are the entities carrying the configured **leader label**
(default `feature_leader`). Both sensors re-render on the same events
the template sensors did:

| Event                                | Effect                                       |
| ------------------------------------ | -------------------------------------------- |
| `state_changed` (filtered to leaders) | Re-evaluate `leaders` + affected `features` |
| `labeled_feature_set`                | Write manual override into `features`        |
| `labeled_feature_snapshot_set`       | Merge / delete a `snapshots` entry           |
| `label_registry_updated`             | Reconcile leaders + rebuild `label_map`      |
| `area_registry_updated`              | Rebuild `label_map`                          |
| `floor_registry_updated`             | Rebuild `label_map`                          |
| `homeassistant_start`                | Full reconcile                               |

`sensor.labeled_features_state` is a `RestoreEntity` — `leaders`,
`features`, and `snapshots` survive restarts. `feature_meta` is
code-owned and re-populated on every boot. `label_map` is a pure
function of the label/area/floor registries and is recomputed at boot.

## Error handling

`labeled_features.report_error` mirrors `script.labeled_feature_error_mode`:

| Tier   | Action                                                                                              |
| ------ | --------------------------------------------------------------------------------------------------- |
| silent | No-op.                                                                                              |
| log    | `system_log.write` at `warning` with `"{source}: {message}"`.                                       |
| alert  | Calls `script.send_alert`; if the script isn't registered, falls back to `persistent_notification`. |
| stop   | Logs at `error` and raises `HomeAssistantError`. Callers are still responsible for propagating.     |

Existing scripts continue to call `script.labeled_feature_error_mode`
unchanged. The service is available for any new callers (or the
component's own internal error paths) that want the same behaviour
without duplicating logic.

## Installation

### HACS (custom repository)

1. HACS → Integrations → Custom repositories
2. Add `https://github.com/CuratedForest/Home-Assistant-Label-based-Features` as *Integration*
3. Install "Labeled Features"
4. Restart Home Assistant

### Manual

1. Copy `custom_components/labeled_features` into your
   `custom_components/` directory.
2. Restart Home Assistant.

**Before installing, delete the two template sensor blocks in
`configuration.yaml`** (`sensor.labeled_features_state` and
`sensor.labeled_feature_areas_state`). If a state already exists at the
configured entity IDs, HA will suffix `_2` onto the new sensor and every
downstream automation and script will silently miss it.

## Configuration

Settings → Devices & Services → Add Integration → **Labeled Features**.
Fields:

| Field                          | Default                                | Notes                                                                                            |
| ------------------------------ | -------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Instance name                  | `Labeled Features`                     | Free-form; used as the entry title.                                                              |
| Leader label                   | `feature_leader`                       | Entities carrying this label participate in the instance. Two instances → two disjoint labels.   |
| Features state entity ID       | `sensor.labeled_features_state`        | Keep the default so existing scripts keep resolving it.                                          |
| Areas state entity ID          | `sensor.labeled_feature_areas_state`   | Ditto.                                                                                           |
| Error Mode default             | `log`                                  | Applied as a managed label on the features-state sensor entity. Downstream scripts read via `labels()`. |
| Script Call Mode default       | `Blocking`                             | Same as above.                                                                                   |

Per-feature `<Scoped F> Mode: Leader|Any|All` and
`<Scoped F> Script Call Mode: Blocking|NonBlocking` overrides continue to
live as labels on the sensor entity — the config flow only owns the two
sensor-wide defaults so it doesn't grow with the feature catalog.

**Running a testing instance side-by-side**: add a second entry with a
different leader label (e.g. `feature_leader_test`) and different entity
IDs. Label the entity or entities you want to test with the test
instance's leader label; production entities carrying `feature_leader`
are unaffected.

## Labels

All matching is **case-sensitive** (`True`, feature names, keywords).

On leader entities (must carry the configured leader label):

| Label                          | Meaning                                              |
| ------------------------------ | ---------------------------------------------------- |
| `Leader: <F>`                  | Leads feature `<F>` globally                         |
| `Area Leader: <F>`             | Leads `<F>` for the entity's area                    |
| `Floor Leader: <F>`            | Leads `<F>` for the entity's floor                   |
| `<pfx><F> Enable: <value>`     | Enabled while state equals `<value>`                 |
| `<pfx><F> Disable: <value>`    | Disabled while state equals `<value>`                |
| `<pfx><F> Increasing: True`    | Enabled when the numeric value rises                 |
| `<pfx><F> Decreasing: True`    | Enabled when the numeric value falls                 |
| `<pfx><F> Invert: True`        | Invert the result (applied last)                     |

`<pfx>` is `Area ` / `Floor ` / empty, matching the `Leader:` label's
scope. Direction labels take precedence over Enable/Disable, which take
precedence over the default truth function (state equals the feature
name, or is one of `on/true/home/open/detected/active/unlocked`
case-insensitively; `event` and `button` domain entities are always
true and bump `last_changed_timestamp` on every accepted press).

On the features sensor entity itself:

| Label                                                 | Meaning                                        |
| ----------------------------------------------------- | ---------------------------------------------- |
| `<pfx><F> Mode: Leader\|Any\|All`                     | Fold mode across a triple's leaders            |
| `<pfx><F> Script Call Mode: Blocking\|NonBlocking`    | Follower-script dispatch mode                  |
| `Error Mode: <tier>` (managed by the integration)     | Sensor-wide default Error Mode                 |
| `Script Call Mode: <mode>` (managed by the integration) | Sensor-wide default Script Call Mode         |

On areas (must carry the configured leader label):

| Label                                                        | Meaning                                                                |
| ------------------------------------------------------------ | ---------------------------------------------------------------------- |
| `Provides: <Label>` / `Area Provides: <Label>` / `Floor Provides: <Label>` | Register `(scope_id, label)` in `label_map`               |
| `<pfx>Provides <Label> Component: <comp>`                     | Component hint (default `select`)                                     |
| `<pfx>Provides <Label> {Min,Max,Step,Unit,Icon,Initial,Static,Mode,Device Class}: ...` | Modifier labels — consumed by `script.labeled_feature_area`, ignored by the sensor |

## Development

```bash
make install      # create .venv and install deps
make lint         # ruff
make test         # pytest (via pytest-homeassistant-custom-component)
make ci           # lint + test
```

## License

GPL-3.0 — see [LICENSE](LICENSE).

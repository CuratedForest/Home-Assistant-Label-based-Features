# Area Based Features

Source: the Area Based Features spec doc. Tag an area with
`(Area |Floor |)Provides: <FeatureName>` and the system generates the
corresponding MQTT-discovery entity; remove the label and the entity is
retracted. Survives restarts (retained discovery topics re-published on
`homeassistant.start`).

## Pipeline layers (responsibility boundaries)

```
sensor.labeled_feature_areas_state.label_map   ← trigger surface only
            │  (state-attribute change on label_map)
            ▼
automation.labeled_feature_areas               ← diff added/removed, route
        ┌───────────────────┬──────────────────────────┐
        │ added             │ removed (delete: true)    │
        ▼                   ▼
                  script.labeled_feature_area   ← owns canonical naming;
                                                  short-circuits on _delete
                                ▼
                  script.labeled_feature_entities ← publish/retract MQTT
```

- **Sensor** (now the custom component): emits the flat
  `<scope_id>||<label>` registry. Each entry: `scope_id`, `label`, `scope`,
  `declaring_area_id`, `component` (+ nested `label_data` copy). **No
  object_id, no feature knowledge.** `component` defaults to `select`; the
  only override honored is a `(Area |Floor |)Provides <Label> Component:
  <comp>` label on the declaring area. Adding a built-in feature requires
  zero sensor changes.
- **Automation**: trivial diff-and-dispatch. `added = now - prev`, `removed =
  prev - now` keyed `<scope_id>||<label>`; a `component` change appears in
  both (rename semantics). Removes run first. On `homeassistant.start`
  everything is re-published (idempotent). Owns no parsing or naming.
- **`script.labeled_feature_area`**: the feature source of truth. `choose:`
  on feature name; each branch computes the canonical object_id **first**,
  short-circuits on `_delete` **before** any label resolution (on delete the
  driving labels are already gone), then builds the payload from fresh
  `labels(declaring_area_id)` reads.
- **`script.labeled_feature_entities`**: generic MQTT-discovery creator /
  retract helper. `delete: true` publishes an empty retained payload.
  `create_mode`: `always` (default) | `if_missing` | `never`.
  `initialize_mode` / `attributes_mode`: `set_if_missing` (default) |
  `always` | `never`. Errors route through `script.labeled_feature_error_mode`.

## Scope semantics

| Label on area | Scope | Dynamic-option pool | scope_id in object_id |
|---|---|---|---|
| `Area Provides: <F>` | `area` | `area_entities(area)` + device entities | the area id |
| `Floor Provides: <F>` | `floor` | union over the area's floor | the floor id (deduped per floor) |
| `Provides: <F>` (bare) | `none` | entire entity pool | the declaring area id |

Option labels on entities follow the same prefixes: `Area Provides Option:
<F>` (area scope), `Floor Provides Option: <F>` (floor scope), bare `Provides
Option: <F>` (none-scoped features anywhere). `(scope-prefix)Provides <F>
Exclude: True` opts an entity out.

## Built-in feature catalog

| FeatureName | Trigger | Component | Generates |
|---|---|---|---|
| `Manifest` | implicit — one per gated area | `sensor` | `sensor.area_manifest_<area_id>` (state = entity_count; attributes: area_id, area_name, entity_ids, device_ids, labels) |
| `Shoot Zone` | `Provides: Shoot Zone` | `sensor` | `sensor.<scope_id>_vpd` (Antoine-equation VPD from the scope's temp+humidity sensors) |
| `Root Zone` | `Provides: Root Zone` | `number` | `number.<scope_id>_tracked_psi` (0–2000, step 0.1, optimistic, initial 0 set-if-missing) |
| `<UserDefined>` | `Provides: <F>` (+ optional static options) | `select` (overridable) | `select.<scope_id>_<slug(F)>` |

## Label catalog

On areas:

```
(Area |Floor |)Provides: <FeatureName>                                  # create
(Area |Floor |)Provides Options: <F>: <v1>|<v2=label2>|<v3>             # static options
(Area |Floor |)Provides <F> Initial: <value>
(Area |Floor |)Provides <F> Icon: mdi:foo
(Area |Floor |)Provides <F> Component: <component>                      # override select
(Area |Floor |)Provides <F> Min|Max|Step: <number>                      # number component
(Area |Floor |)Provides <F> Unit: <string>
(Area |Floor |)Provides <F> Device Class: <string>
```

On entities (select option pools):

```
(Area |Floor |)Provides Option: <FeatureName>
(Area |Floor |)Provides Option <FeatureName>: <custom_dropdown_label>
(Area |Floor |)Provides <FeatureName> Exclude: True
```

Static options: pipe-delimited (labels may contain commas); `value=label`
form supported. Three pool modes: pure dynamic (entity Option labels), pure
static (`Provides Options:` implies `Provides:`), or combined (static first,
dynamic appended).

Modifier keywords (`Component`, `Min`, `Max`, `Step`, `Unit`, `Icon`,
`Initial`, `Static`, `Mode`, `Device Class`) must never register as features
in their own right — the component rejects them in `areas.py`.

## Deletion semantics

Removing a `Provides:` label (or the area) drops the `label_map` entry; the
automation dispatches `script.labeled_feature_area` with `delete: true`, which
publishes an empty retained payload to
`homeassistant/<component>/<object_id>/config`. Renames appear as
remove-then-add in one trigger.

## Adding a new built-in area feature

1. Add a `choose:` branch to `script.labeled_feature_area`: compute `_obj`
   first, short-circuit on `_delete` immediately after, then build the
   payload.
2. Document it in the catalog.
3. **No sensor changes** (the label_map already exposes every pair with
   `component: select`; a `Component:` label covers other defaults).
4. **No automation changes** (feature-agnostic router).

User features needing only a different component need none of the above —
`Provides <F> Component:` routes through the generic branch.

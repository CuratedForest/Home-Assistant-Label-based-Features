# Label Catalog — the complete grammar

Source: the Features & Labels spec doc, annotated for the current
(component + YAML) implementation. All matching is **case-sensitive**.

## Mandatory labels

Every leader needs:

```
Feature Leader
```

(The component's `leader_label` option defaults to `Feature Leader` and
accepts a label name or id, so a legacy `feature_leader` id also resolves.)

Every entity in a leader/follower setup carries one grouping label per
feature group:

```
(Area |Floor |)(Leader|Follower): FEATURE_NAME
```

- `Area `/`Floor `/bare — the scope of filtering (bare = global).
- `Leader`/`Follower` — the entity's role.
- `FEATURE_NAME` — user-defined feature name.

## Provides labels (one concept, two meanings by location)

| Where it lives | Meaning | Example |
|---|---|---|
| On an **entity** | Domain-grouping shorthand: opts the entity into every generic feature whose `domain_label` matches. Never generates entities. | `Area Provides: Media Player` on `media_player.tv_room_audio` |
| On an **area** | Area Based Features declaration: generates an MQTT-discovery entity in that area's scope. | `Area Provides: Audio Mode` on the `kitchen` area |

Provider shorthand (entity context):

| Provider label | Implicit domain | Features it opts into |
|---|---|---|
| `Provides: Media Player` | `media_player` | Media Toggle/Play/Pause/Next/Previous/Seek Back/Seek Forward, Volume Up/Down |
| `Provides: Light` | `light` | Lights On/Off/Up/Down |
| `Provides: Fan` | `fan` | Fan On/Off/Up/Down |

**4-step Provides resolver** (run for both the feature name and its
`domain_label`, results unioned):

```
resolve_provides(label, scope_prefix):
  try in order, return first non-empty:
    1. label_entities(label)                               # exact (global)
    2. label_entities(scope_prefix ~ 'Provides: ' ~ label)
    3. label_entities(scope_prefix ~ 'Follower: ' ~ label)
    4. label_entities(scope_prefix ~ 'Leader: '   ~ label)
  Candidates 2–4 are filtered to the scope entity set;
  candidate 1 is never scope-filtered.
```

Final targets = the union minus entities labeled
`(scope-prefix)<Feature> Exclude: True` (and the same for the `domain_label`).

Area-context label catalog — see `area-based-features.md`.

## Optional labels (gates and filters)

Format: `(Area |Floor |)FEATURE_NAME <Function>: <value>`. **The scope prefix
must match the grouping label** (`Area Leader: Fan` → `Area Fan …`).

| Function | Value | Effect |
|---|---|---|
| `Enable` / `Disable` | a string | **Leader:** state matches → feature Enabled / leaves it → Disabled. **Follower:** when `leader_enabled` matches, set the entity to that value. |
| `Only` | `Enable`\|`Disable` | Fire only when `leader_enabled` matches. |
| `Invert` | `True`\|`False` | **Leader:** inverts the `leader_enabled` passed down. **Follower:** inverts the action. |
| `Increasing` / `Decreasing` | `True` | **Leader only.** Numeric `current_value` vs `previous_value`; both may be present (OR). Takes precedence over Enable/Disable; Invert applies after. |
| `Between` / `Not Between` | `<HH:MM>:-<HH:MM>` (`-` = open end) | Time-of-day gate, evaluated at trigger time. Multiple labels OR within each kind. |
| `Toggle` | `True` | **Leader:** bypasses Only/Increasing/Decreasing (Between still applies), passes `toggle: true` to followers. **Follower:** toggles current state; direct-value labels skipped. |
| `Error Mode` | `Silent`\|`Log`\|`Alert`\|`Stop` | Per-feature override of dispatch error handling (component: lowercase tiers). |
| `Exclude` | `True` | **Follower only.** Opts the entity out of `labeled_feature_generics` resolution for the feature (domain-fallback opt-out). |

## Default truth function (leader with no Enable/Disable/Direction label)

Two rules OR'd, evaluated by the state sensor / component:

1. **State equals the feature name** (case-sensitive) — option-style leaders
   (`input_select.house_mode` with `Leader: Night`).
2. **Generic truthy state** (case-insensitive): `on`, `true`, `home`, `open`,
   `detected`, `active`, `unlocked`.

`event` and `button` domains always evaluate `enabled = true` (every change is
a fire). `Invert: True` applies after the default rule. Pin explicitly with
`<F> Enable: <value>` when neither rule fits.

## Automation-level labels

On `automation.labeled_feature_leaders`:

```
Error Mode: (Silent|Log|Alert|Stop)
```

sets the default Error Mode; a leader-level feature Error Mode overrides it.

On `sensor.labeled_features_state` — **Script Call Mode**:

```
(Area |Floor |)FEATURE_NAME Script Call Mode: (Blocking|NonBlocking)
Script Call Mode: (Blocking|NonBlocking)
```

Controls whether the leaders automation awaits dispatched `script.*` items.
Blocking (default) invokes the ref directly; NonBlocking uses `script.turn_on`
(fire-and-forget for `parallel`/`restart` scripts — required for long-running
scripts like `labeled_feature_sleep_timeout`). Resolver precedence: scoped
per-feature → unscoped per-feature → sensor-wide → `Blocking`. The same
resolver runs in `script.labeled_feature_follower`. `automation.*` / `scene.*`
refs are always invoked directly.

> Phase-1 note: the component stores `default_script_call_mode` and exposes it
> in the `config` attribute, but the YAML leaders automation still reads Script
> Call Mode from labels.

## Component configuration equivalents

Labels remain the primary surface; config subentries are a **fill-in** (a real
label wins, the subentry sits inert until the label is removed):

| Subentry | Label equivalent |
|---|---|
| Leader definition | `Feature Leader` + `(Area\|Floor\|)Leader: <F>` (+ Enable/Disable/Increasing/Decreasing/Invert) |
| Provides declaration | `(Area\|Floor\|)Provides: <F>` (+ `Provides <F> Component:`) |
| Feature mode | `<Scoped F> Mode: Leader\|Any\|All` on the sensor entity |

Mode precedence: sensor label > mode subentry > per-feature option override >
entry default > `leader`.

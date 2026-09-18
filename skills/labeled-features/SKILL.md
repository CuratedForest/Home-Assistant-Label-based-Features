---
name: labeled-features
description: Use when working on the Label Based Features system — the label grammar (Leader/Follower/Provides labels), the labeled_features custom component, the labeled_feature_* YAML scripts and automations, feature dispatch, button mappings, area-generated MQTT entities, or any leader/follower wiring question. Also use when docs-vs-YAML parity matters.
---

# Label Based Features (Spencer's Lab)

A maintainable, scalable, dynamic way to drive Home Assistant automations from
area/floor metadata and entity labels: configure a device's area and its
entities' labels, and features "just work".

## Implementation status — read this first

The system is mid-transition from pure YAML to a native custom component.
**The docs describe the target design; the YAML is the current production
behavior; where they disagree, reproduce the YAML** (see README
`KNOWN_DIVERGENCES`).

| Layer | Implementation | Where |
|---|---|---|
| Labeled Features State sensor | **Custom component** (`custom_components/labeled_features`) — replaces the trigger-based template sensor | `sensor.labeled_features_state` |
| Labeled Feature Areas State sensor | **Custom component** — replaces the template sensor | `sensor.labeled_feature_areas_state` |
| Error handling (silent/log/alert/stop tiers) | **Both** — component handles its own paths (`errors.py`, `labeled_features.error_mode` action); existing YAML scripts keep calling `script.labeled_feature_error_mode` — do not replace it in the scripts | `errors.py` + `scripts.yaml` |
| Leaders automation, Areas automation | YAML (unchanged consumers) | `/home/coder/HomeAssistant/automations.yaml` |
| Follower / Generics / Area / Entities / button-mapping / Sleep Timeout scripts | YAML (unchanged consumers) | `/home/coder/HomeAssistant/scripts.yaml` |

The component is Phase 1 (state layer only). Migrating the automations/scripts
into the component is Phase 2+ and requires explicit approval.

## The one rule that bites everyone

**All label matching is case-sensitive.**

- Feature names capitalized exactly everywhere: `Area Leader: Screen`,
  `Area Follower: Screen`, `Area Screen Only: Enable` must match.
- Booleans capitalized: `True` / `False`, never `true` / `false`.
- Label keywords capitalized: `Toggle`, `Invert`, `Increasing`, `Decreasing`,
  `Only`, `Between`, `Not Between`, `Enable`, `Disable`, `Script`, `Arg`,
  `Error Mode`, `Provides`, `Provides Option(s)`, `Provides Initial/Icon/
  Component/Min/Max/Step/Unit/Device Class`, `Exclude`.
- Optional labels must carry the same scope prefix as the grouping label:
  `Area Leader: Night` pairs with `Area Night Enable: …`, never bare
  `Night Enable: …`.

## Core concepts

- **Leader** — entity labeled `Feature Leader` + `(Area |Floor |)Leader: <F>`.
  Its state changes drive feature evaluation.
- **Follower** — entity labeled `(Area |Floor |)Follower: <F>`, acted on by the
  dispatch loop.
- **Feature** — a named capability (`Night`, `Lights On`, `Screen`), resolved
  per scope.
- **Triple** — `(feature, scope, scope_id)`, the key of the `features`
  attribute; scope is `area` / `floor` / `global` (global scope_id is `''`).
- **Provides** — one label, two meanings by location: on an **entity** it is
  domain-grouping shorthand (`Area Provides: Media Player` opts the entity into
  every media feature); on an **area** it generates an MQTT-discovery entity
  (`Area Provides: Audio Mode` → `select.<area>_audio_mode`). Disambiguation is
  by location, never by name.
- **Resolution modes** — per triple: `Leader` (default, the driving leader
  only), `Any` (OR across leaders), `All` (AND), set via
  `<Scoped F> Mode: Leader|Any|All` on the state sensor entity (or subentry /
  config option; labels win).

## State sensor attribute contract (frozen — YAML consumers index into it)

`sensor.labeled_features_state`:

- `feature_meta` — static catalog `{<Feature>: {domain, kind, domain_label}}`
  (17 built-in generic features; see `references/dispatch-loop.md`).
- `leaders` — `{entity_id: {current_value, previous_value,
  last_changed_timestamp}}`.
- `features` — `{feature: {scope: {scope_id: {enabled, mode,
  last_changed_timestamp, triggering_leader}}}}`; `triggering_leader: ''`
  marks manual overrides (exempt from orphan-drop).
- `snapshots` — `{snapshot_name: <mapping>}`, persistence for `mode: restart`
  scripts (written via `Set Snapshot`).

`sensor.labeled_feature_areas_state`:

- `label_map` — `{"<scope_id>||<label>": {scope_id, label, scope, component,
  declaring_area_id, label_data}}`. Trigger surface only; all feature-specific
  resolution happens in `script.labeled_feature_area` at dispatch.

## Where to read next

- `references/label-catalog.md` — the complete label grammar: mandatory,
  Provides, optional/gate labels, default truth function, automation-level
  labels, Script Call Mode.
- `references/dispatch-loop.md` — the shared dispatch loop, Script/Feature/Arg
  labels and substitutions, the generic feature catalog, button mapping
  scripts (Somrig/Styrbar/Symfonisk), Sleep Timeout.
- `references/area-based-features.md` — the area stack: pipeline layers, scope
  semantics, built-in feature catalog, deletion semantics, adding new features.
- `references/production-objects.md` — the production object inventory with
  locations, what the component replaces, and the legacy objects to ignore.

## Source material

- Spec docs (target design): `/home/coder/CuratedForest.com/content/tech/
  home-assistant/label-based-features/` — **read-only, outside this repo**.
- Production YAML (current behavior): `/home/coder/HomeAssistant/
  {configuration,automations,scripts}.yaml` — **read-only, outside this repo**.
- Component contract: `custom_components/labeled_features/AGENTS.md` and
  README `KNOWN_DIVERGENCES`.

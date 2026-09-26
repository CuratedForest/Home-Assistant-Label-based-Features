# Plan: Move Label Based Features YAML into blueprint-shaped packages

## Goal

Extract the entire production Label Based Features YAML system out of
`/home/coder/HomeAssistant/{configuration,automations,scripts}.yaml` into nine
cohesive packages under `/home/coder/HomeAssistant/packages/`, each package one
blueprintable unit (one future automation/script/template blueprint bundle).
Pure relocation: object content moves byte-identical, every `id:` / `unique_id`
/ script key is preserved, so all entity IDs and the frozen attribute contract
are untouched. The custom component (`custom_components/labeled_features`) is
NOT modified and not cut over by this work.

Decisions confirmed with the user:
- **Scope**: production objects only (13). The 12 superseded legacy objects
  stay untouched.
- **Split**: 9 packages — state / dispatch / generics / error_mode / areas /
  somrig / styrbar / symfonisk / sleep_timeout (buttons per device family,
  Generics and Error Mode get their own packages).
- **Co-located non-LF sensors** sharing the LF template block in
  configuration.yaml: decouple them onto their own proper triggers now and
  remove the duplicate `House: Home Count` definition.

## Skills

Code agent must load:
1. `labeled-features` — object inventory, false positives to avoid
   (label-printer stack, hydroponics, sleep_me_switch), attribute contract.
2. `Home Assistant YAML` — package structure + 2026 trigger syntax for the
   re-triggered leftover sensors.
3. `home-assistant-best-practices` — safe-refactoring gate (impact analysis
   before deleting the duplicate sensor; post-change verification).

Not needed: HA Integration Dev (no component changes), ESPHome, Dashboard
Design, API Catalog, Node-RED.

## MCP Servers

- `readonly-global-homeassistant` — live verification: entity states/attrs,
  `homeassistant_validate_config`, traces, system log, registry lookups.
  **Was DOWN during planning** (`authorization header with Bearer token
  required` — see troubleshooting note in `/home/coder/HomeAssistant/AGENTS.md`).
  Retry at implementation; if still down, follow that AGENTS.md fallback:
  file-level validation only, and state explicitly that live verification was
  skipped.
- `readonly-home-kubernetes` — only if ha-mcp pod logs are needed to debug the
  MCP server itself (pod `homeassistant-0`, ns `default`).

## Verified context

- Files inspected (line anchors verified 2026-09-26, will drift):
  - `configuration.yaml` (993 ln): `template:` at 24; entry 1 = areas-state
    sensor 25–187 (comments start 25, `- trigger:` 67); entry 2 = LF
    triggers+conditions 189–266 + `sensor:` 267 with LF sensor 268–693,
    followed by co-located non-LF sensors 695–731 (House: Home Count TWICE —
    695–697 and 729–731, identical; Unavailable Entities 700–713; NHL
    away/home team 715–728); entry 3 = light `scene_night_bathroom_main`
    734–755 (not LF, stays). Packages include at 803–804
    (`homeassistant: packages: !include_dir_named packages`).
  - `automations.yaml` (2912 ln): Leaders `- id: '1776536295923'` 1970–2677;
    legacy `Buttons Bedroom 2` 2678–2721 (stays); Areas `- id:
    'labeled_feature_areas'` 2722–2912 (EOF). Both use modern
    `triggers:`/`actions:` syntax, `mode: queued, max: 50`.
  - `scripts.yaml` (6767 ln), LF block is contiguous 1398–6240:
    follower 1398–2157 | sleep_timeout 2158–2954 | error_mode 2955–3043 |
    generics 3044–4017 | somrig 4018–4450 | entities 4451–4955 |
    area 4956–5468 | styrbar 5469–5708 | symfonisk 5709–6240.
    Next key after block: `label_restore_group` 6241 (label PRINTER — false
    positive, stays).
- Call graph (grep-verified): Leaders→follower/error_mode/send_alert;
  follower→generics/error_mode/send_alert; generics→follower/error_mode;
  Areas→area/send_alert; area→entities/error_mode; somrig/styrbar/symfonisk→
  generics; sleep_timeout→generics/error_mode; error_mode→send_alert.
- No `!secret`/`!include` inside any LF block (grep-verified) → package files
  are standalone-parseable.
- No references to LF objects from outside the LF blocks in the three files,
  nor from scenes.yaml/groups.yaml/other packages/dashboards YAML (grep).
  Storage-mode dashboards + UI registry objects may reference them, but entity
  IDs don't change, so this is safe.
- `script.send_alert` and `script.labeled_feature_button` have NO YAML
  definition anywhere (checkout `.storage` is partial: only
  lovelace_dashboards/lovelace_resources/scheduler.storage) → they are
  UI-registry objects. They are not moved; package headers document them as
  external dependencies. Verify live at implementation.
- `/home/coder/HomeAssistant` is a git repo on `main` (clean except untracked
  `.agents/worktrees/`). Its AGENTS.md governs edits there: packages are the
  preferred home for feature bundles; section-divider comment style;
  attribution header on every NEW file; safe-refactoring gate.
- KNOWN_DIVERGENCES (this repo's README): unaffected — no behavior changes.
- Live HA verification skipped during planning (MCP down).

## Design decisions

1. **Pure cut-and-paste.** Object bodies move byte-identical; ids, aliases,
   unique_ids, modes, fields, descriptions unchanged. Only additions are
   package-file headers (attribution + divider comments + dependency notes).
   Consequence: the Areas automation's description still says the sensor is
   "computed in configuration.yaml" — left stale deliberately (cosmetic; any
   content edit is a parity risk). Flagged as optional follow-up.
2. **9 packages = 9 future blueprint bundles.** Dependency edges are intrinsic
   and documented in package headers (a blueprint would declare them the same
   way): state ← dispatch ← {generics, error_mode}; areas ← state(areas
   sensor)+error_mode; buttons/sleep ← generics.
3. **Entity identity is preserved by id.** Leaders automation id
   `'1776536295923'`, Areas id `'labeled_feature_areas'`, template
   `unique_id: labeled_feature(s|_areas)_state`, script keys — all carried
   over verbatim, so registry entities survive the move. HA merges package
   definitions with `automation: !include automations.yaml` /
   `script: !include scripts.yaml`, which is why removal from the old files
   MUST land together with the new packages before any reload/restart.
4. **Leftover sensors get real triggers** (user-approved): each becomes its
   own trigger-based template entry in configuration.yaml, sensor bodies
   byte-identical. Duplicate `House: Home Count` removed after live impact
   check.
5. **Full restart, not reload**, after the move — trigger-based template
   sensors have restore-from-recorder boot paths already designed for it;
   restart avoids partial-reload edge cases across 3 integrations.
6. **UI-registry objects stay**: `Labeled Feature Button` script and
   `script.send_alert` cannot be YAML-ized from here; if these packages ever
   become blueprints, those two are the manual-import pieces.

## Package map

| New file (`/home/coder/HomeAssistant/packages/`) | Contents (source → lines) |
|---|---|
| `package_labeled_features_state.yaml` | `template:` — Areas State sensor (config 25–187) + Features State sensor (config 189–266 triggers/conditions + 267–693 sensor) |
| `package_labeled_features_dispatch.yaml` | `automation:` Leaders (auto 1970–2677); `script:` follower (scripts 1398–2157) |
| `package_labeled_features_generics.yaml` | `script:` generics (scripts 3044–4017) |
| `package_labeled_features_error_mode.yaml` | `script:` error_mode (scripts 2955–3043) |
| `package_labeled_features_areas.yaml` | `automation:` Areas (auto 2722–2912); `script:` area (scripts 4956–5468) + entities (scripts 4451–4955) |
| `package_labeled_features_somrig.yaml` | `script:` somrig (scripts 4018–4450) |
| `package_labeled_features_styrbar.yaml` | `script:` styrbar (scripts 5469–5708) |
| `package_labeled_features_symfonisk.yaml` | `script:` symfonisk (scripts 5709–6240) |
| `package_labeled_features_sleep_timeout.yaml` | `script:` sleep_timeout (scripts 2158–2954) |

## Changes (ordered)

Working tree for edits is `/home/coder/HomeAssistant` (a separate repo — the
user explicitly authorized these edits; follow that repo's AGENTS.md, not this
repo's "reference only" default).

### Phase 0 — pre-flight
1. Retry `readonly-global-homeassistant` MCP (`get_system_info`). If down,
   record it and proceed file-first; live checks then happen post-restart.
2. In `/home/coder/HomeAssistant`: `git checkout -b
   move-label-based-features-to-packages`.
3. (Live, if MCP up) Snapshot for later comparison: state + attribute keys of
   `sensor.labeled_features_state` and `sensor.labeled_feature_areas_state`;
   enabled-status of the 2 automations + 9 scripts; resolve the duplicate
   House: Home Count — find which entity_id the second definition owns
   (expect `sensor.house_home_count_2`) and run reference/impact analysis on
   it (`analyze_entity` / `find_references`). If anything references the
   duplicate's entity, KEEP the second copy and note it.

### Phase 1 — create the 9 packages (files under /home/coder/HomeAssistant/packages/)
Each file: attribution block required by the HA repo AGENTS.md, then a
section-divider comment header (house style) naming the subsystem, its
contents, and its package dependencies (incl. "alert tier calls
script.send_alert which is defined outside these packages" on the error_mode
package; "Labeled Feature Button script is UI-managed" note on the
dispatch/buttons packages). Then the objects, byte-identical:

4. `package_labeled_features_state.yaml`
5. `package_labeled_features_dispatch.yaml`
6. `package_labeled_features_generics.yaml`
7. `package_labeled_features_error_mode.yaml`
8. `package_labeled_features_areas.yaml`
9. `package_labeled_features_somrig.yaml`
10. `package_labeled_features_styrbar.yaml`
11. `package_labeled_features_symfonisk.yaml`
12. `package_labeled_features_sleep_timeout.yaml`

### Phase 2 — remove from the source files (same commit as Phase 1)
13. `automations.yaml` — [MODIFY] delete lines 1970–2677 (Leaders) and
    2722–2912 (Areas). Everything else untouched (incl. legacy Buttons
    Bedroom 2 at 2678–2721).
14. `scripts.yaml` — [MODIFY] delete lines 1398–6240 (all nine LF scripts).
15. `configuration.yaml` — [MODIFY] from the `template:` section delete lines
    25–693 (both LF entries incl. their comment blocks, triggers, conditions,
    LF sensor) and restructure the five leftover sensors into their own
    entries, bodies byte-identical, keeping `default_entity_id`s:
    - `House: Home Count` (ONE copy; delete the duplicate per Phase 0
      findings): `trigger: event` `event_type: state_changed` + template
      condition `trigger.event.data.entity_id is defined and
      trigger.event.data.entity_id.startswith('person.')` (robust to roster
      changes; alternative: explicit person entity list from the registry).
    - `Unavailable Entities`: `trigger: time_pattern` `minutes: "/1"`
      (matches the documented once-per-minute intent in
      packages/package_unavailable_entities.yaml; Grafana's
      `update_every_minute` attribute keeps working).
    - NHL `away_team` + `home_team` (one shared entry): `trigger: event`
      `event_type: state_changed` + condition `trigger.event.data.entity_id
      == 'sensor.nhl_sensor'` (catches attribute-only updates too).
    - Add divider comments per house style. The `- light:` entry (734–755)
      and everything outside `template:` stay untouched.

### Phase 3 — validate & cut over
16. Parse-check every new package file standalone (no !secret/!include
    inside, so `python3 -c "import yaml,sys; yaml.safe_load(open(f))"` per
    file suffices) and re-parse the three edited source files.
17. `homeassistant_validate_config` (MCP). If MCP still down: shell fallback
    `check_config` if the container/host allows it; otherwise state that only
    syntax-level validation was possible.
18. Full HA restart (user action or via MCP if available).
19. Post-restart verification (MCP; paste evidence):
    - All 13 entities exist with unchanged entity_ids; automations' enabled
      flags match the Phase 0 snapshot; no "duplicate id"/"already exists"
      entries in `manage_system_log`.
    - `sensor.labeled_features_state` carries `feature_meta` (17 entries),
      `leaders`, `features`, `snapshots`; `sensor.labeled_feature_areas_state`
      carries `label_map`; values match the Phase 0 snapshot.
    - Leftover sensors update on their new triggers: house_home_count after a
      person state change (or verify render), unavailable_entities within ~1
      min, NHL teams on nhl_sensor updates.
    - Smoke: a natural (or induced) leader state change produces a
      `labeled_feature_leaders` trace that completes without error; the
      `labeled_feature_areas` start-time re-publish trace is clean.
20. Commit on the branch (conventional message, e.g. `refactor(packages):
    move label-based features into blueprint-shaped packages`). Do not merge
    to main — that's the user's decision.

### Phase 4 — doc sync in THIS repo
21. `skills/labeled-features/references/production-objects.md` — [MODIFY]
    update the location tables: dispatch-layer objects now live in
    `packages/package_labeled_features_*.yaml`; state sensors in
    `package_labeled_features_state.yaml`; re-anchor line numbers as
    "see package files"; note send_alert/Button remain UI-registry objects.
22. `skills/labeled-features/SKILL.md` — [MODIFY] update the
    implementation-status table rows that point at
    `/home/coder/HomeAssistant/automations.yaml` / `scripts.yaml` to the new
    package paths.

## Rollback

`git -C /home/coder/HomeAssistant checkout main -- .` (or revert the commit)
+ HA restart. Entity IDs never changed, so registry/dashboards/consumers are
unaffected either way.

## Risks & open questions

- **HA MCP down during planning** — duplicate-sensor ownership, send_alert /
  Button script existence, and automation enabled-flags could not be
  verified live. Phase 0/3 carry the checks forward; if MCP stays down, the
  implementer must say live verification was skipped (HA repo AGENTS.md
  fallback).
- **Root AGENTS.md of the labeled_features repo says "Never edit
  /home/coder/HomeAssistant"** — overridden by the user's explicit request;
  edits happen in the HA config repo under THAT repo's AGENTS.md.
- **Stale location text** in the Areas automation description
  ("computed in configuration.yaml") and in this repo's README migration
  section — deliberately untouched (pure-move rule); optional follow-up.
- **Component cutover is NOT part of this plan** — the template sensors keep
  owning the production entity IDs from inside the state package; README
  migration order still applies later.
- Optional follow-ups (out of scope): consolidate the Unavailable Entities
  sensor into the existing `packages/package_unavailable_entities.yaml`;
  delete the 12 superseded legacy objects after confirming registry-disabled
  status.

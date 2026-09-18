# Production Objects & Legacy Inventory

Verified against `/home/coder/HomeAssistant/{configuration,automations,
scripts}.yaml` on 2026-09-17. Line numbers drift as the files change — treat
them as approximate anchors, and re-verify before relying on them.

## Production objects (the live system)

### State layer — now the custom component (not yet cut over)

| Object | Legacy implementation | Component replacement |
|---|---|---|
| Labeled Feature State | trigger-based template sensor, `configuration.yaml` ~214–693, `sensor.labeled_features_state` | `sensor.<prefix>s_state` (`sensor.py` + `coordinator.py`) |
| Labeled Feature Areas State | trigger-based template sensor, `configuration.yaml` ~67–187, `sensor.labeled_feature_areas_state` | `sensor.<prefix>_areas_state` |
| Error Handling | `script.labeled_feature_error_mode`, `scripts.yaml` ~2920–3008 | component `errors.py` + `labeled_features.error_mode` action — **the YAML script stays**; the scripts keep calling it |

Cutover status: the template sensors still own the production entity IDs.
Migration order lives in README → "Migration from the template sensors".

### Dispatch layer — YAML, unchanged consumers

| Object | File | Lines (approx) | Notes |
|---|---|---|---|
| Labeled Feature Leaders (automation) | automations.yaml | ~1970–2677 | triggers on `features` attribute; `mode: queued, max: 50`; reads `Error Mode:` from its own labels |
| Labeled Feature Areas (automation) | automations.yaml | ~2722–2912 | triggers on `label_map`; removes before adds |
| Labeled Feature Follower (script) | scripts.yaml | ~1398–2157 | `parallel, max 50` |
| Labeled Feature Generics (script) | scripts.yaml | ~3009–3982 | `parallel, max 50`; includes Set Feature / Set Snapshot branches |
| Labeled Feature Area (script) | scripts.yaml | ~4921–5433 | `parallel, max 100` |
| Labeled Feature Entities (script) | scripts.yaml | ~4416–4900 | `parallel, max 100`; 40 fields |
| Labeled Feature Somrig (script) | scripts.yaml | ~3983–4415 | |
| Labeled Feature Styrbar (script) | scripts.yaml | ~5434–5673 | |
| Labeled Feature Symfonisk (script) | scripts.yaml | ~5674–6205 | |
| Labeled Feature Sleep Timeout (script) | scripts.yaml | ~2158–2919 | `mode: restart`; contains diagnostic `system_log.write` blocks marked "Remove after confirming the fix" |
| Labeled Feature Button (script) | **not in scripts.yaml** | — | UI-managed (HA script registry). Verify against the live instance before documenting or editing |

`script.send_alert` (used by the error tiers) is defined outside scripts.yaml.

## Legacy objects (superseded — do not extend)

Enable/disable state lives in the HA script/automation **registry** (UI), not
in the YAML — none of these are flagged disabled in the files themselves.
Anything labeled-feature-ish not in the production list above is legacy.
Disabled ones can be ignored outright.

Automations (automations.yaml):

| Alias | Lines | Superseded by |
|---|---|---|
| Audio: Follow The Leader | ~254–319 | Leader/Follower labels + Leaders automation |
| Audio: Trigger Night | ~722–743 | house-mode leader features |
| Audio Triggers: Night | ~744–760 | same (duplicate subset) |
| Area: Pause Follow the Leader | ~804–881 | Media Play/Pause features |
| Audio: Pause Follow The Leader (Better?) | ~882–976 | same (iteration) |
| Area Leader Device Control (Dep) | ~1746–1794 | `automation.labeled_feature_leaders` (direct predecessor) |
| Buttons Bedroom 2 | ~2678–2721 | button feature-leader wiring (calls the old `script.labeled_area_action` family) |

Scripts (scripts.yaml):

| Alias | Lines | Superseded by |
|---|---|---|
| Audio: Play Area Mood (`audio_mood_play_in_area`) | ~203–225 | leader/generics stack (contains a corrupted `room_mood: '[object Object]'` variable) |
| Audio: Area Based Media Actions | ~226–241 | generics media features |
| Audio Mood: Morning/Afternoon/Evening/Night | ~151–202 | legacy audio-mood chain |
| Sensors: Area Manifests | ~1325–1397 | `labeled_feature_area` `Manifest` branch (creates the identical `sensor.area_manifest_<area>`) |

## Not labeled-features (keyword false positives — leave alone)

- **Label printer stack** — `print_label`, `label_restore_group`, the
  `label-printer` dashboard, rest sensors/commands: physical Brother P-Touch
  printer.
- **sleep_me_switch family** (~26–150): laptop media controls, unrelated to
  Sleep Timeout.
- **Hydroponics** (`dose_nutrient_v2`, `water_supply_*`,
  `calibrated_values_initalize_helpers_v2`, `nutrient_dosing_*`): label-driven
  but a separate nutrient-dosing/calibration subsystem.
- House Mode day/night automations use label **targets** but are separate
  wiring; the labeled-features equivalent is leader labels on
  `input_select.house_mode`.
- `Sensors: Area Manifests trigger` automation (~1795–1856) belongs to the
  legacy area-manifest system (`type_*` labels) that the Areas stack
  supersedes.

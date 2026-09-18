# The Dispatch Loop, Generics, Buttons, and Sleep Timeout

Source: the "Running Custom Scripts, Automations, and Scenes" spec doc.
All of this is still YAML (`/home/coder/HomeAssistant/scripts.yaml` +
`automations.yaml`) — the component only owns the state sensors.

## The Dispatch Loop

**One execution loop, shared by Leaders and Followers.** Both
`automation.labeled_feature_leaders` (against the leader's labels) and
`script.labeled_feature_follower` (against the follower's labels) build an
ordered list of *action items* and walk one `repeat:`. The only difference:
the implicit `feature` item fans out to followers on a Leader, and performs
the direct entity action on a Follower.

1. **Sort features** alphabetically (deterministic: `Day` before `Night`).
2. **Build the action list** per feature from labels. Two kinds:
   - `script` — from `<F> [Enable|Disable] Script <tag>: <ref>` (replacement:
     drops the implicit feature item) or `<F> [Enable|Disable] Extra Script
     <tag>: <ref>` (additive). `<ref>` may be `script.*`, `automation.*`, or
     `scene.*`.
   - `feature` — the implicit one per feature, or `<F> [Enable|Disable]
     [Extra] Feature <tag>: <other_feature>` (empty value = current feature).
   - Tags are single words (no spaces; use `-`/`_`).
   - **Leader shorthand:** a label `<F>: <state_value>` (no keyword between
     feature and colon) is an implicit-feature item emitted when the leader's
     `current_value` matches `<state_value>`; scoped to the matching feature's
     iteration only.
3. **Sort items**: primary key tag (lexicographic, no-tag last), secondary key
   variant (`Enable` → normal → `Disable`).
4. **Filter**: drop `Enable` items when `leader_enabled` is false; drop
   `Disable` items when true; normal + implicit always kept.
5. **Execute**:
   - `script` items: `automation.*`/`scene.*` → plain action; `script.*` no
     args → plain action with the std fields; `script.*` with args →
     `script.turn_on` with `variables:`. Args validated against the target's
     declared fields (invalid → Error Mode).
   - `feature` items: **Leader** → resolve followers (`Follower:` +
     `Provides:` resolver) and call `script.labeled_feature_follower` once per
     follower. **Follower** → direct entity action (bare value, Enable/Disable
     value, Toggle, or implicit on/off per `follower_enabled`); no-op when the
     state already matches.
6. **Error Mode** after each iteration: `silent` no-op / `log`
   `system_log.write` / `alert` `script.send_alert` / `stop` log + halt this
   feature's loop (outer loop continues). All call sites use
   `continue_on_error: true`.

## Passing arguments to scripts

- `<F> [Enable|Disable] Arg <tag> <field>: <value>` — args pool by tag +
  variant; every Script/Extra Script item with the same tag receives them.
- `<field>` must be declared by the target script, or be a **standard
  pass-through field** (added automatically when declared): `feature` /
  `leader_feature`, `scope` / `scope_id`, `follower_entity_id` /
  `leader_entity_id`, `leader_enabled`, `toggle`.
- **Substitutions:** a value matching `^[A-Za-z_][A-Za-z0-9_]*\.` walks the
  state sensor's attributes: `leaders.current_value` (the triggering leader is
  spliced in as the first key), `features.Night.floor.first_floor.enabled`,
  `feature_meta.Lights Off.domain`. Empty segment (`..`) = literal `''` key
  (global scope_id). Anything else is a literal string.

## Labeled Feature Error Mode (YAML helper)

`script.labeled_feature_error_mode` — fields `error_mode` (default `log`),
`message` (required), `source` (default `Labeled Feature`), `severity`
(default `medium`). Tiers: silent no-op; log → `system_log.write` warning;
alert → `script.send_alert`; stop → error log and **the caller** must follow
with its own `stop: error: true`. The component's `errors.py` mirrors this for
its own code paths and exposes `labeled_features.error_mode`; the YAML scripts
keep their script version — do not swap them.

## Labeled Feature Generics

`script.labeled_feature_generics` — the generic feature dispatcher. Called with
`feature: <FeatureName>` (+ `scope`, `scope_id`, `follower_entity_id`,
`leader_entity_id`, `leader_enabled`, `toggle`, `error_mode`,
`exclude_feature` — defaults to `feature`; mapping scripts thread the leader's
feature name through so Exclude keys on the leader).

Resolution: scope set (`area_entities` + device entities / floor union / none)
→ label-resolved `(scope-prefix)Follower: <F>` in scope → minus
`(scope-prefix)<F> Exclude: True` → if empty, domain fallback (entities of the
feature's default domain in scope, minus excluded) → if still empty and no
fallback domain, Error Mode.

**`toggle: true`** — per-entity, not aggregate: evaluate currently-enabled via
the same truth function (Enable/Disable labels → default truth → Invert), then
call the follower with the opposite `leader_enabled` and `toggle: false`. No
per-domain toggle services.

### Generic feature catalog (the 17 `feature_meta` entries)

| Feature | Domain fallback | Action (toggle=false) | toggle=true |
|---|---|---|---|
| Media Toggle/Play/Pause | `media_player` (most-recently-active) | play_pause / play / pause | play_pause |
| Media Next / Previous | same | next / previous track | Error Mode |
| Media Seek Back / Forward | same | `media_seek` ±30s; silently falls back to previous/next track when `SUPPORT_SEEK` (bit 2) is clear | Error Mode |
| Volume Up / Down | same | `volume_set` ±0.05 — **stepping** | Error Mode |
| Lights On / Off | `light` | turn_on / turn_off | `light.toggle` |
| Lights Up / Down | `light` | turn_on `brightness_step_pct` ±10 — **stepping** | `light.toggle` |
| Fan On / Off | `fan` | turn_on / turn_off | `fan.toggle` |
| Fan Up / Down | `fan` | increase/decrease_speed | one-shot (delegates to follower) |

- **Media-player target selection:** every media feature collapses to a single
  most-recently-active player (playing/buffering by `last_changed` desc →
  most recent `last_changed` → first), avoiding double-press toggles and
  volume drift on grouped speakers.
- **Stepping / hold loop** (Volume Up/Down, Lights Up/Down): one-shot without
  `leader_entity_id`; with it, repeat until the leader's state changes
  (500 ms volume / 300 ms lights cadence, 200-iteration cap). Volume uses a
  local accumulator (never re-reads `volume_level` mid-loop — lnxlink-style
  echo lag would race); lights use `brightness_step_pct`.
- **Unknown features** (anything not in the catalog, e.g. `Screen`, `Night`,
  `Ads`) resolve through the Provides resolver and delegate per-entity to
  `script.labeled_feature_follower`. The catalog exists only for non-trivial
  dispatch logic.
- **`Set Snapshot`** catalog entry: writes
  `sensor.labeled_features_state.snapshots[<snapshot_name>]` via the
  `labeled_feature_snapshot_set` event (empty payload deletes). Persistence
  surface for `mode: restart` scripts.
- **`Set Feature`** catalog entry: writes a manual override into `features`
  via the `labeled_feature_set` event (`target_feature`, `scope`, `scope_id`,
  `enabled`). Sticky until a leader mapped to the same triple changes. The
  component also exposes validated `labeled_features.set_feature` /
  `set_snapshot` actions.

## Button mapping scripts

One per device family; they translate raw events + contextual state into
`labeled_feature_generics` calls and never run service calls directly.

Standard wiring on the button event entity:

```
Feature Leader
Area Leader: <button_feature_name>
Area <button_feature_name> Script: script.labeled_feature_<family>
Area <button_feature_name> Arg feature: leaders.current_value
```

| Script | Devices | Notes |
|---|---|---|
| `labeled_feature_somrig` | IKEA Somrig / E2123 dots | `N_*` events (`dots_N_*` normalized); branches on `media_playing`; `1_short_release` Lights Off is floor-scoped; long-press stepping forwards `leader_entity_id` |
| `labeled_feature_styrbar` | IKEA STYRBAR | lights-only (`on`/`off`/`brightness_move_*`); `arrow_*` are TODO no-op stubs |
| `labeled_feature_symfonisk` | SYMFONISK Gen 2 | transport keys global; volume taps = area lights, holds = global volume when playing; `dots_*` force `toggle: true` (Screen, TV Input, Bright, Ads, Night, Accent) |

`Labeled Feature Button` is a **UI-managed script** (HA script registry, not in
`scripts.yaml`) — check the live instance before documenting or editing it.

To add a new family: new `script.labeled_feature_<family>` accepting the
standard fields, `choose:` on raw event names, call generics per dispatch,
wire with the pattern above.

## Labeled Feature Sleep Timeout

`script.labeled_feature_sleep_timeout` — `mode: restart`, no companion
automation; cancellation is in-script via interruptible waits.

- **Gate:** `should_run = Night.enabled AND Media Playing.enabled`, both read
  fresh from the state sensor per invocation (`leader_enabled` ignored).
- **Re-trigger prelude** (when a fade snapshot is in flight): stepping events
  (`long_press|long_release|hold|_move_` in the leader's current value) →
  re-baseline the snapshot to the current volume; discrete events → restore
  the snapshot and keep it as the baseline (no re-read — echo lag would
  corrupt it).
- **Fade sequence** (gate true): wait `sleep_timeout_minutes` (15) → halve
  volume → wait 1m → "mute" via `volume_set: 0` → wait 1m → silent hold
  (seek-back 30s × 20 @ 0.5s when `SUPPORT_SEEK`; plain delay otherwise —
  deliberately **no** track-skip fallback here) → restore volume → pause
  (guarded on `SUPPORT_PAUSE`, with optional `pause_fallback` entity) →
  restore again → clear snapshot.
- **Step 1c screen-off piggyback:** when the leader's event matches
  `screen_off_event` (default `1_short_release`) and Night passes, dispatch
  `screen_off_feature` (default `Screen`) with `leader_enabled: false`.
- Snapshot persists in `snapshots.sleep_timeout` (never in the script's own
  `variables:` — those reset on restart).
- Target player resolves from the Media Playing triple's `triggering_leader`
  unless the `media_player` field overrides it.

# Model Comparison: `labeled_features` custom component (7 Agent Manager sessions)

Seven Agent Manager worktree sessions each produced the same Home Assistant custom component, `custom_components/labeled_features/`: a label-driven "features" state layer that replaces two legacy Jinja trigger-based template sensors (`sensor.labeled_features_state` + `sensor.labeled_feature_areas_state`). All seven share the same core label grammar (`[Area |Floor ]Leader: <F>`, `[Area |Floor ]Provides: <F>`, `<F> Enable:/Disable:/Increasing:/Decreasing:/Invert:`, `<F> Mode: Leader|Any|All`), the same 17-entry `FEATURE_META` catalog, the same two-sensor output, and the same two legacy bus events (`labeled_feature_set`, `labeled_feature_snapshot_set`). They differ in architecture, config surface, services, robustness, and testing.

## Model ↔ branch mapping (from the Agent Manager worktrees)

| Model | Branch | Worktree session name | Screenshot diffstat* |
|---|---|---|---|
| **qwen3.6 27b** | `ha-label-based-features-component-v3` | "qwen3.6 27b Build labeled_features component" | ↓2 ↑7 +2277 |
| **Kimi k3** | `claude-testing-component-creation` | "kimi k3 Claude Testing Component Creation" | ↓1 +3032 −642 |
| **Fable** | `claude-testing-component-creation-v2` | "or fable Claude Testing Component Creation…" | ↓1 +2937 −437 |
| **qwen3.7 max** | `claude-testing-component-creation-v3` | "or qwen3.7 max Claude Testing Component …" | ↓1 +1374 −789 |
| **Opus 4.7 (pt-2)** | `testing-component-creation-pt-2` | "Opus 4.7 Testing Component Creation Pt. 2" | ↓1 +3850 −931 |
| **Opus 5** | `testing-component-creation-pt-2-v2` | "or Opus 5 Testing Component Creation Pt. 2 …" | ↓1 +5469 −937 |
| **Opus 4.7 (pt-2-v3)** | `testing-component-creation-pt-2-v3` | "or Opus 4.7 Testing Component Creation Pt. …" | ↓1 +3879 −888 |

\* Diffstats from the screenshot cover **all** repo files (README, LICENSE, hacs/manifest/strings JSON, etc.); the line counts in this report are Python-only and will not match them.

Notes:
- `ha-label-based-features-component-v4` (**llama**) and a fourth pt-2 sibling (`testing-component-creation-pt-2-v4`) exist in the worktree list but were not in the requested set.
- Naming trivia: despite the branch names, the "claude-testing-component-creation" line was built by **Kimi k3, Fable, and qwen3.7 max** — no Claude model touched it. The pt-2 line is the one actually built by Opus models.
- Both pt-2 and pt-2-v3 are **Opus 4.7**; they are disambiguated below as **Opus 4.7 (pt-2)** and **Opus 4.7 (pt-2-v3)**.

Lineage used below: the "Claude Component Creation" family = Kimi k3 → Fable → qwen3.7 max; the "Pt. 2" family = Opus 4.7 (pt-2) → Opus 5 → Opus 4.7 (pt-2-v3); qwen3.6 27b stands alone.

---

## 1. Master table

| | qwen3.6 27b | Kimi k3 | Fable | qwen3.7 max | Opus 4.7 (pt-2) | Opus 5 | Opus 4.7 (pt-2-v3) |
|---|---|---|---|---|---|---|---|
| Component lines (py) | 1,680 | 2,403 | 1,874 | 1,244 | 2,236 | 2,574 | 1,816 |
| Test lines (py) | 0 | 0 | 1,266 | 0 | 998 | 2,456 | 726 |
| Tests at all | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ | ✅ |
| Architecture | 935-line god-coordinator | engine/coordinator split | engine/coordinator split | 832-line god-coordinator | coordinator package + models | modular (labels/features/areas/routing/errors) | no coordinator; 867-line god-sensor |
| Restore/persistence | ❌ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| Multi-instance | suffix (hazardous) | suffix (services pinned to default) | ❌ single instance | instance_name slug | disjoint labels + entity ids | prefix + event routing | entity ids + unique_id |
| Services | 3 (fire events) | 3 (direct writes, validated) | 1 (`handle_error`, admin) | 1 (`error_mode`) | 1 (`report_error`) | 3 (validated, instance routing) | 2 (re-fire events) |
| Repairs issues | ❌ | ✅ self-clearing | ✅ (entity-id collision) | ❌ | ❌ | ❌ | ✅ (stop tier; broken clear) |
| Diagnostics | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Config subentries | ❌ | ✅ (leader/provides/mode) | ❌ | ❌ | ❌ | ❌ | ❌ |
| Reconfigure step | ❌ | ✅ (suffix only) | ❌ | ❌ | ❌ | ❌ | ✅ (all 7 fields) |
| Standout trait | baseline | subentry UI | guardrail caps + enable toggle | regression of its family | managed-label sync | best tests, publication invariants | full reconfigure; HA-less test stubs |

---

## 2. Config flow — what's settable

### qwen3.6 27b
- Config step `user`: `feature_leader_label` (str, default `"Feature Leader"`), `default_error_mode` (select: silent/log/alert/stop, default `log`), `alert_action` (str, default `script.send_alert`), `entity_id_suffix` (str, default `""`, enables multi-instance, dedup check)
- Options flow: `feature_leader_label`, `default_error_mode`, `alert_action` — **functionally inert**: nothing ever reads `entry.options`; form defaults are seeded from `entry.data`, not saved options
- No reconfigure, no subentries, no migration

### Kimi k3
- Config step `user`: `entity_id_suffix` only (normalized/validated: `^_[a-z0-9_]+$`, uniqueness check)
- Reconfigure step: `entity_id_suffix`
- Options flow: `error_mode` (silent/log/alert/stop), `alert_action` (default `script.send_alert`), `alert_severity` (low/medium/high)
- **Config subentries** (unique to this session), each with add + edit steps:
  - `leader`: `entity_id` (entity selector, req), `feature` (req), `scope` (area/floor/global), `enable_value`, `disable_value`, `direction` (none/increasing/decreasing/both), `invert` (bool)
  - `provides`: `area_id` (area selector, req), `feature` (req), `scope` (area/floor/none), `component` (select/number/sensor/switch/text/binary_sensor, custom allowed)
  - `mode`: `feature` (req), `scope`, `mode` (leader/any/all)

### Fable
- Config step `user`: **nothing** — a bare Submit form; hard-coded `unique_id=DOMAIN` enforces single instance
- Options flow: `enabled` (bool, default `True`) — applied live without reload; disables coordinators and makes sensors unavailable
- Deliberately minimal ("Part 1"); everything else label-driven

### qwen3.7 max
- Config step `user`: `instance_name` (req, drives unique_id + entity-id slug), `leader_label` (req, default `feature_leader`), `feature_prefix` (optional, default `""` — **dead end-to-end, does nothing**)
- Options flow: `leader_label`, `feature_prefix` (no validation; writes duplicate data into both `entry.data` and `entry.options`)
- No reconfigure, no subentries

### Opus 4.7 (pt-2)
- Config step `user`: `instance_name` (default `"Labeled Features"`, slugified → unique_id), `leader_label` (default `feature_leader`, uniqueness-checked), `features_state_entity_id` (default `sensor.labeled_features_state`, validated + collision/ownership checks), `areas_state_entity_id` (same), `error_mode_default` (select), `script_call_mode_default` (Blocking/NonBlocking)
- Options flow: same six fields minus `instance_name` — **broken in practice** (see per-model observations: `entity_id_taken` false-positive makes saving options on a running instance impossible)
- No reconfigure, no subentries

### Opus 5
- Config step `user`: `name` (default `"Labeled Features"`), `prefix` (default `labeled_feature`, slug-validated, unique, **immutable** — drives both entity ids), `leader_label` (default `"Feature Leader"`), `default_mode` (leader/any/all), `default_script_call_mode` (Blocking/NonBlocking — stored but **functionally unused**), `default_error_mode` (silent/log/alert/stop), `mode_overrides` (multiline, line-validated as `<Scoped F> Mode: Leader|Any|All`), `script_call_mode_overrides` (multiline, validated)
- Options flow: everything except `name` and `prefix`
- No reconfigure, no subentries

### Opus 4.7 (pt-2-v3)
- Config step `user`: `instance_name`, `features_entity_id` + `areas_entity_id` (regex-validated, registry/state collision checks), `leader_label` (default `"Feature Leader"`), `error_mode` (select), `alert_action` (regex-validated `domain.service`), `script_call_mode` (Blocking/NonBlocking — **never read by any runtime code**)
- **Full reconfigure step** (unique): all 7 fields with self-collision exemption — but undermined by an options-shadowing bug (see observations)
- Options flow: `leader_label`, `error_mode`, `alert_action`, `script_call_mode`

### Config surface summary table

| Settable | qwen3.6 | Kimi k3 | Fable | qwen3.7 max | Opus 4.7 (pt-2) | Opus 5 | Opus 4.7 (pt-2-v3) |
|---|---|---|---|---|---|---|---|
| Leader label | ✅ | label const | label const | ✅ | ✅ | ✅ | ✅ |
| Error mode default | ✅ (inert) | ✅ | label-driven | ❌ | ✅ | ✅ | ✅ |
| Alert action/severity | ✅ (inert) | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ (action only) |
| Instance identity | suffix | suffix | n/a (single) | name slug | name + entity ids | name + prefix | name + entity ids |
| Entity-id control | suffix | suffix | fixed legacy ids | name-derived slug | full ids | prefix | full ids |
| Mode defaults/overrides | ❌ | subentry | ❌ | ❌ | ❌ | ✅ | ❌ |
| Script-call-mode | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ (dead) | ✅ (dead) |
| Enable/disable toggle | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Subentries | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Reconfigure | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## 3. What's tested

### qwen3.6 27b — **nothing**
No `tests/`, no pytest config, no CI test job.

### Kimi k3 — **nothing**
No `tests/`. CI runs HACS/hassfest only. (Notably, `engine.py`'s docstring claims it is "testable in isolation" — never exercised.)

### Fable — 1,266 lines (`tests/`: `__init__` 1, conftest 11, test_config_flow 52, test_engine 802, test_init 400)
Approach: real HA harness (`pytest-homeassistant-custom-component`, unpinned) for flow/init tests; **pure HA-free unit tests** for the engine.
- `test_config_flow.py` (3): entry creation, `single_instance_allowed` abort, options toggle persisted
- `test_engine.py` (~25): `eval_leader` precedence table (direction > enable/disable > default truth > invert; case sensitivity; momentary domains), `build_triples` scoping + unresolved-scope errors, `resolve_modes`, `update_features` (flip/timestamp rules, momentary bumps, skip values, any/all folding, orphan drop, manual-override stickiness, invalid scope, legacy-shape tolerance), `update_leaders` (seed/carry/drop, previous chaining, skip sanitization), `update_snapshots`, `build_label_map` (shape, component override, modifier filtering, floor dedup, bare-provides→none, floorless error), `FEATURE_META` parity
- `test_init.py` (13): sensor creation with contractual ids/attributes, leader tick end-to-end, boot-noise gate, manual override event, snapshot events, label_map build + retraction, restore on startup, boot reconcile ordering, disable option, unload, error service lifecycle, guardrail caps (snapshot size/count, field length)
- Gaps: error tiers never asserted (reason the dead `ErrorStop` path went unnoticed), entity-id-collision repair issue, `Error Mode:` label resolution, device→area fallback

### qwen3.7 max — **nothing**
No `tests/`, no pytest config. CI is HACS/hassfest only.

### Opus 4.7 (pt-2) — 998 lines (`tests/`: `__init__` 0, conftest 12, test_config_flow 118, test_coordinator_areas 242, test_coordinator_features 328, test_error_handler 115, test_models 82, test_setup_and_restore 101)
Approach: real HA harness; white-box (constructs coordinators directly, calls private methods); `Makefile` + `pytest.ini`.
- `test_config_flow.py` (5): happy path, duplicate leader label, duplicate entity id, invalid entity id, features==areas conflict. **No options-flow test** (hides the live options bug)
- `test_coordinator_areas.py` (10): label_map scopes, component override, modifier filtering, gating, floor dedup, floorless drop, instance isolation
- `test_coordinator_features.py` (13): 17-row `_eval_leader` truth table, manual override (with a pointless bus fire the comment admits does nothing), mode preservation, bad scope, snapshots, device-label exclusion, triple index, orphan reconcile
- `test_error_handler.py` (8): all four tiers, alert payload capture, persistent-notification fallback, registration lifecycle
- `test_models.py` (5): dataclass dict round-trips, restore round-trip, malformed payload tolerance
- `test_setup_and_restore.py` (5): sensors created, service registered, both legacy events flow through, unload removes service — **despite the filename, zero restore tests**
- Gaps: `label_sync.py` entirely untested, no `state_changed` hot-path test, no debounce test, docstrings advertise tests that don't exist

### Opus 5 — 2,456 lines (`tests/`: `__init__` 1, conftest 148, test_areas 160, test_config_flow 184, test_coordinator 204, test_errors 98, test_features 484, test_labels 169, test_publication 300, test_sensor 708)
Approach: real HA harness (PHCC **pinned** `0.13.205`), rich conftest factories, minimal mocking; pure unit tests for `features.py`; `pytest.ini` + `ruff.toml` + `requirements_test.txt`.
- `test_config_flow.py`: creation with data/options split, prefix validation/uniqueness, leader-label required, override validation, options flow (excludes prefix, validates overrides)
- `test_labels.py`: registry semantics (no device-label inheritance, device-area fallback, missing-id tolerance, id-or-name resolution), grouping/provides parsing, scope prefixes
- `test_features.py`: pure unit — truth table, enable/disable semantics, direction precedence, invert, skip values, leader-entry chaining, triple map, mode resolution precedence (sensor label > option override > entry default), fold table, timestamp bump rules, manual entries, carry-forward/orphan rules
- `test_areas.py`: label_map shapes, floor dedup, component override scoping, all 10 modifier keywords excluded
- `test_errors.py`: all tiers incl. alert payload + fallback, `LabeledFeatureStop`, unknown-tier fallback, error-mode resolution precedence
- `test_coordinator.py`: override parsing/validation, debounced reconcile, `config` attribute, diagnostics payload, `error_mode` and `set_snapshot` services
- `test_publication.py` (unique, notable): counts real `state_changed` bus events; exactly-one-write invariants; published attributes are detached copies (`is not` identity); multi-instance routing (ambiguity drop, explicit instance, default-prefix preference); reload stability
- `test_sensor.py`: full-stack — legacy + prefixed entity ids, state values, triple flips with scope resolution, boot gate, button re-trigger bumps, `_initial_press` skip, leader tracking, modes via label and via option (and label-beats-option), manual write shapes, orphan drop, label_map reconcile after start, attribute restore across restart, event routing, unload, options reload
- Gaps/flaws: one **vacuous test** (timestamp compared against itself via `pytest.approx`), unknown-instance routing path, unload-failure branch, end-to-end `default_error_mode` behavior

### Opus 4.7 (pt-2-v3) — 726 lines (`tests/`: conftest 155, test_error_handler 23, test_evaluator 264, test_label_parser 151, test_sensors_ha 133; no `__init__.py`)
Approach: two-tier — pure unit tests runnable **without HA installed** (conftest injects ~20 stub `homeassistant.*` modules into `sys.modules` when real HA is absent); HA harness tests gated by `importorskip`, explicit `@pytest.mark.asyncio` (no pytest config file).
- `test_label_parser.py`: leader/provides/mode parsing, scope prefixes, modifier-keyword rejection, component override, enable/disable/invert/direction matchers (omits the `Static` keyword)
- `test_evaluator.py`: default truth (case rules), enable/disable, increasing direction (no decreasing tests), invert ordering, fold modes, mode resolution
- `test_error_handler.py`: only the `_issue_id` hash helper — **the entire tier routing/alert/Repairs logic is untested**
- `test_sensors_ha.py`: smoke-level — features sensor bootstrap (**one test is broken as written**: asserts `feature_meta["Night"]`, a key that doesn't exist → `KeyError`, and the `or True` makes it tautological anyway), manual override write, snapshot set/delete, areas bootstrap, start-event no-crash
- Gaps: **zero config-flow tests** (the most regex-heavy code), zero service tests, the entire `_process_state_changed` state machine, skip values, orphan pruning, restore round-trip, label_map with real floors

### Test summary table

| | qwen3.6 | Kimi k3 | Fable | qwen3.7 max | Opus 4.7 (pt-2) | Opus 5 | Opus 4.7 (pt-2-v3) |
|---|---|---|---|---|---|---|---|
| Test lines | 0 | 0 | 1,266 | 0 | 998 | 2,456 | 726 |
| Config flow | — | — | ✅ basic | — | ✅ good | ✅ thorough | ❌ none |
| Pure logic units | — | — | ✅ deep (engine) | — | ✅ good (eval/models) | ✅ deep (features/labels) | ✅ deep (parser/evaluator) |
| Error tiers | — | — | ❌ | — | ✅ | ✅ | ❌ (only id hash) |
| End-to-end (real harness) | — | — | ✅ | — | ✅ partial | ✅ extensive | ⚠️ smoke only; 1 broken test |
| Restore | — | — | ✅ | — | ❌ (despite filename) | ✅ | ❌ |
| Publication/state-write behavior | — | — | ❌ | — | ❌ | ✅ (unique) | ❌ |
| Harness | — | — | PHCC (unpinned) | — | PHCC | PHCC (pinned) | PHCC + HA-less stubs |

---

## 4. Features found in other sessions but missing here / unique to each session

### qwen3.6 27b
**Missing (present elsewhere):**
- Any tests (Fable, all three Opus sessions)
- Restore/persistence of leaders/features/snapshots (Kimi k3, Fable, Opus family)
- Subentries (Kimi k3), reconfigure (Kimi k3, Opus pt-2-v3), diagnostics (Opus 5)
- Repairs issues (Kimi k3, Fable, Opus pt-2-v3)
- Guardrail caps on snapshots/manual overrides (Fable)
- Multi-instance event routing (Opus 5); its own multi-instance is actively hazardous (unloading one instance removes the global services for all; every instance applies every `labeled_feature_set` event)
- Enable/disable toggle (Fable)

**Unique:** nothing of substance — it is effectively the baseline implementation the others re-architect.

### Kimi k3
**Missing (present elsewhere):**
- Tests (Fable, Opus family); diagnostics (Opus 5); event routing (Opus 5); guardrails (Fable); enable toggle (Fable); managed-label sync (Opus pt-2); full reconfigure (Opus pt-2-v3); explicit entity-id config (Opus pt-2, Opus pt-2-v3)
- Services are pinned to the default (suffix-less) instance — a `_dev`-only setup gets `no_default_instance` errors (Opus 5's routing solves this better)

**Unique:**
- **Config subentries** (leader/provides/mode) — a UI alternative to authoring labels; subentries win on conflict with labels
- **Self-clearing Repair issues** driven by engine error diffs, plus issue cleanup on entry removal (`async_remove_entry`)
- Alert tier raises a repair issue on failure
- Dual write paths (legacy events *and* validated direct services) — Opus 5 has both too, but Kimi's services write directly rather than re-firing events

### Fable
**Missing (present elsewhere):**
- Multi-instance entirely (all others support it); configurable leader label (qwen3.6, qwen3.7 max, Opus family); any entity-id customization; `set_feature`/`set_snapshot` services (qwen3.6, Kimi k3, Opus 5, Opus pt-2-v3 — writes here are event-only); subentries (Kimi k3); reconfigure (Kimi k3, Opus pt-2-v3); diagnostics (Opus 5)

**Unique:**
- **Enable/disable option** that gates processing live without reload
- **Guardrail caps** (`MAX_SNAPSHOTS=50`, 16 KB payload cap, `MAX_MANUAL_FEATURES=100`, 255-char field cap) reported through the error tiers
- Admin-only service registration (`async_register_admin_service`)
- Entity-id-collision repair issue (detects the legacy template sensor still owning the contractual id)
- Options applied **without** an entry reload
- Cheapest `state_changed` handling: synchronous `event_filter` on the bus subscription (others filter after delivery)

### qwen3.7 max
**Missing (present elsewhere):**
- Almost everything: tests, restore, subentries, reconfigure, repairs, diagnostics, caps, routing, enable toggle, error-mode tiers beyond a single service, `entity_registry_updated` listener (mode labels on the sensor don't trigger rebuilds)
- Vs its own family siblings (Kimi k3, Fable): dropped the `engine.py`/`error_handler.py` split and collapsed everything into an 832-line coordinator with **no try/except anywhere**
- No error handling in core logic; the `error_mode` service is the entirety of "tiered error handling" and nothing internal calls it

**Unique:**
- `instance_name`-derived entity ids (`sensor.<slug>_labeled_features_state`) — a naming scheme none of the others use
- Nothing else; reads as a regressed/collapsed sibling of Kimi k3/Fable. Its README describes features (subentries, reconfigure, suffix, error-mode options, restore, `set_feature`/`set_snapshot` services) that **do not exist in the code**

### Opus 4.7 (pt-2)
**Missing (present elsewhere):**
- Diagnostics (Opus 5); event routing (Opus 5); publication invariants (Opus 5); subentries (Kimi k3); guardrails (Fable); enable toggle (Fable); reconfigure (Kimi k3, Opus pt-2-v3); `set_feature`/`set_snapshot` services (qwen3.6, Kimi k3, Opus 5, Opus pt-2-v3 — only `report_error` + legacy events here)

**Unique:**
- **`label_sync.py`** — managed labels (`Error Mode: <mode>`, `Script Call Mode: <mode>`) applied/curated on the features sensor entity, ids persisted in `entry.data`, unbound on entry removal
- Explicit entity-id selection **with state-ownership collision detection** (refuses ids owned by live YAML template sensors) — Opus pt-2-v3 has similar checks; Opus pt-2 does it at setup config time
- `data_version`-driven attribute memoization in the sensor
- Only session with a `Makefile`
- Dataclass models with `to_restore`/`apply_restore` (Opus 5 has dataclasses too, but pt-2's restore model is its own)

### Opus 5
**Missing (present elsewhere):**
- Subentries (Kimi k3); enable toggle (Fable); guardrail caps (Fable); managed-label sync (Opus pt-2); fully explicit entity ids (Opus pt-2, Opus pt-2-v3 — it uses a prefix); reconfigure step (Kimi k3, Opus pt-2-v3)
- `default_script_call_mode`/`script_call_mode_overrides` are settable but functionally dead (nothing acts on them)

**Unique:**
- **`diagnostics.py`** — config-entry diagnostics
- **`routing.py`** — multi-instance event ownership (explicit `instance` field → ownership match → default-prefix fallback; **ambiguous events are dropped with a warning** rather than misapplied)
- **Publication invariants** — every write publishes a detached deep-copied attribute graph; exactly one state write per leader tick (regression-tested by counting bus events)
- `default_mode` + validated multiline `mode_overrides` options
- Label resolution by id *or* display name, deliberately mirroring HA template semantics
- `Follower:` role parsing in the grouping-label regex (vestigial but present)
- Largest, most rigorous test suite (2,456 lines), pinned test deps, `ruff.toml`

### Opus 4.7 (pt-2-v3)
**Missing (present elsewhere):**
- Any coordinator/engine separation — logic is crammed into an 867-line `sensor.py` (all others separate concerns)
- Error-mode **service** (all six others register one; here `handle_error` is internal-only)
- Diagnostics (Opus 5); routing (Opus 5); subentries (Kimi k3); caps (Fable); enable toggle (Fable); label sync (Opus pt-2)
- Meaningful end-to-end tests (Fable, Opus pt-2, Opus 5)

**Unique:**
- **Full reconfigure step** for all seven fields (Kimi k3's reconfigure only edits the suffix)
- Deterministic sha1-based Repairs issue ids on the stop tier with intent to auto-clear (the clear calls are buggy no-ops)
- HA-less test technique: conftest stubs `homeassistant.*` modules so pure unit tests run with no HA install
- Services that validate then **re-fire the legacy events** (single write path) — qwen3.6's services also fire events, but without the schema validation; the "one write path" design is most explicit here
- `alert_action` regex validation in the flow

---

## 5. Obviously dead code

| Model | Dead code found |
|---|---|
| **qwen3.6 27b** | **Options flow is dead end-to-end** (options saved but never read; defaults seeded from wrong place). Unused imports (`DOMAIN`, module-level `DEFAULT_FEATURE_LEADER_LABEL`, `MODE_ANY`, `typing.Any`). Four public coordinator properties bypassed by sensors reading private attrs. Entire `DataUpdateCoordinator` data channel unused (sensors aren't `CoordinatorEntity`s). Unused params (`_event_data`, `_all_leaders`). Unreachable non-dict branch in snapshot service. `handle()` return value never consumed ("stop" tier is a no-op signal). `self._entry` stored but unread in both sensors. |
| **Kimi k3** | `floor_registry` import (self-admitted `# noqa`). `AreasCoordinator.sensor_entity_id` never read. `ISSUE_INVALID_SUBENTRY` const + its translation blocks + its `_KNOWN_ISSUE_KEYS` entry (no code path emits it). `issues.no_default_instance` strings (only ever raised as a `ServiceValidationError`, never a repair issue). `MODE_ANY` const. `EngineError.context` dicts built at every error site, never read. Duplicate `pop` of the entry on unload. |
| **Fable** | `ErrorStop` raise path is dead — every caller passes `raise_on_stop=False`; the parameter, class, and docstring promises around it are dead weight. Unused `_LOGGER` in `__init__.py`. Entity-side restore call is a by-design no-op (coordinator restores earlier; openly documented as fallback). Least dead code of the seven. |
| **qwen3.7 max** | **7 of 9 module-level regexes never used** (inline recompilation won). **`feature_prefix` config option dead end-to-end** (collected, stored, never read). `_all_label_ids()`, `_floor_areas()` never called. `FALSY_STATES` const. `MODIFIER_KEYWORDS` import. `entry_id` attr. `_LOGGER` in both coordinator and `__init__` (nothing logs, ever). Unused `typing.Any`. |
| **Opus 4.7 (pt-2)** | `apply_context()` on **both** coordinators never called (options reload recreates them). Areas sensor's `_handle_coordinator_update` override just calls `super()`. False `__all__`/re-export comment. Unreachable `default_entity_id` fallback in sensor base. Dead test assignments and a pointless event fire in `test_coordinator_features.py`. Several stale docstrings describing behavior that isn't wired (unload unbinding, ConfigEntryNotReady propagation, `hass.data` `"unsub"` key). |
| **Opus 5** | `labels.label_value()` and `labels.has_label()` never called. `MODE_LABEL_VALUES` const (same tuple hardcoded inline in features.py). Redundant `suggested_object_id` property overrides on both sensors (re-implement the HA base-class behavior). `resolve_error_mode`'s scoped-label parameter never passed by production code (only tests exercise it). `default_script_call_mode`/overrides functionally dead ("forward-looking"). |
| **Opus 4.7 (pt-2-v3)** | Empty `if TYPE_CHECKING: pass` block. Unused `LabeledFeaturesConfigEntry` type alias. Unused imports (`floor_registry`, `PROVIDES_MODIFIER_KEYWORDS`, `typing.Any`). `_LOGGER`s with zero log calls. **`parse_mode_label`/`_MODE_RE` dead in production** — `evaluator.resolve_mode` re-implements it (only tests use the parser). **`script_call_mode` dead end-to-end**. `clear_error()` calls guaranteed no-ops (hash inputs never match creation messages). Dead `State.state is None` branch. Unused test imports (`MagicMock`, four registry modules). |

---

## 6. Needless verbosity

| Model | Verdict |
|---|---|
| **qwen3.6 27b** | Yes, heavily. Scope-prefix ternary repeated 4× verbatim; duplicated carry-through loops (inline vs `_carry_through`); nested `setdefault` write pattern ×4 with repeated isinstance-guard boilerplate; 8 identical listener-registration blocks (should be a loop); twin label-resolution routines differing only in registry; options schema restates the user schema field-by-field; dead `last_changed` None-guards; "Generated by aurora…" banner in every file + manifest/hacs metadata. |
| **Kimi k3** | Moderate. Three subentry flows are near-verbatim copies (~200 lines); `_subentries()` and the self-clearing error block duplicated character-for-character between the two coordinators; twin sensor scaffolding; `{"labels": {...}}` single-key wrapper + flat/nested field duplication in `build_label_map` (deliberate legacy shape); defensive `isinstance(Mapping)` re-checks ~9×; hand-maintained `en.json` byte-identical to `strings.json`. |
| **Fable** | Light. `dict(x) if isinstance(x, Mapping) else {}` ~10× (wants a `_as_map` helper); regexes recompiled per call for fixed-prefix matching (could be `startswith`); roundabout scope-prefix re-derivation; manual-event normalization duplicated across coordinator and engine. Leanest of the seven relative to its size. |
| **qwen3.7 max** | Yes. Scope-prefix mapping ×4; nested-dict insertion idiom ×4 (no `setdefault`); double-loop leader rebuild; inline timestamp fallback ×3 despite an existing helper; ~85% identical sensor classes (no shared base); four near-identical registry getters with function-level imports. |
| **Opus 4.7 (pt-2)** | Moderate. `_base_schema` = six near-identical 7-line vol blocks; normalize/build-data logic duplicated verbatim between user and options steps; four parenthesized import statements for sibling helpers (also copied into two test files); sensor base takes params purely to be passed constants (should be class attrs); dict-or-State duck-typing branches no caller exercises; six-key entry dict copy-pasted into four test files (belongs in conftest). |
| **Opus 5** | Light. Six `previous.get(...)` lines for schema defaults (table + comprehension would be 4 lines); `validate_overrides` duplicates the line-iteration loop; allowed-values mappings written 3× across two files; flat + `label_data` duplication (deliberate contract); 3 identical service-registration stanzas. Deliberate duplication is consistently documented as legacy-contract preservation. |
| **Opus 4.7 (pt-2-v3)** | Moderate. 4-line timestamp fallback ×3; `extra_restore_state_data` (including a dynamically defined inner class) duplicated nearly verbatim across sensors; SelectSelector schema blocks duplicated between base schema and options flow; function-local const imports on every error call; wrapper closures where `functools.partial` suffices; redundant nested ternary re-deriving a scope prefix; double `.get()` calls; noise `bool()` casts; duplicated validate/except/re-raise boilerplate in both service handlers (also redundant with schema validation). |

---

## 7. Other observations per model

### qwen3.6 27b
- **Bug:** alert tier can never reach the configured service — passes `"script.send_alert"` as the *domain* with `None` service (must split on `.`); always falls back to a persistent notification
- **Bug:** options flow fully disconnected (nothing reads `entry.options`)
- **Bug:** `float(cv)` crashes with `ValueError` in a `@callback` on non-numeric leader states when direction labels exist
- **Bug:** `Provides` regex `^(Area|Floor|)Provides:` can't match `"Area Provides: X"` (its own documented syntax); component-override grammar inconsistent with it
- **Inconsistency:** full rebuild folds leader mode as `any()` across leaders; incremental path uses only the changed leader's truth — results diverge until next full rebuild
- Multi-instance: services registered globally per entry and removed on any unload; all instances consume all manual-override events
- Sensors aren't `CoordinatorEntity`s, never subscribe, and rely on default polling — undermines the push design (~30 s lag); unbounded attribute dumps risk exceeding HA's ~16 KB attribute guidance
- Raw event-name strings instead of HA constants; blanket `except Exception` in ~8 helpers (ironic given the unused 4-tier error subsystem); `@callback` on a coroutine; O(registry × labels) per state change; missing translation strings for `feature_leader_label`

### Kimi k3
- **Bug:** `update_snapshots` docstring contradicts code (empty *name* doesn't remove; empty *payload* does) — empty `snapshot_name` is a silent no-op
- **Bug:** all three subentry **edit** steps skip the duplicate-unique_id check (add steps have it) — edits can create colliding subentry ids
- **Bug:** `services.yaml` marks `scope` required; schema makes it optional with default `global`
- Label regexes allow whitespace-only feature names (subentry paths guard, label paths don't)
- Subscribes to raw `state_changed` and filters in-handler (Fable's `event_filter` is the better pattern); locally redefines `EVENT_STATE_CHANGED`/`EVENT_HOMEASSISTANT_START` as strings
- No config-entry `unique_id` (hand-rolled duplicate check); `MEASUREMENT` state class on count sensors enrolls them in long-term statistics
- Features never recomputed at start (legacy parity) — restored features can stay stale until the first leader event
- Restore of `label_map` is near-vestigial (live rebuild runs first)

### Fable
- **Bug:** state removal writes spurious `current_value=""` with a fresh timestamp (`""` isn't a skip value)
- **Bug:** `timestamp=0` in a `labeled_feature_set` event silently replaced with now (`or` fallback)
- `services.yaml` says `error_mode` required; schema has it optional — UI/backend mismatch
- Scope vocabulary inconsistent between attributes (`global` in features vs `none` in label_map) — persisted contract, confusing
- `manifest.json` declares `"integration_type": "hub"` (it's a local service); no minimum HA version declared anywhere while using very recent APIs; **unpinned** dev requirements
- `extra_state_attributes` returns the module-level `FEATURE_META` by reference on every write
- Restore implemented twice (coordinator-level + entity-level fallback) — works, documented, but redundant
- Test quality high overall (nice boot-reconcile technique using `CoreState.starting`); weak on error tiers, which is exactly where its dead code hides

### qwen3.7 max
- **README documents a different integration** — wrong domain name, nonexistent services/options/subentries/restore; largest doc/code divergence of the seven
- **Bug:** `feature_prefix` silently does nothing (users can set it; strings describe it; no effect)
- **Bug:** no `entity_registry_updated` listener + sensor doesn't exist at first `_rebuild_all` → `Mode:` labels only take effect after the first leader state change (Any/All silently fold as Leader until then)
- **Bug:** label-*ID* matching for leader detection vs label-*name* matching everywhere else — entering a name that differs from its slugified id yields zero leaders, silently
- **Bug:** unguarded `float(data.get("timestamp"))` crashes the event handler on bad input
- Full rebuild restamps all `last_changed_timestamp`s with `time.time()` → phantom changes for diffing consumers; manual entries immortal in memory (no persistence)
- `_attr_has_entity_name = True` with `_attr_name` but no `device_info`; direct `entity_id` assignment means a registry `_2` suffix silently breaks mode-label lookup
- Options flow duplicates data into `entry.data` *and* `entry.options`, and accepts an empty `leader_label` the user step rejects → a bad options submit yields a silently dead instance after reload
- Subscribes to the entire `state_changed` firehose and filters afterward; no error handling anywhere in core logic

### Opus 4.7 (pt-2)
- **Live bug:** options flow can essentially never save on a running instance — the `entity_id_taken` check excludes only *other* entries' ids, so the entry's own live sensors trip it; no options test exists to catch this
- **Bug:** `_eval_leader` ignores its `current_value` argument for Enable/Disable/default-truth branches (re-reads live state) — contract-misleading port-fidelity hazard
- **Bug:** `apply_restore` wipes `features` on any malformed/partial payload (leaders/snapshots are guarded)
- **Bug:** restore happens *after* first reconcile → orphaned restored entries linger until the next event
- `label_sync` never deletes the registry labels it creates → orphaned `Error Mode: *` labels accumulate
- `list[callable]` uses the builtin instead of `Callable`; `async_config_entry_first_refresh` overridden with `# type: ignore[override]` on a coordinator with no `update_method` (any `async_request_refresh` hits `NotImplementedError`)
- Fixed `notification_id` for alert fallback → alerts overwrite each other
- Sensor names stutter (`"Labeled Features Features State"`); stale strings tell users to reload manually when it auto-reloads
- Test docstrings twice advertise coverage that doesn't exist; `pytest.ini` globally suppresses `DeprecationWarning`s (masks HA API drift); `Makefile hassfest` target is broken as written

### Opus 5
- One **actively misleading test**: timestamp asserted with `pytest.approx(<its own value>)` — can never fail
- **Bug (minor):** `slugify` preserves hyphens, so `my-prefix` passes validation but yields odd object ids; error message promises underscores
- **Bug (minor):** stringly bool on the schema-less event path (`"enabled": "false"` → `True`); the service path is safe
- Docstring invariant "hot path never touches a registry" is contradicted by per-tick `_sensor_labels()` and per-error registry reads; mode overrides re-parsed per tick (could be cached)
- Duplicated constants across modules (`TRIPLE_SEPARATOR` vs `LABEL_MAP_KEY_SEPARATOR`; `"Labeled Features"` vs `"Labeled Feature"` source strings); function-local routing import "to avoid a cycle" that the existing `TYPE_CHECKING` pattern already solves
- HA API usage otherwise exemplary: forward-setups ordering, idempotent service registration with last-entry teardown, debouncer shutdown, `ServiceValidationError`, diagnostics without secrets, wired translation keys, and a docstring trail explaining every legacy-fidelity quirk
- `MEASUREMENT` on count sensors (long-term statistics noise) — a smell shared by all seven sessions

### Opus 4.7 (pt-2-v3)
- **Bug:** reconfigure silently loses to saved options (`{**data, **options}` merge — options win) for the 4 overlapping fields
- **Bug:** entity-id changes via reconfigure don't take effect (registry owns the id once registered) despite "fully overridable" strings
- **Bug:** nondeterministic floor dedup — `set`→`list` conversion + "first wins"
- **Bug:** `clear_error` hashes different messages than issue creation → stop-tier Repairs issues never auto-clear
- **Bug:** one shipped test fails as written (`feature_meta["Night"]` KeyError + tautological `or True`)
- **Bug:** stringly bool coercion on event path; non-dict snapshot payloads silently treated as deletes; boot-noise gate eats legitimate literal `"none"` states (e.g. input_select options)
- Service lifecycle ordering: services registered before platform setup (leak on failure) and removed even if platform unload fails; `exc_info=exc` misuse logs wrong/no tracebacks outside `except` blocks; reconfigure doesn't update `unique_id` → duplicate-guard defeatable after the fact
- Nondeterministic Enable/Disable resolution when multiple Enable labels exist (set iteration + first-match-wins)
- Deep-copies all attributes on **every** state write (O(everything) per tick); global `state_changed` subscription with in-Python filtering; key-order asymmetry between the two maps (`feature||scope||scope_id` vs `scope_id||feature`) is a consumer trap
- Excellent granular unit tests for parser/evaluator; smoke-level everything else; the conftest stub approach is clever but fragile (stub drift would go unnoticed since config_flow/services are never imported by tests)

---

## 8. Synthesis

- **Strongest overall: Opus 5** — most modular architecture, only diagnostics + multi-instance routing, publication-safety invariants, the deepest and most rigorous test suite (2,456 lines), pinned tooling, exemplary HA API usage. Its weaknesses are minor (one vacuous test, dead script-call-mode settings).
- **Strongest engine design: Kimi k3 / Fable** — the pure-functions `engine.py` split is the cleanest separation; Fable pairs it with the only guardrails and an enable toggle but sacrificed multi-instance; Kimi k3 pairs it with the richest config surface (subentries) but shipped zero tests and several real bugs.
- **Most regressed: qwen3.7 max** — collapsed the engine split into a god-coordinator, dropped error handling, tests, and restore, and its README describes features that don't exist. `feature_prefix` is a silent no-op.
- **Opus 4.7 (pt-2)** has good bones (managed-label sync is a genuinely unique capability) but a live options-flow bug makes its options UI unusable, and its test docstrings overpromise.
- **Opus 4.7 (pt-2-v3)** has the only full reconfigure step and the cleverest test-bootstrapping trick, but concentrates everything into an 867-line sensor god-object, ships a broken test, and has the longest bug list relative to its size.
- **qwen3.6 27b** is the unadorned baseline: working core semantics, no tests, no restore, a fully inert options flow, and the alert path broken by an unsplit `domain.service` string.
- Family note: the two Opus 4.7 sessions landed at opposite ends of the quality spectrum (pt-2 = solid but buggy options flow; pt-2-v3 = clever but buggiest), suggesting the v3 *prompt* regressed rather than the model. Similarly, Kimi k3 → Fable improved within the "Claude Component Creation" family while qwen3.7 max regressed from both.
- Common to all: identical 17-entry `FEATURE_META` catalog, identical label grammar, `MEASUREMENT` state class on count sensors (statistics noise), and the legacy contract's `label_data` duplication.

---
---

# Part 2 — Three-way deep dive: Kimi k3 vs Opus 4.7 (pt-2-v3) vs Opus 5

Adds performance, maintenance-cost, ease-of-improvement, and documentation-conformance analysis for the three requested sessions. Conformance is measured against the system documentation at `~/CuratedForest.com/content/tech/home-assistant/label-based-features/` (all 8 pages read; the six `examples.md` files are empty placeholders).

## 2.1 Master table (three-way)

| | Kimi k3 | Opus 4.7 (pt-2-v3) | Opus 5 |
|---|---|---|---|
| Branch | `claude-testing-component-creation` | `testing-component-creation-pt-2-v3` | `testing-component-creation-pt-2-v2` |
| Component lines (py) | 2,403 | 1,816 | 2,574 |
| Test lines (py) | 0 | 726 | 2,456 |
| Architecture | pure `engine.py` + two push coordinators | no coordinator; 867-line god-sensor | modular: labels/features/areas/routing/errors + event-driven coordinator |
| Restore/persistence | ✅ RestoreEntity seeds coordinators | ✅ ExtraStoredData | ✅ restore into coordinator pre-subscription |
| Multi-instance | suffix; services pinned to default instance | entity ids + unique_id | prefix + ownership routing (ambiguity drop) |
| Services | 3 (direct writes, validated) | 2 (validate → re-fire legacy events) | 3 (validated, instance routing) |
| Repairs issues | ✅ self-clearing, cleaned on removal | ✅ stop tier; clear calls broken no-ops | ❌ |
| Diagnostics | ❌ | ❌ | ✅ |
| Config subentries | ✅ leader/provides/mode | ❌ | ❌ |
| Reconfigure step | ✅ (suffix only) | ✅ (all 7 fields; options-shadowing bug) | ❌ |
| Error-mode service | ✅ `handle_error` (doc-field parity) | ❌ internal only | ✅ `error_mode` (doc-field parity) |
| Performance posture | full per-tick re-resolution; firehose | full per-tick re-resolution + per-write deep copy | cheapest hot path (cached metadata, debounce, 1 write/tick) |
| Maintenance cost | high (no tests, duplication) | high (bug debt, god-object, broken test) | low (tests as safety net, docs as spec) |
| Ease of improvement | moderate (pure engine, wide edit surface) | low (god-object blocks most changes) | high (module boundaries + executable spec) |
| Docs conformance | high on state layer; gaps on error-mode labels | medium (core semantics ✓, several defects) | highest (contract pinned by tests) |

## 2.2 Config flow (three-way)

| Settable | Kimi k3 | Opus 4.7 (pt-2-v3) | Opus 5 |
|---|---|---|---|
| Instance identity | `entity_id_suffix` (validated, reconfigurable) | `instance_name` + unique_id `{leader_label}\|{features_entity_id}` | `name` + immutable slug `prefix` |
| Entity-id control | suffix | full ids, regex + collision checks | prefix-derived |
| Leader label | label constant | ✅ (default `"Feature Leader"`) | ✅ (default `"Feature Leader"`) |
| Error mode | ✅ options (+ `alert_action`, `alert_severity`) | ✅ (+ `alert_action`, regex-validated) | ✅ `default_error_mode` |
| Mode defaults/overrides | via `mode` subentries | ❌ | ✅ `default_mode` + validated multiline `mode_overrides` |
| Script-call-mode | ❌ | ✅ (dead — nothing reads it) | ✅ (dead — "forward-looking") |
| Subentries | ✅ leader/provides/mode (add+edit) | ❌ | ❌ |
| Reconfigure | ✅ suffix | ✅ all 7 (shadowed by options — bug) | ❌ |
| Options flow | error-mode trio | 4 fields (no entity ids/name) | all except name/prefix |
| Duplicate protection | suffix check | unique_id abort + entity-id ownership checks | prefix uniqueness |

## 2.3 Tests (three-way)

| | Kimi k3 | Opus 4.7 (pt-2-v3) | Opus 5 |
|---|---|---|---|
| Test lines | 0 | 726 | 2,456 |
| Config flow | ❌ | ❌ (zero tests on the most regex-heavy code) | ✅ thorough incl. options + override validation |
| Pure logic units | ❌ (engine designed for it, never exercised) | ✅ deep: label_parser + evaluator | ✅ deep: features + labels + areas |
| Error tiers | ❌ | ❌ (only `_issue_id` hash) | ✅ all tiers + precedence |
| End-to-end | ❌ | ⚠️ smoke only; **1 test fails as written** | ✅ extensive incl. restore, routing, reload |
| Publication/state-write behavior | ❌ | ❌ | ✅ unique: counts real `state_changed` events, `is not` identity checks |
| Test infra | none | no pytest config; HA-less stub conftest (fragile) | pinned PHCC `0.13.205`, pytest.ini, ruff.toml, rich conftest factories |
| Known defects | n/a | `feature_meta["Night"]` KeyError + tautological `or True`; unused imports in test file | 1 vacuous `pytest.approx(self)` timestamp assertion |

## 2.4 Performance impacts

**Steady-state hot path (per leader state change):**

| | Kimi k3 | Opus 4.7 (pt-2-v3) | Opus 5 |
|---|---|---|---|
| Bus subscription | raw `state_changed`, in-handler filter (whole firehose) | global `state_changed`, in-handler filter by cached leader set | global `state_changed`, in-handler filter by cached leader-id set |
| Per-tick registry work | **O(all leaders)** — `_recompute` re-resolves label names + area/floor for every leader on every tick | **O(all leaders)** — `_compute_triples` iterates every leader + labels + area/floor per tick; `_sensor_labels()` per tick | **O(1)-ish** — per-leader metadata cache built at debounced reconcile; only `_sensor_labels()` read per tick (cached singletons); overrides re-parsed per tick (trivial) |
| Feature re-evaluation | incremental (only triples the changed leader feeds; any/all re-evaluate others live) | incremental (same shape) | incremental (same shape) |
| State writes per tick | 1 (coordinator push) | 1 | exactly 1 (tested invariant) |
| Attribute copy cost | engine builds fresh trees at recompute (safe publication) | **deep copy of all attributes on every write** (incl. static `feature_meta`) | deep-copied snapshot tree per write (deliberate, tested) |

**Registry-change bursts:** Opus 5 debounces (1.0 s, immediate) — a startup/bulk-edit burst collapses to one reconcile. Kimi k3 refreshes only the leader cache on registry events (cheap, no recompute) but its AreasCoordinator rebuilds `label_map` un-debounced. pt-2-v3 does full `label_map` rebuilds un-debounced.

**Boot:** Kimi k3 is cheapest at boot — no features recompute at start (restored attributes served until first tick, documented legacy parity). Opus 5 restores then reconciles. pt-2-v3 restores + seeds missing leaders from live states on add.

**Multi-instance scaling:** Kimi k3 — N instances each on the firehose + every instance applies every manual-override event (no routing: double-apply with a `_dev` instance). pt-2-v3 — N sensors each on the firehose, each filtering by its own leader set. Opus 5 — routing adds ownership checks per untargeted event (small-N cheap); ambiguous events dropped with a warning instead of misapplied.

**Shared (all three):** unbounded attribute dumps (`features`/`leaders`/`snapshots`/`label_map`) into the state machine on every write — the documented design makes attributes the contract surface, so recorder rows grow with features × scopes; `MEASUREMENT` state class on the two count sensors adds long-term-statistics noise.

**Verdict:** Opus 5 has the cheapest steady-state hot path and the only burst protection; Kimi k3 and pt-2-v3 both do full per-tick re-resolution, and pt-2-v3 additionally pays a full-attribute deep copy per write. All fine at expected home scale; differences show with many leaders/features or multiple instances.

## 2.5 Maintenance costs

| | Kimi k3 | Opus 4.7 (pt-2-v3) | Opus 5 |
|---|---|---|---|
| Codebase size | 2,403 (largest of trio) + 0 tests | 1,816 (smallest) + 726 tests | 2,574 + 2,456 tests (largest total, ~49% tests) |
| Safety net | **none** — regression detection is manual | partial — parser/evaluator well covered; config flow, services, state machine, restore all untested; **one shipped test fails** | strong — contract pinned by 2,456 lines incl. publication regression tests |
| Bug debt carried | 4 real bugs (snapshot empty-name no-op, subentry-edit dup check, yaml/schema mismatch, whitespace feature names) | 13+ defects (options-shadowing reconfigure, nondeterministic dedup, broken `clear_error`, stringly bool, broken test, service lifecycle, `exc_info` misuse…) | 2 minor bugs (hyphen-prefix edge, stringly bool on event path) + 1 vacuous test |
| Duplication burden | subentry flows ×3 (~200 lines), coordinator blocks ×2, strings/en.json hand-duplicated | sensor boilerplate ×2, restore-data ×2, schema blocks ×2 | deliberate, documented legacy duplication (label_data); some 3× mappings |
| Tooling/CI | hassfest/HACS only, no pytest | no pytest config, no pinned deps, fragile HA-less stubs | pinned PHCC, pytest.ini, ruff.toml |
| Knowledge trail | strong docstrings citing legacy line numbers | decent docstrings | strongest — every legacy quirk has a documented *why*; diagnostics for field debugging |

**Verdict:** Kimi k3's zero tests make every change a manual-regression exercise despite the clean engine; pt-2-v3 has the smallest code but the largest bug debt and a god-object that couples every concern; Opus 5 costs the most lines but the least risk per change.

## 2.6 Ease of improvement

**Scenario: add a new leader-modifier label (e.g. `Only:`)**
- Kimi k3: engine `extract_label_modifiers` + `LeaderDef` + `eval_leader` (pure, easy) — then 3 duplicated subentry schemas + strings ×2. Wide but mechanical; no tests to update (none exist — also nothing catches you).
- Opus 4.7 (pt-2-v3): `label_parser` + `evaluator` (well-tested pure modules — easiest edit of the trio), then wire through the 867-line sensor's hot path (no state-machine tests — riskiest verification).
- Opus 5: `features.py` parse/eval + extend existing truth-table tests; coordinator metadata cache picks it up. Narrowest, safest path.

**Scenario: add a new service**
- Kimi k3: `services.py` + decide per-instance routing (currently hard-pinned to default instance).
- Opus 4.7 (pt-2-v3): `services.py` stanza firing an event (simple).
- Opus 5: `services.py` stanza + optional `routing.py` ownership rule; registration loop exists.

**Scenario: fix a state-machine bug**
- Kimi k3: pure engine is easy to reason about and would be easy to unit-test (Fable's sibling proves it: 802 lines of pure engine tests); coordinator glue is the fiddly part.
- Opus 4.7 (pt-2-v3): edit the god-sensor with no state-machine coverage — highest blast radius.
- Opus 5: targeted module + existing tests localize the fix.

**Extension points already present:** Kimi k3's subentries are a unique UI extension surface; Opus 5's diagnostics + routing + module layout are the best developer surface; pt-2-v3's parser/evaluator split is its one clean seam.

**Verdict:** Opus 5 easiest (boundaries + executable spec); Kimi k3 moderate (clean core, wide edit surface, no safety net); pt-2-v3 hardest despite smallest size (god-object; must fix the broken test before CI means anything).

## 2.7 Conformance to the CuratedForest documentation

Scope: the component replaces the two trigger-based template sensors (`sensor.labeled_features_state`, `sensor.labeled_feature_areas_state`) and the `script.labeled_feature_error_mode` helper. The dispatch loop, generics catalog, button mapping scripts, and area scripts stay YAML-side — the component's job is to keep their documented assumptions true.

### Contract checklist

| # | Documented requirement (source) | Kimi k3 | Opus 4.7 (pt-2-v3) | Opus 5 |
|---|---|---|---|---|
| 1 | Attributes `feature_meta`/`leaders`/`features`/`snapshots` with exact shapes (theory) | ✅ | ✅ | ✅ |
| 2 | `feature_meta` = 17-entry catalog `{domain, kind, domain_label}` (theory, dispatch-loop) | ✅ | ✅ | ✅ |
| 3 | Event-domain leaders store the **event name** in `current_value` via `attributes.event_type` — required by sleep-timeout's stepping classifier (dispatch-loop) | ✅ | ✅ | ✅ |
| 4 | `features` keys `feature → scope(area/floor/global) → scope_id('' for global)`; entry `{enabled, mode, last_changed_timestamp, triggering_leader}` (theory) | ✅ | ✅ | ✅ |
| 5 | Timestamp bumped only when `enabled` flips; momentary domains re-fire so repeat button presses dispatch (theory + template parity) | ✅ | ✅ | ✅ |
| 6 | Mode labels on the **sensor entity**: `<Scoped F> Mode: Leader\|Any\|All`, case-sensitive, default Leader (theory) | ✅ (+ subentry alternative) | ✅ | ✅ (+ option overrides — docs don't mention; precedence label > option, so labels still win) |
| 7 | Leader mode = only the driving leader's truth (theory: "other leaders are ignored") — verified in code | ✅ `this_truth` | ✅ `this_truth` | ✅ single-value fold |
| 8 | Default truth: `state == <F>` case-sensitive; truthy set case-insensitive; `event`/`button` always true; `Invert` last (features-and-labels) | ✅ | ✅ | ✅ |
| 9 | Direction precedence over Enable/Disable; non-numeric/first → false; Invert after (features-and-labels) | ✅ | ✅ | ✅ |
| 10 | Skip `*_initial_press` + unknown/unavailable/none; boot-noise gate (dispatch-loop, theory) | ✅ | ⚠️ also eats legitimate literal `"none"` old-states | ✅ |
| 11 | Orphan drop on next tick; manual entries (`triggering_leader: ''`) exempt (theory) | ✅ | ✅ | ✅ (tested) |
| 12 | Manual override durability: sticky until a leader on the **same triple** changes; mode preserved (dispatch-loop) | ✅ | ✅ | ✅ (tested) |
| 13 | `labeled_feature_set` payload `{target_feature, scope, scope_id, enabled, timestamp}` (dispatch-loop) | ✅ | ⚠️ stringly bool on raw event path (`"false"` → `True`) | ⚠️ same stringly-bool edge on event path (service path safe) |
| 14 | `labeled_feature_snapshot_set`; empty payload deletes (dispatch-loop) | ⚠️ empty **name** silently no-ops (doc-bug in code) | ⚠️ non-dict payload silently treated as delete | ✅ (tested set/delete) |
| 15 | Case-sensitivity of feature names, keywords, `True`/`False` (theory warning) | ✅ | ✅ | ✅ (tested) |
| 16 | `label_map` keyed `<scope_id>\|\|<label>` with `{scope_id, label, scope, declaring_area_id, component}`; **"exactly five fields… no object_id"**; sensor must NOT parse icon/initial/min/max/step/unit/device_class (area-based-features) | ⚠️ adds redundant `label_data` | ⚠️ adds redundant `label_data` | ⚠️ adds redundant `label_data` |
| 17 | `component` default `select`; override only via `Provides <F> Component:` (area-based-features) | ✅ | ✅ | ✅ (tested) |
| 18 | Floor-scope `Provides` deduped by `scope_id` across areas (area-based-features) | ✅ (first wins) | ⚠️ **nondeterministic** winner (set iteration) | ✅ (first wins, tested) |
| 19 | Bare `Provides:` → scope `none`, scope_id = declaring area (area-based-features) | ✅ | ✅ | ✅ (tested) |
| 20 | Modifier keywords (`Component/Min/Max/Step/Unit/Icon/Initial/Static/Mode/Device Class`) never become features (area-based-features) | ✅ | ⚠️ filtered, but `Static` untested | ✅ (all 10 tested) |
| 21 | Areas map re-renders on label/area/floor registry change **and** publishes at `homeassistant.start` for the re-publish-diff automation (area-based-features) | ✅ | ✅ | ✅ (+ restored-map publishes before reconcile — tested) |
| 22 | Real `state_changed` publications with detached from/to attributes — the Leaders/Areas automations **diff `from_state` vs `to_state`** (theory, area-based-features) | ✅ (pure engine returns fresh trees) | ✅ (deep copy per write) | ✅ (rebuild-then-publish, **tested** with identity checks) |
| 23 | Sensor `unique_id` for registry features (theory) | ✅ | ✅ | ✅ |
| 24 | Error-mode helper parity: fields `error_mode/message/source/severity`; tiers silent/log/alert(→`script.send_alert` w/ `alert_severity/title/message`)/stop(log; caller halts) (dispatch-loop) | ✅ service w/ same fields + alert payload | ❌ **no error-mode service at all** (internal-only handler) | ✅ service w/ same fields; stop re-raised as `ServiceValidationError` |
| 25 | Per-feature `Error Mode:` label resolution (features-and-labels) | ❌ options-only (engine errors) | ❌ config-only | ⚠️ bare-label + option resolution; **scoped-label tier coded but never called in production** |
| 26 | Script Call Mode labels live on the sensor, resolved by the automation (features-and-labels) | ✅ untouched (automation reads labels — still works) | ⚠️ dead config field instead | ⚠️ dead config field instead |

### Per-session conformance verdict

- **Kimi k3 — high conformance on the state layer.** Everything the docs require of the two sensors is present and shape-correct; its "byte-compatible" doc citations are backed by the code (Enable/Disable compare *state* not `current_value` — the documented legacy quirk — is preserved). Extras (subentries, self-clearing repairs) are additive, not conflicting. Gaps: no per-feature `Error Mode:` label consultation, a docstring/code mismatch on empty snapshot names, and multi-instance hazards the docs never contemplated (docs assume one instance — the `_dev` story is its own invention).
- **Opus 4.7 (pt-2-v3) — medium conformance.** Core state-layer semantics are right (verified leader-mode, truth, skip, orphan, restore behavior), and its services' "validate then re-fire the legacy event" design matches the documented `Set Feature`/`Set Snapshot` catalog entries exactly. But it has the most contract-adjacent defects: no error-mode service (the documented shared helper has no replacement in this branch), nondeterministic floor dedup, the `"none"`-state gate, stringly-bool, dead `script_call_mode` config, broken issue-clearing, and a shipped test that fails.
- **Opus 5 — highest conformance.** The contract is not just implemented but *pinned by tests*: publication invariants (the exact mechanism the diff-based automations depend on), orphan rules, mode precedence (label > option > default), skip values, boot gate, restore semantics, multi-instance routing. It also documents every deliberate legacy quirk in docstrings — the same role the CuratedForest docs play for the YAML stack. Deviations are minor: the shared `label_data` extra field, dead script-call-mode config, and the unused scoped-error-mode tier.

**Shared deviation (all three):** `label_map` entries carry a nested `label_data` duplicate beyond the docs' "exactly five fields" — all three target the actual legacy template sensor's byte shape, while the docs have since tightened the stated contract. Decide per policy whether docs or template wins; the three branches behave identically here.

**Philosophy fit (docs' acceptance criterion: "configure area + labels and everything just works"):** Opus 5 keeps labels as the sole behavioral truth with options only as defaults — most aligned. Kimi k3's subentries let UI config silently *override* labels — convenient but a second source of truth the docs deliberately avoid. Opus 4.7 (pt-2-v3) is label-primary but its reconfigure/options shadowing bug means UI config can silently override labels *unintentionally*.

## 2.8 Three-way synthesis

- **Opus 5** is the branch to build on: cheapest hot path, only burst protection, lowest maintenance risk, easiest to extend, and the documentation contract is enforced by its test suite rather than by hope.
- **Kimi k3** has the best *engine design* and a unique subentry UI, but zero tests, the widest edit surface, and several real bugs make it expensive to carry forward; its best move would be adopting Fable's sibling test suite (same engine lineage) and an Opus-5-style routing module.
- **Opus 4.7 (pt-2-v3)** is the weakest of the three to maintain (god-object, longest bug list, broken test, no error-mode service) though its parser/evaluator seam and full reconfigure step are worth salvaging; adopting it means paying down bug debt first.

---
---

# Part 3 — Implementation plan: port cc-v1's config-flow additions into `main`

**Target:** `main` (working tree, identical to `testing-component-creation-pt-2-v2` / Opus 5).
**Source:** `claude-testing-component-creation` (Kimi k3).
**Skills loaded:** `home-assistant-best-practices` (native constructs, typed selectors over free text) and `HA Integration Dev` (`references/config-flow.md` — explicit `SelectSelectorMode.DROPDOWN`; `references/subentries.md` — subentry lifecycle/strings; note its single-type API example is dated, we use the modern `async_get_supported_subentry_types` API that cc-v1 already uses).

**User decisions (2026-07-26):**
1. **Scope:** port the three subentry types (leader / provides / mode) **and** the `alert_action` + `alert_severity` options. **No reconfigure step** (main's AGENTS.md flags editable prefix as ask-first; the options flow already covers runtime settings).
2. **Precedence:** **labels stay supreme.** Where a label and a subentry define the same thing, the label wins; subentries are a fill-in for things no label declares. Mode precedence becomes: sensor label > mode subentry > option override > entry default > `leader`.

**The two UI fixes (included regardless of scope):**
- **"Top right" missing text:** cc-v1's `strings.json` lacks `entry_type` under each `config_subentries.<type>` — HA's frontend uses that key as the subentry-type label (add-dialog header / subentry section). Port includes `entry_type` for all three types, plus complete `initiate_flow` / `step.*` / `abort` strings.
- **Select lists → dropdowns:** main's three `SelectSelector`s in `_settings_schema` set no `mode`, and the modern frontend renders small option sets as lists when mode is unset. Set `mode=SelectSelectorMode.DROPDOWN` explicitly on all existing and new selectors (per the skill's config-flow reference; cc-v1's `_select` helper already does this).

## 3.1 Design: label synthesis at the refresh boundary

Subentries are converted to **synthetic labels** inside `_async_refresh_registry` (the only registry-touching path), so the entire pure pipeline (`build_triple_map`, `evaluate_leader`, `build_label_map`) and the hot path (`_async_state_changed` / `_leader_info`, registry-free per AGENTS.md) work **unchanged**:

- A `leader` subentry `{entity_id, feature, scope, enable_value, disable_value, direction, invert}` synthesizes `Leader: <F>` / `Area Leader: <F>` / `Floor Leader: <F>` plus modifier labels (`<pfx><F> Enable: <v>`, `Disable: <v>`, `Increasing: True`, `Decreasing: True`, `Invert: True`), appended to that entity's `_leader_meta` labels. **Skipped** when the entity's real labels already produce the same `(feature, scope)` grouping (labels supreme). Subentry entities not carrying the leader label are added to `_leader_ids` / `_leader_meta`.
- A `provides` subentry `{area_id, feature, scope, component}` synthesizes `Provides: <F>` / `Area Provides: <F>` / `Floor Provides: <F>` (plus `<pfx>Provides <F> Component: <c>` when component ≠ `select`) into a new `extra_area_labels` argument of `build_label_map`. **Skipped** when the area's real labels already declare the same `(feature, scope)`. Subentry areas join `_gated_area_ids` (cc-v1 parity: gated = leader-labeled areas ∪ provides-subentry areas).
- A `mode` subentry `{feature, scope, mode}` feeds a new `subentry_modes: dict[scoped_feature, mode]` passed to `resolve_mode` as a new tier **between** sensor labels and option overrides.

Subentry add/edit/delete fires the entry update listener (cc-v1 relied on this; verified by a test), and `__init__.py` already reloads on update — no `__init__.py` changes needed. New triples are **not** seeded into `features` at reconcile (AGENTS.md never-do); subentry-driven triples appear on the leader's next state change, same as label-driven ones.

## 3.2 File-by-file changes

### `const.py` (additions)
- `SUBENTRY_TYPE_LEADER = "leader"`, `SUBENTRY_TYPE_PROVIDES = "provides"`, `SUBENTRY_TYPE_MODE = "mode"`
- `SUBCONF_AREA_ID`, `SUBCONF_FEATURE`, `SUBCONF_SCOPE`, `SUBCONF_ENABLE_VALUE`, `SUBCONF_DISABLE_VALUE`, `SUBCONF_DIRECTION`, `SUBCONF_INVERT`, `SUBCONF_MODE`, `SUBCONF_COMPONENT` (reuse `CONF_ENTITY_ID` from HA)
- `LEADER_SCOPES = ("area", "floor", "global")`, `PROVIDES_SCOPES = ("area", "floor", "none")`, `DIRECTIONS = ("none", "increasing", "decreasing", "both")`, `DIRECTION_NONE = "none"`, `PROVIDES_COMPONENTS = ("select", "number", "sensor", "switch", "text", "binary_sensor")`
- `CONF_ALERT_ACTION = "alert_action"`, `DEFAULT_ALERT_ACTION = ALERT_SCRIPT_ENTITY_ID` (`"script.send_alert"`), `CONF_ALERT_SEVERITY = "alert_severity"`, `DEFAULT_ALERT_SEVERITY = DEFAULT_ERROR_SEVERITY`, `SEVERITIES = ("low", "medium", "high")`
- Do **not** duplicate existing `MODES` for fold modes — the mode subentry uses `MODES`.

### `features.py` (pure helpers)
- `subentry_leader_labels(data, area_id, floor_id) -> list[str] | None` — subentry → synthetic grouping + modifier labels; `None` when area/floor scope is unresolvable (coordinator routes the error via `_async_error`, e.g. `leader subentry for <entity> has no area`).
- `grouping_label_covers(labels, feature, scope) -> bool` — true when a real label already defines that grouping (reuse `parse_grouping_label`); used to skip conflicting subentries.
- `resolve_mode(...)` — insert `subentry_modes: dict[str, str]` param after `sensor_labels`; precedence: sensor label > subentry > option override > default > `leader`. Update the docstring.

### `areas.py`
- `build_label_map(regs, leader_label, extra_area_labels=None, extra_gated_area_ids=None)` — optional params; synthetic labels are parsed by the same existing code path (modifier filtering, floor dedup, component override all inherited). Skip a synthetic declaration when the area's real labels already cover `(feature, scope)`.

### `coordinator.py` (refresh path only)
- `_async_refresh_registry`: split `self._entry.subentries.values()` by type; build/merge synthesized labels into `_leader_ids`, `_leader_meta`, `_gated_area_ids`, `extra_area_labels` for `build_label_map`, and `self._subentry_modes`; route unresolvable-scope errors through `_async_error`; pass merged leader ids to `_reconcile_leaders` so subentry leaders get seeded `leaders` entries.
- Mode call site (in the leader-tick path): pass `self._subentry_modes` to `resolve_mode`.
- **No hot-path changes** — synthesized labels live in the caches the hot path already reads.

### `config_flow.py`
- Add `_select(options, *, custom_value=False)` helper with explicit `SelectSelectorMode.DROPDOWN`; use it for the three existing selectors (`default_mode`, `default_script_call_mode`, `default_error_mode`) — the dropdown fix.
- Add `alert_action` (TextSelector + `vol.Match(r"^[a-z0-9_]+\.[a-z0-9_]+$")` → error key `alert_action_invalid`) and `alert_severity` (dropdown over `SEVERITIES`) to `_settings_schema`; persist in options like the other settings.
- Add `async_get_supported_subentry_types` returning the three flows.
- Port the three `ConfigSubentryFlow` classes from cc-v1 with these fixes:
  - **Dup-check on edit** (cc-v1 bug): reconfigure steps call `_unique_id_taken(new_id)` excluding the subentry being edited.
  - **Empty-feature guard**: stripped-empty `feature` → `feature_required` field error (cc-v1 allowed it).
  - `invert` uses `BooleanSelector` (skill: typed selectors over primitives).
  - All selects via the dropdown helper.
  - Descriptions rewritten for labels-supreme semantics ("Used only when no label defines the same feature/scope; labels win on conflict").

### `errors.py`
- `async_handle_error(..., *, alert_action: str | None = None)` — when provided, split `domain.service` and call it with `alert_severity/alert_title/alert_message`; unknown/malformed action → fall back to the existing warning path (never raise out of the error handler). Default stays `ALERT_SCRIPT_ENTITY_ID`.
- `coordinator._async_error` passes the entry's configured `alert_action` and `alert_severity`.

### `strings.json` + `translations/en.json` (byte-identical)
- New `config_subentries` blocks for `leader` / `provides` / `mode` **with `entry_type`** (the missing-text fix), `initiate_flow`, `step.user` (title/description/data/data_description), `step.reconfigure`, `abort.already_configured`.
- `config.step.user` + `options.step.init`: `alert_action` / `alert_severity` labels and descriptions; new error keys `alert_action_invalid`, `feature_required`.
- Write once, `cp` to `translations/en.json`; verify identical.

### Tests
- `tests/test_config_flow.py`: subentry add/edit/abort-duplicate for each type; edit-step duplicate rejection (new fix); empty-feature error; alert-option validation; assert every `SelectSelectorConfig` in the schemas sets `mode == SelectSelectorMode.DROPDOWN`.
- `tests/test_subentries.py` (new): unlabeled entity becomes a leader via subentry and flips a feature end-to-end; enable/invert modifiers honored; **label beats conflicting subentry** (labels supreme); provides subentry lands in `label_map` (with component); provides label beats subentry; mode subentry resolves mode, and precedence label > subentry > option override; unresolvable area scope routes an error without crashing; adding a subentry triggers entry reload (update listener fires).
- `tests/test_errors.py`: alert tier calls the configured action with the three fields; missing/invalid action falls back to warning, never raises.
- Re-run `test_publication.py` unchanged — no new write paths are added.

### Docs
- `README.md`: new "Config subentries" section (three types, labels-supreme precedence, alert options); note subentry-driven triples appear on the leader's next tick (not at reconcile).
- Root `AGENTS.md`: update the "Labels stay the configuration surface" decision to include subentries as a label-driven alternative where labels win conflicts.
- `custom_components/labeled_features/AGENTS.md`: Key Files (config_flow subentries), Boundaries (labels win over subentries).
- `tests/AGENTS.md`: the new test file.

## 3.3 Explicit non-goals
- No reconfigure step (AGENTS.md ask-first on editable prefix; options flow covers runtime settings).
- No `entity_id_suffix` concept from cc-v1 — main's `prefix` stays.
- No changes to the attribute contract, publication paths, services, or `services.yaml`.
- Skill attribution banners are **not** added to existing files (repo convention has none; the skill's attribution rule applies to skill-generated new files — the one new test file gets the repo's standard header, not a banner).

## 3.4 Risks & verifications
- **Update-listener assumption**: subentry changes must reload the entry — covered by a dedicated test; if HA doesn't fire the listener, fall back to listening for subentry changes explicitly in `async_setup_entry`.
- **Mode subentry keying**: keyed by exact scoped feature name (`Area Night`, `Night`, `Floor Night`), case-sensitive like labels — documented in strings.
- **Label-supreme skip logic** must be total: a subentry fully shadowed by labels is inert but retained (visible in UI, documented in README), not deleted.
- **cc-v1 bugs not ported**: edit-step dup-check omission, whitespace-only feature names, `vol.In`-less schema/yaml drift (services.yaml untouched here).

## 3.5 Implementation order & acceptance
1. `const.py` → pure helpers (`features.py`, `areas.py`) → `coordinator.py` → `config_flow.py` → `errors.py` → strings (both files) → tests → docs.
2. Acceptance: `ruff check custom_components tests` clean; `black --line-length 88 custom_components tests` clean; `pytest -q` green with output pasted; strings/en byte-identical (`cmp`); no attribute-contract keys changed; new subentry tests pass; `test_publication.py` still green.

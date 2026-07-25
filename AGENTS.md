<!-- FOR AI AGENTS - Human readability is a side effect, not a goal -->
<!-- Managed by agent: keep sections and order; edit content, not structure -->
<!-- Last updated: 2026-07-25 | Last verified: 2026-07-25 -->

# AGENTS.md

**Precedence:** the **closest `AGENTS.md`** to the files you're changing wins. Root holds global defaults only.

A Home Assistant custom integration (`labeled_features`) implementing the state layer of the
Label Based Features system. It replaces two production trigger-based template sensors with
native entities. **Parity with those sensors is the hard requirement** — the consuming
automations and scripts are unchanged YAML and must keep working.

## Commands (verified 2026-07-25)
> Source: `requirements_test.txt`, `pytest.ini`, `ruff.toml`. No Makefile, no `pyproject.toml`.

| Task | Command | ~Time |
|------|---------|-------|
| Setup | `python -m venv .venv && . .venv/bin/activate && pip install -r requirements_test.txt` | ~2m |
| Lint | `ruff check custom_components tests` | <1s |
| Format | `black --line-length 88 custom_components tests` | <1s |
| Test (single file) | `pytest tests/test_features.py -q` | ~2s |
| Test (all) | `pytest -q` | ~4s (142 cases) |
| Build | none — this is a HACS/custom_components drop-in | — |

> Validation of `manifest.json`/`hacs.json` runs in CI only (hassfest + HACS action,
> `.github/workflows/validate.yaml`). There is no local equivalent.

## Response Style
- Answer first, elaborate only if needed. No sycophantic openers.
- For yes/no or status questions, lead with the answer.
- Skip preamble. Match response length to task complexity.

## Workflow
1. **Before coding**: read the nearest `AGENTS.md` + the Golden Samples for the area you touch
2. **After each change**: `ruff check` → the single most relevant test file
3. **Before committing**: `pytest -q` (the suite is 4s; there is no excuse to skip it)
4. **Before claiming done**: paste command output as evidence — never say "should work", "tested", or "all green" without it

## File Map
```
custom_components/labeled_features/ -> the integration (see its AGENTS.md)
tests/                              -> pytest-homeassistant-custom-component suite (see its AGENTS.md)
.github/workflows/validate.yaml     -> hassfest + HACS validation (CI only)
hacs.json, README.md                -> HACS metadata and user/migration docs
pytest.ini, ruff.toml, requirements_test.txt -> tool config (no pyproject.toml)
```

## Golden Samples (follow these patterns)
| For | Reference | Key patterns |
|-----|-----------|--------------|
| Behavior logic | `custom_components/labeled_features/features.py` | Pure functions over explicit inputs; no `hass`, no I/O — directly unit-testable |
| Registry access | `custom_components/labeled_features/labels.py` | Mirrors HA template helpers exactly; one `Registries` bundle passed in |
| Publishing state | `custom_components/labeled_features/coordinator.py` (`_publish_features`) | Detached snapshots, one write per tick |
| Write-path tests | `tests/test_publication.py` | Asserts on `EVENT_STATE_CHANGED` counts, not `hass.states.get()` |
| Test fixtures | `tests/conftest.py` | `register_entity` / `create_area` / `make_entry` / `setup_entry` |

## Utilities (check before creating new)
| Need | Use | Location |
|------|-----|----------|
| Entity/area labels, area+floor resolution | `Registries`, `entity_label_names`, `label_entities`, `label_areas`, `entity_area_id`, `entity_floor_id` | `labels.py` |
| Detach a dict tree before publishing | `snapshot_tree()` | `coordinator.py` |
| Report an error through the tiers | `async_handle_error`, `resolve_error_mode` | `errors.py` |
| Pick the instance for an untargeted event | `async_event_owner` | `routing.py` |
| Parse `<Scoped F> <Keyword>: <value>` overrides | `parse_overrides`, `validate_overrides` | `coordinator.py` |
| Label/scope constants, feature catalog | `SCOPE_LABEL_PREFIX`, `TRUTHY_STATES`, `FEATURE_META` | `const.py` |

## Heuristics (quick decisions)
| When | Do |
|------|-----|
| Docs and the legacy YAML disagree | Reproduce the **YAML**, then record it under `KNOWN_DIVERGENCES` in README.md |
| Adding a state attribute or changing its shape | Treat as a breaking change — the YAML consumers index into it |
| Touching a write path | Add a test that counts `EVENT_STATE_CHANGED`, not one that reads `hass.states.get()` |
| Adding behavior logic | Put the rule in `features.py` / `areas.py` as a pure function, call it from the coordinator |
| Needing registry data on a state-change tick | Read the coordinator's cache; do **not** call a registry |
| Adding dependency | Ask first — `manifest.json` requirements are intentionally empty |
| Unsure about a pattern | Check Golden Samples above |

## Key Decisions
- **Parity over cleanup (Phase 1).** Legacy quirks are reproduced deliberately and documented in README `KNOWN_DIVERGENCES`. Do not "fix" one without being asked.
- **Labels stay the configuration surface.** Leaders, features and followers are label-driven; the config flow only carries instance-level settings, and **labels on the sensor entities win over config-entry options**.
- **Entity slug prefix is fixed at setup.** Default `labeled_feature` reproduces the legacy entity IDs; changing it would orphan entity IDs, so it is absent from the options flow.
- **One instance consumes each untargeted compat event.** Ambiguity is dropped with a warning rather than guessed (`routing.py`).
- **Phase 1 is the state layer only.** The Leaders/Areas automations and every `labeled_feature_*` script stay in YAML.

## Boundaries

### Always Do
- Run `ruff check` + `pytest -q` before committing, and paste the output
- Add tests for new code paths; for write paths, assert on published events
- Use conventional commits: `type(scope): subject`, atomic (one logical change each)
- Keep published attributes detached from mutable working state (see the integration's AGENTS.md)
- Keep behavior logic pure and in `features.py` / `areas.py`
- Verify `pwd` is inside the intended worktree before editing

### Ask First
- Adding a dependency to `manifest.json` or `requirements_test.txt`
- Changing any state attribute name, nesting, or value type
- Editing `.github/workflows/`, `hacs.json`, or `manifest.json` metadata
- Removing a documented divergence or a legacy quirk
- Migrating any of the YAML automations/scripts into the component (that is Phase 2+)

### Never Do
- Commit secrets or credentials
- Mutate `coordinator.leaders` / `.features` / `.snapshots` / `.label_map` and expect a state write — HA compares attributes shallowly and will suppress the event
- Call a registry or rebuild `Registries` inside the `state_changed` hot path
- Emit more than one state write per logical tick — consumers diff `from_state`/`to_state`
- Edit files under `/home/coder/HomeAssistant/` or `/home/coder/CuratedForest.com/` (reference only, outside this repo)
- Push directly to `main` — open a PR
- Force-push without `--force-with-lease`

## Codebase State
- **Phase 1 complete**: both sensors, error tiers, config/options flow, actions, routing, diagnostics. 142 tests.
- **Not yet cut over**: the template sensors still own the legacy entity IDs in production. README has the migration order; creating a default-prefix instance before deleting them yields `_2` entity IDs.
- **Known divergences** (intentional, see README): Enable/Disable compares entity *state* not `current_value`; new triples are not seeded on a label edit; `leaders` seeding happens on the debounced reconcile.
- **Forward-looking option**: `default_script_call_mode` is stored and exposed but unused in Phase 1 — the YAML Leaders automation still reads Script Call Mode from labels.
- Local reference material, **not in this repo**: legacy YAML at `/home/coder/HomeAssistant/{configuration,automations,scripts}.yaml`; specification docs at `/home/coder/CuratedForest.com/content/tech/home-assistant/label-based-features/`.

## Terminology
| Term | Means |
|------|-------|
| Leader | Entity labeled `Feature Leader` + `(Area \|Floor \|)Leader: <F>`; its state drives a feature |
| Follower | Entity labeled `(Area \|Floor \|)Follower: <F>`; acted on by the dispatch loop (still YAML) |
| Feature | Named capability (`Night`, `Lights On`); resolved per scope |
| Triple | `(feature, scope, scope_id)` — the key of the `features` attribute; flat key `feature\|\|scope\|\|scope_id` |
| Scope | `area` / `floor` / `global` (features) or `area` / `floor` / `none` (areas sensor's bare form) |
| scope_id | `area_id`, `floor_id`, or `''` for global |
| Mode | Fold across a triple's leaders: `Leader` (default), `Any` (OR), `All` (AND) |
| Instance | One config entry; its slug prefix determines both entity IDs |
| Compat events | `labeled_feature_set` / `labeled_feature_snapshot_set`, fired by existing YAML scripts |

## Scoped AGENTS.md (MUST read when working in these directories)
- [`custom_components/labeled_features/AGENTS.md`](./custom_components/labeled_features/AGENTS.md) — the integration: attribute contract, publication rules, module boundaries
- [`tests/AGENTS.md`](./tests/AGENTS.md) — test environment, fixtures, and the assertion rules that make write-path tests meaningful

> **Agents**: When you read or edit files in a listed directory, you **must** load its AGENTS.md first. It contains directory-specific conventions that override this root file.

## When instructions conflict
The nearest `AGENTS.md` wins. Explicit user prompts override files.

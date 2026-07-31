<!-- Managed by agent: keep sections and order; edit content, not structure. Last updated: 2026-07-26 -->

# AGENTS.md — tests

## Overview
`pytest-homeassistant-custom-component` suite for the `labeled_features` integration. 174 cases,
~4s for the whole run, so run it all rather than guessing which file is relevant.

## Key Files
| File | Covers |
|------|--------|
| `conftest.py` | Fixtures and registry helpers (see below), plus the PHCC compat shim |
| `test_features.py` | Pure logic: truth function matrix, direction, Any/All fold, timestamp bumps, orphan drop, subentry label synthesis |
| `test_labels.py` | Registry helpers: device-label non-inheritance, area→device fallback, label id/name lookup, parsers |
| `test_areas.py` | `label_map`: scopes, modifier rejection, component override, floor dedup, provides-subentry fill-in |
| `test_sensor.py` | End-to-end sensor behavior: entity IDs, leader ticks, modes, restore, unload |
| `test_publication.py` | **Write-path regressions** — every write must emit a `state_changed` event; routing |
| `test_coordinator.py` | Override parsing, debounced registry path, `config` attribute, diagnostics, actions |
| `test_config_flow.py` | Config + options + subentry flows, including every validation error |
| `test_subentries.py` | Subentry → state machine: leader seeding, label-wins conflicts, provides in `label_map`, mode folding |
| `test_errors.py` | The four error tiers, configurable alert action, precedence resolution |

## Golden Samples (follow these patterns)
| For | Reference |
|-----|-----------|
| Asserting a write actually happened | `test_publication.StateWrites` — counts `EVENT_STATE_CHANGED` for one entity |
| A pure-logic unit test | `test_features.test_enable_and_disable_together` |
| An integration test | `test_sensor.test_global_leader_flip` — register entity, set up entry, `async_set_state` |
| Registry setup | `conftest.register_entity` / `create_area` / `create_floor` |
| Labelling our own sensor | `conftest.set_sensor_labels` (labels on the sensor beat entry options) |

## Setup & environment
```bash
uv venv --python 3.13 .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pip install --no-deps pytest-homeassistant-custom-component==0.13.205
.venv/bin/pytest -q
```
The suite runs against **Home Assistant 2025.7.4 on Python 3.13** (the floor for config
subentry flows). PHCC is installed with `--no-deps` because its exact HA pin (2025.1.4) lags;
`requirements_test.txt` covers both HA's and PHCC's runtime dependencies. `conftest.py`
patches `ConfigEntry.__init__` with the `subentries_data` default PHCC's `MockConfigEntry`
omits — remove the shim if PHCC is ever bumped past it. `pytest.ini` sets
`asyncio_mode = auto`, so `async def test_*` needs no decorator, and `conftest.py` enables
custom integrations for every test automatically.

## Running tests
| Task | Command |
|------|---------|
| Everything | `pytest -q` |
| One file | `pytest tests/test_features.py -q` |
| One test, with prints | `pytest tests/test_publication.py::test_manual_set_feature_publishes_a_state_change -q -s` |

## Fixtures and helpers
| Helper | Does |
|--------|------|
| `leader_label` fixture | Creates the default `Feature Leader` label |
| `make_entry(prefix=…, name=…, **options)` | Builds a `MockConfigEntry` with all option defaults filled in |
| `setup_entry(hass, entry=None)` | Adds and sets up an entry, then blocks till done |
| `register_entity(hass, entity_id, labels=…, area_id=…, state=…, attributes=…)` | Registry entry + optional state |
| `create_area` / `create_floor` | Areas with labels and an optional floor |
| `label_ids(hass, names)` | Creates labels by name and returns their ids |

## The assertion rule that matters
`hass.states.get(...).attributes` can show data that was **never published**: if the coordinator
mutated a dict that the previous `State` still references, the test reads the mutated object even
though no `state_changed` event fired. A suite of 132 tests passed that way once while manual
`Set Feature` and snapshot writes were silently broken.

So, for any path that writes state:
- assert on `EVENT_STATE_CHANGED` counts and on the `new_state` carried by the event
  (`StateWrites` in `test_publication.py`), and
- assert exactly **one** write per tick, since the consuming automations diff
  `from_state`/`to_state`.

Reading `hass.states.get()` is fine for asserting the *shape* of already-verified state, never for
proving a write happened.

## Boundaries

### Always Do
- Add a `test_publication.py`-style event-count test for every new write path
- Use the `conftest.py` helpers instead of touching the registries inline
- Prefer a pure-logic test in `test_features.py` when the rule is pure — it is faster and clearer
- Fire real transitions: `hass.states.async_set` with an *unchanged* value emits nothing, so a
  test that "sets" the same state never exercises the tick

### Ask First
- Adding a test dependency to `requirements_test.txt`
- Bumping the pinned `pytest-homeassistant-custom-component` version (it pins the HA version too)

### Never Do
- Prove a write happened via `hass.states.get()` alone
- Assert on an exact `last_changed_timestamp` value — compare relatively (`>`), or use `pytest.approx`
- Reach into coordinator privates except to prove detachment (`test_published_attributes_are_detached_snapshots`)
- Skip the suite because "the change is small" — it is 4 seconds

## Code style
- One behavior per test; the docstring states the behavior, not the mechanics.
- `async def test_*` with no decorator (`asyncio_mode = auto`).
- Parametrize matrices (`test_features.test_default_truth_generic_truthy`) instead of copy-paste.
- Build fixtures through `conftest.py` helpers; keep registry plumbing out of test bodies.
- Same tooling as the package: 88 columns, `black`, `ruff` (docstring rules relaxed for tests
  via `ruff.toml` per-file ignores).

## Security
- Tests must not reach the network or the real filesystem outside `tmp_path`; the HA test
  harness fails on unexpected I/O.
- No real credentials or tokens in fixtures — nothing here needs them.
- When testing untrusted-payload handling (compat events), assert the bad payload is **ignored**
  rather than that it raises: a raising handler would break the sensor in production.

## Examples

Proving a write happened:
```python
# GOOD
writes = StateWrites(hass, FEATURES_SENSOR)
hass.bus.async_fire(EVENT_SET_FEATURE, {...})
await hass.async_block_till_done()
assert len(writes) == 1
assert writes.last.attributes["features"]["Night"]["global"][""]["enabled"] is True

# BAD: passes even when no state_changed event fired, because the dict is aliased
hass.bus.async_fire(EVENT_SET_FEATURE, {...})
await hass.async_block_till_done()
assert hass.states.get(FEATURES_SENSOR).attributes["features"]["Night"]["global"][""]["enabled"]
```

Exercising a tick:
```python
# GOOD: a real transition
register_entity(hass, "binary_sensor.door", labels=[DEFAULT_LEADER_LABEL, "Leader: Open Door"], state="off")
await setup_entry(hass)
hass.states.async_set("binary_sensor.door", "on")
await hass.async_block_till_done()

# BAD: same value -> no state_changed event -> the coordinator never runs
hass.states.async_set("binary_sensor.door", "off")
```

## Commit checklist
- [ ] `pytest -q` green, output pasted into the response
- [ ] `ruff check tests` and `black --line-length 88 tests` clean
- [ ] New write paths covered by an event-count test
- [ ] No absolute timestamp assertions
- [ ] Test names describe behavior, not implementation

## When stuck
Boot-suppression, skip-values and timestamp bumps are the usual surprises. Check the expected
behavior against the legacy template sensor at
`/home/coder/HomeAssistant/configuration.yaml:214-693` before changing an assertion.

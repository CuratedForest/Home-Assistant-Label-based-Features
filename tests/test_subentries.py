"""Integration tests for config subentries feeding the state machine."""

from __future__ import annotations

import logging

import pytest

from custom_components.labeled_features.const import DEFAULT_LEADER_LABEL
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant

from .conftest import (
    create_area,
    create_floor,
    register_entity,
    set_sensor_labels,
    setup_entry,
)
from .test_sensor import FEATURES_SENSOR, async_set_state, entry_for, leaders

AREAS_SENSOR = "sensor.labeled_feature_areas_state"


async def add_subentry(hass, entry, subentry_type, data, title, unique_id):
    """Add a subentry and let the entry reload settle."""
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data=data,
            subentry_type=subentry_type,
            title=title,
            unique_id=unique_id,
        ),
    )
    await hass.async_block_till_done()


# ── leader subentries ────────────────────────────────────────────────────────


async def test_leader_subentry_makes_unlabeled_entity_a_leader(
    hass: HomeAssistant, leader_label
) -> None:
    """An entity with no labels becomes a leader via a leader subentry."""
    register_entity(hass, "input_boolean.night_mode", state="off")
    entry = await setup_entry(hass)
    assert "input_boolean.night_mode" not in leaders(hass)

    await add_subentry(
        hass,
        entry,
        "leader",
        {
            "entity_id": "input_boolean.night_mode",
            "feature": "Night",
            "scope": "global",
        },
        "Night (input_boolean.night_mode)",
        "input_boolean.night_mode|Night|global",
    )

    assert "input_boolean.night_mode" in leaders(hass)
    await async_set_state(hass, "input_boolean.night_mode", "on")
    assert entry_for(hass, "Night", "global", "")["enabled"] is True


async def test_leader_subentry_modifiers_are_honored(
    hass: HomeAssistant, leader_label
) -> None:
    """An enable_value subentry pins the truth function like an Enable label."""
    area = create_area(hass, "Kitchen")
    register_entity(hass, "media_player.tv", state="idle", area_id=area.id)
    entry = await setup_entry(hass)
    await add_subentry(
        hass,
        entry,
        "leader",
        {
            "entity_id": "media_player.tv",
            "feature": "Media Playing",
            "scope": "area",
            "enable_value": "playing",
        },
        "Media Playing (media_player.tv)",
        "media_player.tv|Media Playing|area",
    )

    await async_set_state(hass, "media_player.tv", "paused")
    assert entry_for(hass, "Media Playing", "area", area.id)["enabled"] is False
    await async_set_state(hass, "media_player.tv", "playing")
    assert entry_for(hass, "Media Playing", "area", area.id)["enabled"] is True


async def test_leader_label_wins_over_conflicting_subentry(
    hass: HomeAssistant, leader_label
) -> None:
    """A real Leader label beats a subentry for the same entity/feature/scope."""
    area = create_area(hass, "Kitchen")
    register_entity(
        hass,
        "media_player.tv",
        labels=[DEFAULT_LEADER_LABEL, "Area Leader: Media Playing"],
        state="idle",
        area_id=area.id,
    )
    entry = await setup_entry(hass)
    # The subentry would gate on Enable: playing if it were applied.
    await add_subentry(
        hass,
        entry,
        "leader",
        {
            "entity_id": "media_player.tv",
            "feature": "Media Playing",
            "scope": "area",
            "enable_value": "playing",
        },
        "Media Playing (media_player.tv)",
        "media_player.tv|Media Playing|area",
    )

    # `on` is truthy: the label path yields True, while the subentry's
    # Enable: playing would yield False. True proves the label won.
    await async_set_state(hass, "media_player.tv", "on")
    assert entry_for(hass, "Media Playing", "area", area.id)["enabled"] is True


async def test_leader_subentry_with_unresolvable_scope_logs_error(
    hass: HomeAssistant, leader_label, caplog: pytest.LogCaptureFixture
) -> None:
    """A floor-scoped leader subentry on an area-less entity only logs."""
    register_entity(hass, "binary_sensor.button", state="off")
    entry = await setup_entry(hass)
    with caplog.at_level(logging.WARNING):
        await add_subentry(
            hass,
            entry,
            "leader",
            {
                "entity_id": "binary_sensor.button",
                "feature": "Night",
                "scope": "floor",
            },
            "Night (binary_sensor.button)",
            "binary_sensor.button|Night|floor",
        )

    assert "cannot resolve its scope" in caplog.text
    assert "binary_sensor.button" not in leaders(hass)


# ── provides subentries ──────────────────────────────────────────────────────


async def test_provides_subentry_lands_in_label_map(
    hass: HomeAssistant, leader_label
) -> None:
    """A provides subentry declares a feature for an unlabeled area."""
    area = create_area(hass, "Kitchen")
    entry = await setup_entry(hass)
    assert hass.states.get(AREAS_SENSOR).attributes["label_map"] == {}

    await add_subentry(
        hass,
        entry,
        "provides",
        {
            "area_id": area.id,
            "feature": "Audio Mode",
            "scope": "area",
            "component": "select",
        },
        "Audio Mode (kitchen)",
        f"{area.id}|Audio Mode|area",
    )

    label_map = hass.states.get(AREAS_SENSOR).attributes["label_map"]
    assert set(label_map) == {f"{area.id}||Audio Mode"}
    assert label_map[f"{area.id}||Audio Mode"]["scope"] == "area"


async def test_provides_subentry_floor_scope(hass: HomeAssistant, leader_label) -> None:
    """A floor-scoped provides subentry dedupes to the floor id."""
    floor = create_floor(hass, "First Floor")
    area = create_area(hass, "Kitchen", floor_id=floor.floor_id)
    entry = await setup_entry(hass)
    await add_subentry(
        hass,
        entry,
        "provides",
        {
            "area_id": area.id,
            "feature": "Audio Mode",
            "scope": "floor",
        },
        "Audio Mode (kitchen)",
        f"{area.id}|Audio Mode|floor",
    )

    label_map = hass.states.get(AREAS_SENSOR).attributes["label_map"]
    assert set(label_map) == {f"{floor.floor_id}||Audio Mode"}
    assert label_map[f"{floor.floor_id}||Audio Mode"]["scope"] == "floor"


# ── mode subentries ──────────────────────────────────────────────────────────


async def test_mode_subentry_sets_fold_mode(hass: HomeAssistant, leader_label) -> None:
    """A mode subentry folds with Any where the default is Leader."""
    register_entity(
        hass,
        "binary_sensor.door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open"],
        state="off",
    )
    register_entity(
        hass,
        "binary_sensor.window",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open"],
        state="off",
    )
    entry = await setup_entry(hass)
    await add_subentry(
        hass,
        entry,
        "mode",
        {"feature": "Open", "scope": "global", "mode": "any"},
        "Open (global: any)",
        "Open|global",
    )

    await async_set_state(hass, "binary_sensor.door", "on")
    assert entry_for(hass, "Open", "global", "")["mode"] == "any"
    assert entry_for(hass, "Open", "global", "")["enabled"] is True

    # With Leader mode the door-off tick would write False (only the changed
    # leader counts); with the subentry's Any mode the window keeps it True.
    await async_set_state(hass, "binary_sensor.window", "on")
    await async_set_state(hass, "binary_sensor.door", "off")
    assert entry_for(hass, "Open", "global", "")["enabled"] is True


async def test_mode_label_on_sensor_beats_subentry(
    hass: HomeAssistant, leader_label
) -> None:
    """A Mode label on the features sensor wins over a mode subentry."""
    register_entity(
        hass,
        "binary_sensor.door",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open"],
        state="off",
    )
    register_entity(
        hass,
        "binary_sensor.window",
        labels=[DEFAULT_LEADER_LABEL, "Leader: Open"],
        state="off",
    )
    entry = await setup_entry(hass)
    await add_subentry(
        hass,
        entry,
        "mode",
        {"feature": "Open", "scope": "global", "mode": "any"},
        "Open (global: any)",
        "Open|global",
    )
    set_sensor_labels(hass, FEATURES_SENSOR, ["Open Mode: Leader"])

    await async_set_state(hass, "binary_sensor.door", "on")
    assert entry_for(hass, "Open", "global", "")["mode"] == "leader"

    await async_set_state(hass, "binary_sensor.window", "on")
    await async_set_state(hass, "binary_sensor.door", "off")
    # Leader mode: only the just-changed leader counts -> False.
    assert entry_for(hass, "Open", "global", "")["enabled"] is False

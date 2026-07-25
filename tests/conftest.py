"""Pytest fixtures for the Labeled Features integration."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom_components/ for every test."""

    yield

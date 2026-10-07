"""Shared test fixtures."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations in all tests."""
    yield


def load_fixture_json(name: str) -> dict:
    """Load a JSON fixture by file name."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def siri_payload() -> dict:
    return load_fixture_json("siri_stop_monitoring.json")


@pytest.fixture
def siri_empty() -> dict:
    return load_fixture_json("siri_empty.json")


@pytest.fixture
def places_payload() -> dict:
    return load_fixture_json("navitia_places.json")


@pytest.fixture
def lines_payload() -> dict:
    return load_fixture_json("navitia_lines.json")


@pytest.fixture
def journeys_payload() -> dict:
    return load_fixture_json("navitia_journeys.json")


@pytest.fixture
def walking_payload() -> dict:
    return load_fixture_json("navitia_walking.json")


@pytest.fixture(autouse=True)
def reset_api_state():
    """Clear module-level per-key API state between tests."""
    from custom_components.idfm_departure import api

    for state in (api._USAGE, api._USAGE_DAY, api._PREFIX, api._NO_LINEREF):
        state.clear()
    yield


@pytest.fixture(autouse=True)
def stub_frontend_deps(request):
    """hass_frontend is not installed: mark http/frontend as already set up."""
    if "hass" in request.fixturenames:
        hass = request.getfixturevalue("hass")
        hass.config.components.add("http")
        hass.config.components.add("frontend")
    yield

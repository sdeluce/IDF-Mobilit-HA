"""Tests for the PRIM client (HTTP mocked with aioclient_mock)."""

from datetime import UTC, datetime

import aiohttp
import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from custom_components.idfm_departure.api import (
    PrimAuthError,
    PrimClient,
    PrimConnectionError,
    PrimNotFoundError,
    PrimRateLimitError,
    PrimServerError,
)
from custom_components.idfm_departure.const import (
    NAVITIA_BASE_URL,
    SIRI_STOP_MONITORING_URL,
)

from .conftest import load_fixture_json

PLACES = f"{NAVITIA_BASE_URL}/places"
PLACES_COV = f"{NAVITIA_BASE_URL}/coverage/idfm/places"
JOURNEYS = f"{NAVITIA_BASE_URL}/journeys"
WHEN = datetime(2026, 10, 7, 7, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset_shared_state():
    from custom_components.idfm_departure import api

    for d in (api._USAGE, api._USAGE_DAY, api._PREFIX):
        d.clear()
    api._NO_LINEREF.clear()
    yield


@pytest.fixture
async def client(hass, aioclient_mock):
    return PrimClient(async_get_clientsession(hass), "SECRET")


async def test_validate_key_sends_headers_and_counts(client, aioclient_mock):
    aioclient_mock.get(PLACES, json=load_fixture_json("navitia_places.json"))
    await client.validate_key()
    assert aioclient_mock.call_count == 1
    method, url, _, headers = aioclient_mock.mock_calls[0]
    assert url.query["q"] == "Chatelet" and url.query["count"] == "1"
    assert headers["apikey"] == "SECRET"
    assert headers["Accept"] == "application/json"
    assert client.usage == {"siri": 0, "navitia": 1}


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, PrimAuthError),
        (403, PrimAuthError),
        (429, PrimRateLimitError),
        (500, PrimServerError),
        (503, PrimServerError),
    ],
)
async def test_http_errors_mapped(client, aioclient_mock, status, exc):
    aioclient_mock.get(PLACES, status=status)
    with pytest.raises(exc):
        await client.validate_key()


async def test_invalid_json_and_transport_errors(client, aioclient_mock):
    aioclient_mock.get(PLACES, text="<html>not json</html>")
    with pytest.raises(PrimConnectionError):
        await client.validate_key()
    aioclient_mock.clear_requests()
    aioclient_mock.get(PLACES, exc=TimeoutError())
    with pytest.raises(PrimConnectionError):
        await client.validate_key()
    aioclient_mock.clear_requests()
    aioclient_mock.get(PLACES, exc=aiohttp.ClientError("boom"))
    with pytest.raises(PrimConnectionError):
        await client.validate_key()


async def test_navitia_prefix_fallback_is_cached(client, aioclient_mock):
    aioclient_mock.get(PLACES, status=404)
    aioclient_mock.get(PLACES_COV, json=load_fixture_json("navitia_places.json"))
    places = await client.search_places("chatelet", ("stop_area",))
    assert [p.id for p in places] == [
        "stop_area:IDFM:71517", "poi:osm:1", "admin:fr:75056"]
    assert aioclient_mock.call_count == 2  # "" 404 then /coverage/idfm
    q = aioclient_mock.mock_calls[1][1].query
    assert q["q"] == "chatelet" and q.getall("type[]") == ["stop_area"]
    await client.search_places("chatelet")
    # cached prefix: exactly one extra call, straight to coverage path
    assert aioclient_mock.call_count == 3
    assert str(aioclient_mock.mock_calls[2][1]).startswith(PLACES_COV)
    assert aioclient_mock.mock_calls[2][1].query.getall("type[]") == ["stop_area", "address"]
    assert client.usage["navitia"] == 3


async def test_all_prefixes_404(client, aioclient_mock):
    aioclient_mock.get(PLACES, status=404)
    aioclient_mock.get(PLACES_COV, status=404)
    with pytest.raises(PrimNotFoundError):
        await client.validate_key()
    assert aioclient_mock.call_count == 2


async def test_stop_area_lines(client, aioclient_mock):
    url = f"{NAVITIA_BASE_URL}/stop_areas/stop_area:IDFM:71517/lines"
    aioclient_mock.get(url, json=load_fixture_json("navitia_lines.json"))
    lines = await client.get_stop_area_lines("stop_area:IDFM:71517")
    assert [(x.code, x.mode) for x in lines] == [
        ("A", "rer"), ("91", "bus"), ("14", "metro"), ("", "other")]


async def test_siri_with_line_ref(client, aioclient_mock):
    aioclient_mock.get(
        SIRI_STOP_MONITORING_URL, json=load_fixture_json("siri_stop_monitoring.json"))
    visits = await client.get_stop_monitoring(
        "STIF:StopArea:SP:71517:", "STIF:Line::C01742:")
    assert len(visits) == 6
    q = aioclient_mock.mock_calls[0][1].query
    assert q["MonitoringRef"] == "STIF:StopArea:SP:71517:"
    assert q["LineRef"] == "STIF:Line::C01742:"
    assert client.usage == {"siri": 1, "navitia": 0}


async def test_siri_empty_returns_empty_list(client, aioclient_mock):
    aioclient_mock.get(SIRI_STOP_MONITORING_URL, json=load_fixture_json("siri_empty.json"))
    assert await client.get_stop_monitoring("STIF:StopArea:SP:71517:") == []
    aioclient_mock.clear_requests()
    aioclient_mock.get(SIRI_STOP_MONITORING_URL, json={})
    assert await client.get_stop_monitoring("STIF:StopArea:SP:71517:") == []


async def test_siri_400_retries_without_line_ref(client, aioclient_mock):
    payload = load_fixture_json("siri_stop_monitoring.json")

    async def side_effect(method, url, data):
        if "LineRef" in url.query:
            return AiohttpClientMockResponse(method, url, status=400)
        return AiohttpClientMockResponse(method, url, json=payload)

    aioclient_mock.get(SIRI_STOP_MONITORING_URL, side_effect=side_effect)
    visits = await client.get_stop_monitoring(
        "STIF:StopArea:SP:71517:", "STIF:Line::C01742:")
    assert len(visits) == 6
    assert aioclient_mock.call_count == 2
    assert "LineRef" in aioclient_mock.mock_calls[0][1].query
    assert "LineRef" not in aioclient_mock.mock_calls[1][1].query
    assert client.usage["siri"] == 2


async def test_get_journeys_params_and_parse(client, aioclient_mock):
    aioclient_mock.get(JOURNEYS, json=load_fixture_json("navitia_journeys.json"))
    opts = await client.get_journeys("2.347;48.8584", "stop_area:IDFM:71517", WHEN, count=2)
    assert [o.line_code for o in opts] == ["A", "91"]
    q = aioclient_mock.mock_calls[0][1].query
    assert q["from"] == "2.347;48.8584" and q["to"] == "stop_area:IDFM:71517"
    assert q["datetime"] == "20261007T090000"  # 07:00Z -> 09:00 Paris
    assert q["data_freshness"] == "realtime" and q["count"] == "2"


async def test_get_journeys_no_solution_is_empty(client, aioclient_mock):
    aioclient_mock.get(JOURNEYS, status=404)
    aioclient_mock.get(f"{NAVITIA_BASE_URL}/coverage/idfm/journeys", status=404)
    assert await client.get_journeys("a", "b", WHEN) == []


async def test_get_walking_time(client, aioclient_mock):
    aioclient_mock.get(JOURNEYS, json=load_fixture_json("navitia_walking.json"))
    assert await client.get_walking_time("2.347;48.8584", "stop_area:IDFM:71517", WHEN) == 412
    q = aioclient_mock.mock_calls[0][1].query
    assert q["direct_path"] == "only"
    assert q.getall("direct_path_mode[]") == ["walking"]


async def test_usage_resets_on_new_paris_day(client, aioclient_mock, monkeypatch):
    from datetime import date

    from custom_components.idfm_departure import api

    aioclient_mock.get(PLACES, json={"places": []})
    await client.validate_key()
    assert client.usage["navitia"] == 1
    monkeypatch.setattr(api, "_paris_today", lambda: date(2099, 1, 1))
    await client.validate_key()
    assert client.usage == {"siri": 0, "navitia": 1}


async def test_siri_400_remembered_second_call_skips_line_ref(client, aioclient_mock):
    payload = load_fixture_json("siri_stop_monitoring.json")

    async def side_effect(method, url, data):
        if "LineRef" in url.query:
            return AiohttpClientMockResponse(method, url, status=400)
        return AiohttpClientMockResponse(method, url, json=payload)

    aioclient_mock.get(SIRI_STOP_MONITORING_URL, side_effect=side_effect)
    await client.get_stop_monitoring("STIF:StopArea:SP:71517:", "STIF:Line::C01742:")
    assert aioclient_mock.call_count == 2
    visits = await client.get_stop_monitoring(
        "STIF:StopArea:SP:71517:", "STIF:Line::C01742:")
    assert len(visits) == 6
    assert aioclient_mock.call_count == 3  # exactly one request on the 2nd call
    assert "LineRef" not in aioclient_mock.mock_calls[2][1].query


async def test_usage_and_prefix_shared_between_clients_same_key(hass, aioclient_mock):
    session = async_get_clientsession(hass)
    c1, c2 = PrimClient(session, "KEY"), PrimClient(session, "KEY")
    other = PrimClient(session, "OTHER")
    aioclient_mock.get(PLACES, status=404)
    aioclient_mock.get(PLACES_COV, json={"places": []})
    await c1.search_places("x")  # probes: 2 calls
    assert aioclient_mock.call_count == 2
    await c2.search_places("x")  # prefix shared -> 1 call straight to coverage
    assert aioclient_mock.call_count == 3
    assert str(aioclient_mock.mock_calls[2][1]).startswith(PLACES_COV)
    assert c1.usage == c2.usage == {"siri": 0, "navitia": 3}
    assert other.usage == {"siri": 0, "navitia": 0}
    assert "KEY" not in "".join(
        k for k in __import__(
            "custom_components.idfm_departure.api", fromlist=["_USAGE"])._USAGE)


async def test_usage_reset_is_shared_per_key(hass, aioclient_mock, monkeypatch):
    from datetime import date

    from custom_components.idfm_departure import api

    session = async_get_clientsession(hass)
    c1, c2 = PrimClient(session, "KEY"), PrimClient(session, "KEY")
    aioclient_mock.get(PLACES, json={"places": []})
    await c1.validate_key()
    await c2.validate_key()
    assert c1.usage["navitia"] == 2
    monkeypatch.setattr(api, "_paris_today", lambda: date(2099, 1, 1))
    await c2.validate_key()
    assert c1.usage == {"siri": 0, "navitia": 1}


@pytest.mark.parametrize("err_id", ["no_solution", "date_out_of_bounds"])
async def test_journeys_404_with_navitia_error_does_not_probe(
    client, aioclient_mock, err_id
):
    aioclient_mock.get(JOURNEYS, status=404, json={"error": {"id": err_id}})
    aioclient_mock.get(f"{NAVITIA_BASE_URL}/coverage/idfm/journeys", status=404)
    assert await client.get_journeys("a", "b", WHEN) == []
    assert aioclient_mock.call_count == 1  # no probing of /coverage/idfm
    assert await client.get_walking_time("a", "b", WHEN) is None
    assert aioclient_mock.call_count == 2  # prefix "" cached as valid


async def test_plain_404_still_probes(client, aioclient_mock):
    aioclient_mock.get(JOURNEYS, status=404, text="Not Found")
    aioclient_mock.get(
        f"{NAVITIA_BASE_URL}/coverage/idfm/journeys",
        json=load_fixture_json("navitia_journeys.json"))
    opts = await client.get_journeys("a", "b", WHEN)
    assert opts and aioclient_mock.call_count == 2

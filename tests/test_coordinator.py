"""Coordinator tests with a mocked PrimClient."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.idfm_departure.api import (
    PrimAuthError,
    PrimClient,
    PrimConnectionError,
    PrimNotFoundError,
    PrimRateLimitError,
    PrimServerError,
)
from custom_components.idfm_departure.const import (
    CONF_API_KEY,
    CONF_DESTINATION_ID,
    CONF_HOME_LAT,
    CONF_HOME_LON,
    CONF_LINE_ID,
    CONF_MODE,
    CONF_STOP_DEST_ID,
    CONF_STOP_DEST_NAME,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_WALK_OVERRIDE_MIN,
    DOMAIN,
    MODE_JOURNEY,
    MODE_STOP,
    SOURCE_NAVITIA,
    SOURCE_SIRI,
    WALK_SOURCE_AUTO,
    WALK_SOURCE_MANUAL,
)
from custom_components.idfm_departure.coordinator import (
    CONF_STOP_LAT,
    CONF_STOP_LON,
    WALK_SOURCE_ESTIMATED,
    IdfmCoordinator,
)
from custom_components.idfm_departure.logic import estimate_walk_s
from custom_components.idfm_departure.models import (
    JourneyOption,
    LineInfo,
    StopVisit,
)

# 10:00 Paris (CEST, UTC+2) -> inside the default 05:30-01:00 window
NOW = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
# 03:00 Paris -> outside the window
NIGHT = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)

STOP = "stop_area:IDFM:71517"
LINE = "line:IDFM:C01742"


def _visit(minutes: int, line_ref: str = "STIF:Line::C01742:") -> StopVisit:
    return StopVisit(
        line_ref=line_ref,
        line_name="A",
        destination="Marne-la-Vallée",
        direction=None,
        stop_ref="STIF:StopArea:SP:71517:",
        departure_at=NOW + timedelta(minutes=minutes),
        realtime=True,
    )


def _journey(minutes: int, walk_s: int = 300) -> JourneyOption:
    return JourneyOption(
        walk_s=walk_s,
        pt_departure_at=NOW + timedelta(minutes=minutes),
        stop_point_id="stop_point:IDFM:22113",
        stop_name="Châtelet",
        line_id=LINE,
        line_code="A",
        mode="rer",
        direction="Cergy",
        arrival_at=NOW + timedelta(minutes=minutes + 30),
    )


def _client() -> MagicMock:
    client = MagicMock(spec=PrimClient)
    client.usage = {"siri": 0, "navitia": 0}
    client.get_walking_time = AsyncMock(return_value=300)
    client.get_stop_area_lines = AsyncMock(
        return_value=[
            LineInfo(
                id=LINE, code="A", name="RER A", mode="rer", network=None, color=None
            )
        ]
    )
    client.get_stop_monitoring = AsyncMock(return_value=[_visit(15), _visit(25)])
    client.get_journeys = AsyncMock(return_value=[_journey(20), _journey(40)])
    return client


async def _make(hass, client, data=None, options=None) -> IdfmCoordinator:
    base = {
        CONF_API_KEY: "k",
        CONF_HOME_LAT: 48.85,
        CONF_HOME_LON: 2.35,
        CONF_MODE: MODE_STOP,
        CONF_STOP_ID: STOP,
        CONF_STOP_NAME: "Châtelet",
    }
    base.update(data or {})
    entry = MockConfigEntry(domain=DOMAIN, data=base, options=options or {})
    entry.add_to_hass(hass)
    return IdfmCoordinator(hass, entry, client)


async def test_stop_mode_computes_leave_at(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    coord = await _make(hass, client)
    data = await coord._async_update_data()
    # default margin 3 min, walk 300 s -> leave 8 min before departure
    assert [d.leave_at for d in data.departures] == [
        NOW + timedelta(minutes=7),
        NOW + timedelta(minutes=17),
    ]
    assert data.departures[0].line == "A"
    assert data.departures[0].source == SOURCE_SIRI
    assert data.walk_s == 300
    assert data.walk_source == WALK_SOURCE_AUTO
    assert data.active is True
    client.get_stop_monitoring.assert_awaited_once_with(
        "STIF:StopArea:SP:71517:", None
    )
    await coord.async_shutdown()


async def test_line_filter_passed_and_applied(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_stop_monitoring.return_value = [
        _visit(15),
        _visit(16, line_ref="STIF:Line::C01384:"),
    ]
    coord = await _make(hass, client, data={CONF_LINE_ID: LINE})
    data = await coord._async_update_data()
    client.get_stop_monitoring.assert_awaited_once_with(
        "STIF:StopArea:SP:71517:", "STIF:Line::C01742:"
    )
    assert len(data.departures) == 1
    await coord.async_shutdown()


async def test_outside_window_no_api_call(hass, freezer) -> None:
    freezer.move_to(NIGHT)
    client = _client()
    coord = await _make(hass, client)
    data = await coord._async_update_data()
    assert data.active is False
    assert data.departures == []
    for m in (
        client.get_walking_time,
        client.get_stop_monitoring,
        client.get_journeys,
        client.get_stop_area_lines,
    ):
        m.assert_not_awaited()
    await coord.async_shutdown()


async def test_outside_window_keeps_previous_data(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    coord = await _make(hass, client)
    coord.data = await coord._async_update_data()
    calls = client.get_stop_monitoring.await_count
    freezer.move_to(NIGHT)
    data = await coord._async_update_data()
    assert data.active is False
    assert len(data.departures) == 2
    assert client.get_stop_monitoring.await_count == calls
    await coord.async_shutdown()


async def test_force_refresh_ignores_window(hass, freezer) -> None:
    freezer.move_to(NIGHT)
    client = _client()
    coord = await _make(hass, client)
    await coord.async_force_refresh()
    client.get_stop_monitoring.assert_awaited_once()
    assert coord.data.active is True
    # flag is one-shot
    await coord._async_update_data()
    client.get_stop_monitoring.assert_awaited_once()
    await coord.async_shutdown()


async def test_walk_and_lines_cached(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    coord = await _make(hass, client)
    await coord._async_update_data()
    freezer.move_to(NOW + timedelta(minutes=2))
    await coord._async_update_data()
    assert client.get_walking_time.await_count == 1
    assert client.get_stop_area_lines.await_count == 1
    assert client.get_stop_monitoring.await_count == 2
    freezer.move_to(NOW + timedelta(days=1, minutes=1))
    await coord._async_update_data()
    assert client.get_walking_time.await_count == 2
    assert client.get_stop_area_lines.await_count == 2
    await coord.async_shutdown()


async def test_walk_override(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    coord = await _make(hass, client, options={CONF_WALK_OVERRIDE_MIN: 10})
    data = await coord._async_update_data()
    client.get_walking_time.assert_not_awaited()
    assert data.walk_s == 600
    assert data.walk_source == WALK_SOURCE_MANUAL
    assert data.departures[0].leave_at == NOW + timedelta(minutes=2)
    await coord.async_shutdown()


async def test_walk_unavailable_raises(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_walking_time.return_value = None
    coord = await _make(hass, client)
    with pytest.raises(UpdateFailed, match="walk_override_min"):
        await coord._async_update_data()
    await coord.async_shutdown()


async def test_lines_failure_non_fatal(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_stop_area_lines.side_effect = PrimServerError("boom")
    coord = await _make(hass, client)
    data = await coord._async_update_data()
    assert len(data.departures) == 2
    # falls back to PublishedLineName
    assert data.departures[0].line == "A"
    await coord.async_shutdown()


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (PrimAuthError("401"), ConfigEntryAuthFailed),
        (PrimRateLimitError("429"), UpdateFailed),
        (PrimServerError("500"), UpdateFailed),
        (PrimConnectionError("timeout"), UpdateFailed),
    ],
)
async def test_error_mapping(hass, freezer, exc, expected) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_stop_monitoring.side_effect = exc
    coord = await _make(hass, client)
    with pytest.raises(expected) as info:
        await coord._async_update_data()
    if isinstance(exc, PrimRateLimitError):
        assert "quota exceeded (429)" in str(info.value)
    await coord.async_shutdown()


async def test_other_prim_error_is_update_failed(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_stop_monitoring.side_effect = PrimNotFoundError("404")
    coord = await _make(hass, client)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()
    await coord.async_shutdown()


async def test_journey_stop_name_from_first_pt_section(hass, freezer) -> None:
    freezer.move_to(NOW)
    coord = await _make(hass, _client(), data={**JOURNEY, CONF_STOP_NAME: "Stale name"})
    data = await coord._async_update_data()
    assert data.stop_name == "Châtelet"  # JourneyOption.stop_name, not entry data
    await coord.async_shutdown()


JOURNEY = {CONF_MODE: MODE_JOURNEY, CONF_DESTINATION_ID: "stop_area:IDFM:99999"}


async def test_journey_mode_merges_siri_and_navitia(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    # SIRI refines the first journey (+1 min of delay) and adds one more
    client.get_stop_monitoring.return_value = [_visit(21), _visit(55)]
    coord = await _make(hass, client, data=JOURNEY)
    data = await coord._async_update_data()
    client.get_journeys.assert_awaited_once()
    client.get_stop_monitoring.assert_awaited_once_with(
        "STIF:StopPoint:Q:22113:", "STIF:Line::C01742:"
    )
    client.get_walking_time.assert_not_awaited()
    # SIRI covers the same line up to its horizon (+55 min) so it overrides
    # both Navitia entries (20 and 40 min); no duplicate remains.
    assert [(d.stop_departure, d.source) for d in data.departures] == [
        (NOW + timedelta(minutes=21), SOURCE_SIRI),
        (NOW + timedelta(minutes=55), SOURCE_SIRI),
    ]
    assert data.walk_s == 300
    await coord.async_shutdown()


async def test_journey_siri_failure_falls_back_to_navitia(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_stop_monitoring.side_effect = PrimServerError("siri down")
    coord = await _make(hass, client, data=JOURNEY)
    data = await coord._async_update_data()
    assert len(data.departures) == 2
    assert {d.source for d in data.departures} == {SOURCE_NAVITIA}
    assert all(not d.realtime for d in data.departures)
    await coord.async_shutdown()


async def test_journey_siri_auth_error_propagates(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_stop_monitoring.side_effect = PrimAuthError("403")
    coord = await _make(hass, client, data=JOURNEY)
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()
    await coord.async_shutdown()


async def test_journey_cached_between_updates(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    coord = await _make(hass, client, data=JOURNEY)
    await coord._async_update_data()
    freezer.move_to(NOW + timedelta(minutes=5))
    await coord._async_update_data()
    assert client.get_journeys.await_count == 1  # default refresh 10 min
    freezer.move_to(NOW + timedelta(minutes=11))
    await coord._async_update_data()
    assert client.get_journeys.await_count == 2
    await coord.async_shutdown()


async def test_journey_no_results_is_empty_not_error(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_journeys.return_value = []
    coord = await _make(hass, client, data=JOURNEY)
    data = await coord._async_update_data()
    assert data.departures == []
    client.get_stop_monitoring.assert_not_awaited()
    await coord.async_shutdown()


async def test_journey_datetime_is_now_plus_margin(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    coord = await _make(hass, client, data=JOURNEY, options={"margin_min": 7})
    await coord._async_update_data()
    assert client.get_journeys.await_args.args[2] == NOW + timedelta(minutes=7)
    await coord.async_shutdown()


async def test_journey_siri_value_error_falls_back(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_stop_monitoring.side_effect = ValueError("bad id")
    coord = await _make(hass, client, data=JOURNEY)
    data = await coord._async_update_data()
    assert {d.source for d in data.departures} == {SOURCE_NAVITIA}
    assert len(data.departures) == 2
    await coord.async_shutdown()


async def test_journeys_refresh_error_keeps_cache(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    coord = await _make(hass, client, data=JOURNEY)
    await coord._async_update_data()
    client.get_journeys.side_effect = PrimServerError("500")
    freezer.move_to(NOW + timedelta(minutes=11))
    data = await coord._async_update_data()
    assert client.get_journeys.await_count == 2
    assert len(data.departures) >= 1
    await coord.async_shutdown()


async def test_journeys_error_without_cache_fails(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_journeys.side_effect = PrimServerError("500")
    coord = await _make(hass, client, data=JOURNEY)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()
    await coord.async_shutdown()


async def test_walk_estimated_from_stop_coords(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_walking_time.return_value = None
    coord = await _make(
        hass, client, data={CONF_STOP_LAT: 48.86, CONF_STOP_LON: 2.36}
    )
    data = await coord._async_update_data()
    assert data.walk_s == estimate_walk_s(48.85, 2.35, 48.86, 2.36)
    assert data.walk_s > 0
    assert data.walk_source == WALK_SOURCE_ESTIMATED
    await coord.async_shutdown()


async def test_walk_api_retry_backoff_one_hour(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_walking_time.return_value = None
    coord = await _make(hass, client)
    for delta in (0, 10, 30):
        freezer.move_to(NOW + timedelta(minutes=delta))
        with pytest.raises(UpdateFailed, match="walk_override_min"):
            await coord._async_update_data()
    assert client.get_walking_time.await_count == 1
    freezer.move_to(NOW + timedelta(minutes=61))
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()
    assert client.get_walking_time.await_count == 2
    await coord.async_shutdown()


async def test_lines_error_retried_after_15_min(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    client.get_stop_area_lines.side_effect = PrimServerError("boom")
    coord = await _make(hass, client)
    await coord._async_update_data()
    freezer.move_to(NOW + timedelta(minutes=10))
    await coord._async_update_data()
    assert client.get_stop_area_lines.await_count == 1
    freezer.move_to(NOW + timedelta(minutes=16))
    await coord._async_update_data()
    assert client.get_stop_area_lines.await_count == 2
    await coord.async_shutdown()


DEST = {CONF_STOP_DEST_ID: "stop_area:IDFM:62000", CONF_STOP_DEST_NAME: "La Défense"}


def _dest_client() -> MagicMock:
    client = _client()
    # only the first SIRI visit (+15) reaches the destination
    client.get_journeys = AsyncMock(return_value=[_journey(15)])
    return client


async def test_stop_dest_filters_and_computes_arrival(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _dest_client()
    coord = await _make(hass, client, data=DEST)
    data = await coord._async_update_data()
    client.get_journeys.assert_awaited_once()
    args, kwargs = client.get_journeys.await_args
    assert args[0] == STOP
    assert args[1] == DEST[CONF_STOP_DEST_ID]
    # default margin 3 min + walk 300 s
    assert args[2] == NOW + timedelta(seconds=300, minutes=3)
    assert kwargs["max_nb_transfers"] == 0
    assert kwargs["count"] == 6
    assert len(data.departures) == 1  # the +25 visit is another branch
    assert data.departures[0].stop_departure == NOW + timedelta(minutes=15)
    assert data.departures[0].arrival_at == NOW + timedelta(minutes=45)
    assert coord.destination_filter_active is True
    assert coord.destination_name == "La Défense"
    await coord.async_shutdown()


async def test_stop_dest_direct_only_false_allows_transfers(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _dest_client()
    coord = await _make(hass, client, data=DEST, options={"direct_only": False})
    await coord._async_update_data()
    assert client.get_journeys.await_args.kwargs["max_nb_transfers"] is None
    await coord.async_shutdown()


async def test_stop_dest_navitia_failure_falls_back_to_siri(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _dest_client()
    client.get_journeys = AsyncMock(side_effect=PrimServerError("boom"))
    coord = await _make(hass, client, data=DEST)
    data = await coord._async_update_data()
    assert len(data.departures) == 2  # plain SIRI, unfiltered
    assert coord.destination_filter_active is False
    await coord.async_shutdown()


async def test_stop_dest_navitia_failure_keeps_cache(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _dest_client()
    coord = await _make(hass, client, data=DEST, options={"journey_refresh_min": 5})
    await coord._async_update_data()
    client.get_journeys = AsyncMock(side_effect=PrimServerError("boom"))
    freezer.move_to(NOW + timedelta(minutes=6))  # cache stale, leave_at is NOW+7
    data = await coord._async_update_data()
    client.get_journeys.assert_awaited_once()  # refresh was attempted and failed
    assert len(data.departures) == 1
    assert coord.destination_filter_active is True
    await coord.async_shutdown()


async def test_stop_dest_failure_backs_off_5_min(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _dest_client()
    client.get_journeys = AsyncMock(side_effect=PrimServerError("boom"))
    coord = await _make(hass, client, data=DEST)
    await coord._async_update_data()
    freezer.move_to(NOW + timedelta(minutes=2))
    data = await coord._async_update_data()
    assert client.get_journeys.await_count == 1  # backoff: no Navitia call
    assert len(data.departures) == 2  # plain SIRI fallback
    assert coord.destination_filter_active is False
    freezer.move_to(NOW + timedelta(minutes=5, seconds=1))
    await coord._async_update_data()
    assert client.get_journeys.await_count == 2
    await coord.async_shutdown()


async def test_stop_dest_failure_with_cache_backs_off(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _dest_client()
    coord = await _make(hass, client, data=DEST, options={"journey_refresh_min": 5})
    await coord._async_update_data()
    good = client.get_journeys
    client.get_journeys = AsyncMock(side_effect=PrimServerError("boom"))
    freezer.move_to(NOW + timedelta(minutes=6))
    await coord._async_update_data()
    freezer.move_to(NOW + timedelta(minutes=8))
    await coord._async_update_data()
    assert client.get_journeys.await_count == 1  # second scan within 5 min skipped
    freezer.move_to(NOW + timedelta(minutes=11, seconds=1))
    await coord._async_update_data()
    assert client.get_journeys.await_count == 2
    assert good.await_count == 1
    await coord.async_shutdown()


async def test_stop_dest_journeys_cached_between_scans(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _dest_client()
    coord = await _make(hass, client, data=DEST)
    await coord._async_update_data()
    freezer.move_to(NOW + timedelta(minutes=5))
    await coord._async_update_data()
    assert client.get_journeys.await_count == 1
    assert client.get_stop_monitoring.await_count == 2  # SIRI every scan
    freezer.move_to(NOW + timedelta(minutes=11))
    await coord._async_update_data()
    assert client.get_journeys.await_count == 2
    await coord.async_shutdown()


async def test_stop_without_dest_makes_no_journey_call(hass, freezer) -> None:
    freezer.move_to(NOW)
    client = _client()
    coord = await _make(hass, client)
    data = await coord._async_update_data()
    client.get_journeys.assert_not_awaited()
    assert len(data.departures) == 2
    assert coord.destination_filter_active is True
    assert coord.destination_name is None
    await coord.async_shutdown()

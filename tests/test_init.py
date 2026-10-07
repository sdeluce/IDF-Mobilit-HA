"""Integration-level tests: real config entry, PrimClient methods patched."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.idfm_departure.api import PrimAuthError, PrimClient, PrimServerError
from custom_components.idfm_departure.const import (
    CONF_API_KEY,
    CONF_HOME_LAT,
    CONF_HOME_LON,
    CONF_MODE,
    CONF_STOP_DEST_ID,
    CONF_STOP_DEST_NAME,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DOMAIN,
    MODE_STOP,
    SERVICE_REFRESH,
)
from custom_components.idfm_departure.models import JourneyOption, LineInfo, StopVisit

# 10:00 Paris: inside the default active window
NOW = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
STOP = "stop_area:IDFM:71517"
LINE = "line:IDFM:C01742"
# default margin 3 min + walk 300 s = leave 8 min before the stop departure;
# a departure 8 min 20 s out gives leave_at = NOW + 200 s
LEAVE_AT = NOW + timedelta(seconds=200)


def _visit() -> StopVisit:
    return StopVisit(
        line_ref="STIF:Line::C01742:",
        line_name="A",
        destination="Marne-la-Vallée",
        direction=None,
        stop_ref="STIF:StopArea:SP:71517:",
        departure_at=LEAVE_AT + timedelta(minutes=8),
        realtime=True,
        platform="2",
    )


class _Mocks:
    def __init__(self) -> None:
        self.walk = AsyncMock(return_value=300)
        self.lines = AsyncMock(
            return_value=[
                LineInfo(id=LINE, code="A", name="RER A", mode="rer", network=None,
                         color="#E2231A", text_color="#FFFFFF")
            ]
        )
        self.monitoring = AsyncMock(return_value=[_visit()])

    def all(self) -> tuple[AsyncMock, ...]:
        return self.walk, self.lines, self.monitoring

    def counts(self) -> list[int]:
        return [m.await_count for m in self.all()]


def _patches(m: _Mocks) -> ExitStack:
    stack = ExitStack()
    stack.enter_context(patch.object(PrimClient, "get_walking_time", m.walk))
    stack.enter_context(patch.object(PrimClient, "get_stop_area_lines", m.lines))
    stack.enter_context(patch.object(PrimClient, "get_stop_monitoring", m.monitoring))
    return stack


def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Châtelet",
        unique_id="stop_test",
        data={
            CONF_API_KEY: "k",
            CONF_HOME_LAT: 48.85,
            CONF_HOME_LON: 2.35,
            CONF_MODE: MODE_STOP,
            CONF_STOP_ID: STOP,
            CONF_STOP_NAME: "Châtelet",
        },
    )
    entry.add_to_hass(hass)
    return entry


def _eid(hass, platform: str, entry: MockConfigEntry, key: str) -> str:
    reg = er.async_get(hass)
    eid = reg.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
    assert eid is not None, key
    return eid


async def test_setup_creates_entities_with_states(hass, freezer) -> None:
    freezer.move_to(NOW)
    m = _Mocks()
    entry = _entry(hass)
    with _patches(m):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED

        leave = hass.states.get(_eid(hass, "sensor", entry, "leave_at"))
        assert leave.state == LEAVE_AT.isoformat()
        minutes = hass.states.get(_eid(hass, "sensor", entry, "minutes_until_leave"))
        assert minutes.state == "3"  # floor(200 s / 60)
        assert hass.states.get(_eid(hass, "sensor", entry, "line")).state == "A"
        assert hass.states.get(_eid(hass, "sensor", entry, "walk_time")).state == "5"
        assert (
            hass.states.get(_eid(hass, "binary_sensor", entry, "time_to_leave")).state
            == "off"
        )
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED


async def test_local_tick_makes_no_api_call_and_flips_binary_sensor(hass, freezer) -> None:
    freezer.move_to(NOW)
    m = _Mocks()
    entry = _entry(hass)
    with _patches(m):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        before = m.counts()
        assert before[2] == 1
        binary = _eid(hass, "binary_sensor", entry, "time_to_leave")
        minutes = _eid(hass, "sensor", entry, "minutes_until_leave")
        assert hass.states.get(binary).state == "off"  # 3 min left

        # stay below the 120 s scan interval so only the 30 s local tick fires
        for secs, exp_minutes, exp_binary in ((30, "2", "off"), (60, "2", "off"), (90, "1", "on")):
            freezer.move_to(NOW + timedelta(seconds=secs))
            async_fire_time_changed(hass, NOW + timedelta(seconds=secs))
            await hass.async_block_till_done()
            assert hass.states.get(minutes).state == exp_minutes, secs
            assert hass.states.get(binary).state == exp_binary, secs
            assert m.counts() == before, secs

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_refresh_service_calls_api_and_raises_on_failure(hass, freezer) -> None:
    freezer.move_to(NOW)
    m = _Mocks()
    entry = _entry(hass)
    with _patches(m):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        calls = m.monitoring.await_count
        await hass.services.async_call(DOMAIN, SERVICE_REFRESH, {}, blocking=True)
        assert m.monitoring.await_count == calls + 1

        m.monitoring.side_effect = PrimServerError("boom 500")
        with pytest.raises(HomeAssistantError, match="boom 500"):
            await hass.services.async_call(DOMAIN, SERVICE_REFRESH, {}, blocking=True)

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_auth_error_starts_reauth(hass, freezer) -> None:
    freezer.move_to(NOW)
    m = _Mocks()
    m.monitoring.side_effect = PrimAuthError("401")
    entry = _entry(hass)
    with _patches(m):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_leave_at_attributes_for_card(hass, freezer) -> None:
    freezer.move_to(NOW)
    m = _Mocks()
    entry = _entry(hass)
    with _patches(m):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        st = hass.states.get(_eid(hass, "sensor", entry, "leave_at"))
        a = st.attributes
        assert a["stop_name"] == "Châtelet"
        assert a["line"] == "A"
        assert a["line_color"] == "#E2231A"
        assert a["line_text_color"] == "#FFFFFF"
        assert a["mode"] == "rer"
        assert a["stop_departure"] == (LEAVE_AT + timedelta(minutes=8)).isoformat()
        assert a["walk_min"] == 5
        assert a["realtime"] is True
        assert a["direction"] == "Marne-la-Vallée"
        assert a["platform"] == "2"
        assert a["departures"][0]["platform"] == "2"
        assert a["departures"][0]["line_color"] == "#E2231A"
        assert a["departures"][0]["line_text_color"] == "#FFFFFF"
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_static_path_registered_once(hass) -> None:
    from unittest.mock import MagicMock

    from custom_components.idfm_departure import (
        STATIC_URL,
        _async_register_frontend,
    )

    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    with patch("custom_components.idfm_departure.add_extra_js_url") as add_js:
        await _async_register_frontend(hass)
        await _async_register_frontend(hass)
    hass.http.async_register_static_paths.assert_awaited_once()
    (cfgs,) = hass.http.async_register_static_paths.await_args.args
    assert cfgs[0].url_path == STATIC_URL == "/idfm_departure_static"
    assert cfgs[0].path.endswith("custom_components/idfm_departure/www")
    assert cfgs[0].cache_headers is False
    add_js.assert_called_once()
    assert add_js.call_args.args[1] == "/idfm_departure_static/idfm-departure-card.js?v=0.1.0"


async def test_arrival_sensor_only_with_destination(hass, freezer) -> None:
    freezer.move_to(NOW)
    m = _Mocks()
    entry = _entry(hass)
    reg = er.async_get(hass)
    with _patches(m):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_arrival_at") is None
        attrs = hass.states.get(_eid(hass, "sensor", entry, "leave_at")).attributes
        assert attrs["arrival_at"] is None
        assert attrs["destination_name"] is None
        assert attrs["destination_filter_active"] is True


async def test_arrival_sensor_with_stop_destination(hass, freezer) -> None:
    freezer.move_to(NOW)
    m = _Mocks()
    arrival = _visit().departure_at + timedelta(minutes=30)
    journey = JourneyOption(
        walk_s=0,
        pt_departure_at=_visit().departure_at,
        stop_point_id="stop_point:IDFM:22113",
        stop_name="Châtelet",
        line_id=LINE,
        line_code="A",
        mode="rer",
        direction=None,
        arrival_at=arrival,
    )
    journeys = AsyncMock(return_value=[journey])
    entry = _entry(hass)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_STOP_DEST_ID: "stop_area:IDFM:62000",
            CONF_STOP_DEST_NAME: "La Défense",
        },
    )
    with _patches(m), patch.object(PrimClient, "get_journeys", journeys):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        state = hass.states.get(_eid(hass, "sensor", entry, "arrival_at"))
        assert state.state == arrival.isoformat()
        attrs = hass.states.get(_eid(hass, "sensor", entry, "leave_at")).attributes
        assert attrs["arrival_at"] == arrival.isoformat()
        assert attrs["destination_name"] == "La Défense"
        assert attrs["destination_filter_active"] is True

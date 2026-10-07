"""Config flow tests (PrimClient methods patched)."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.idfm_departure.api import (
    PrimAuthError,
    PrimClient,
    PrimConnectionError,
)
from custom_components.idfm_departure.const import DOMAIN
from custom_components.idfm_departure.models import LineInfo, Place

STOP = Place("stop_area:IDFM:71517", "Châtelet", "stop_area", 48.858, 2.347)
DEST = Place("stop_area:IDFM:62000", "La Défense", "stop_area", 48.89, 2.24)
LINE = LineInfo("line:IDFM:C01742", "A", "RER A", "rer", "RATP", "E2344E")
SETUP = "custom_components.idfm_departure.async_setup_entry"


def _patch(**over):
    methods = {
        "validate_key": AsyncMock(return_value=None),
        "search_places": AsyncMock(return_value=[STOP]),
        "get_stop_area_lines": AsyncMock(return_value=[LINE]),
    }
    methods.update(over)
    return [patch.object(PrimClient, k, v) for k, v in methods.items()]


async def _start(hass, patches, home=True):
    if home:
        hass.states.async_set("zone.home", "zoning", {"latitude": 48.8584, "longitude": 2.347})
    for p in patches:
        p.start()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "KEY", "home_entity": "zone.home"}
    )


async def test_stop_flow_with_line(hass):
    ps = _patch()
    try:
        result = await _start(hass, ps)
        assert result["type"] == FlowResultType.MENU
        fid = result["flow_id"]
        result = await hass.config_entries.flow.async_configure(
            fid, {"next_step_id": "stop_search"}
        )
        result = await hass.config_entries.flow.async_configure(fid, {"query": "chatelet"})
        assert result["step_id"] == "stop_select"
        result = await hass.config_entries.flow.async_configure(fid, {"stop_id": STOP.id})
        assert result["step_id"] == "stop_options"
        with patch(SETUP, return_value=True):
            result = await hass.config_entries.flow.async_configure(
                fid, {"line_id": LINE.id, "direction_filter": " Boissy "}
            )
            assert result["step_id"] == "stop_destination"
            result = await hass.config_entries.flow.async_configure(fid, {})
    finally:
        for p in ps:
            p.stop()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Châtelet (A)"
    d = result["data"]
    assert d["mode"] == "stop"
    assert d["stop_id"] == STOP.id
    assert d["line_id"] == LINE.id
    assert d["direction_filter"] == "Boissy"
    assert d["home_lat"] == 48.8584 and d["home_lon"] == 2.347
    assert d["api_key"] == "KEY"
    assert d["stop_lat"] == STOP.lat and d["stop_lon"] == STOP.lon


async def _to_destination_step(hass, fid):
    await hass.config_entries.flow.async_configure(fid, {"next_step_id": "stop_search"})
    await hass.config_entries.flow.async_configure(fid, {"query": "x"})
    await hass.config_entries.flow.async_configure(fid, {"stop_id": STOP.id})
    result = await hass.config_entries.flow.async_configure(fid, {})
    assert result["step_id"] == "stop_destination"


async def test_stop_flow_with_destination(hass):
    ps = _patch()
    try:
        result = await _start(hass, ps)
        fid = result["flow_id"]
        await _to_destination_step(hass, fid)
        with patch.object(
            PrimClient, "search_places", AsyncMock(return_value=[DEST])
        ) as search:
            result = await hass.config_entries.flow.async_configure(fid, {"query": "defense"})
        assert search.await_args.args == ("defense", ("stop_area",))
        assert result["step_id"] == "stop_destination_select"
        with patch(SETUP, return_value=True):
            result = await hass.config_entries.flow.async_configure(
                fid, {"stop_dest_id": DEST.id}
            )
    finally:
        for p in ps:
            p.stop()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Châtelet → La Défense"
    assert result["data"]["stop_dest_id"] == DEST.id
    assert result["data"]["stop_dest_name"] == "La Défense"


async def test_stop_flow_destination_skipped(hass):
    ps = _patch()
    try:
        result = await _start(hass, ps)
        fid = result["flow_id"]
        await _to_destination_step(hass, fid)
        with patch(SETUP, return_value=True):
            result = await hass.config_entries.flow.async_configure(fid, {"query": "  "})
    finally:
        for p in ps:
            p.stop()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Châtelet"
    assert "stop_dest_id" not in result["data"]
    assert "stop_dest_name" not in result["data"]


async def test_stop_flow_destination_no_results(hass):
    ps = _patch()
    try:
        result = await _start(hass, ps)
        fid = result["flow_id"]
        await _to_destination_step(hass, fid)
        with patch.object(PrimClient, "search_places", AsyncMock(return_value=[])):
            result = await hass.config_entries.flow.async_configure(fid, {"query": "zzz"})
    finally:
        for p in ps:
            p.stop()
    assert result["step_id"] == "stop_destination"
    assert result["errors"] == {"base": "no_results"}


async def test_stop_flow_no_line_title(hass):
    ps = _patch()
    try:
        result = await _start(hass, ps)
        fid = result["flow_id"]
        await hass.config_entries.flow.async_configure(fid, {"next_step_id": "stop_search"})
        await hass.config_entries.flow.async_configure(fid, {"query": "x"})
        await hass.config_entries.flow.async_configure(fid, {"stop_id": STOP.id})
        await hass.config_entries.flow.async_configure(fid, {})
        with patch(SETUP, return_value=True):
            result = await hass.config_entries.flow.async_configure(fid, {})
    finally:
        for p in ps:
            p.stop()
    assert result["title"] == "Châtelet"
    assert "line_id" not in result["data"]
    assert "direction_filter" not in result["data"]


async def test_destination_flow(hass):
    ps = _patch(search_places=AsyncMock(return_value=[DEST]))
    try:
        result = await _start(hass, ps)
        fid = result["flow_id"]
        await hass.config_entries.flow.async_configure(
            fid, {"next_step_id": "destination_search"}
        )
        result = await hass.config_entries.flow.async_configure(fid, {"query": "defense"})
        assert result["step_id"] == "destination_select"
        with patch(SETUP, return_value=True):
            result = await hass.config_entries.flow.async_configure(
                fid, {"destination_id": DEST.id}
            )
    finally:
        for p in ps:
            p.stop()
    assert result["title"] == "Domicile → La Défense"
    assert result["data"]["mode"] == "journey"
    assert result["data"]["destination_id"] == DEST.id


async def test_invalid_auth(hass):
    ps = _patch(validate_key=AsyncMock(side_effect=PrimAuthError("401")))
    try:
        result = await _start(hass, ps)
    finally:
        for p in ps:
            p.stop()
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_cannot_connect(hass):
    ps = _patch(validate_key=AsyncMock(side_effect=PrimConnectionError("x")))
    try:
        result = await _start(hass, ps)
    finally:
        for p in ps:
            p.stop()
    assert result["errors"] == {"base": "cannot_connect"}


async def test_no_home(hass):
    ps = _patch()
    try:
        result = await _start(hass, ps, home=False)
    finally:
        for p in ps:
            p.stop()
    assert result["errors"] == {"base": "no_home"}


async def test_manual_coordinates_win(hass):
    ps = _patch(search_places=AsyncMock(return_value=[DEST]))
    hass.states.async_set("zone.home", "zoning", {"latitude": 1.0, "longitude": 1.0})
    for p in ps:
        p.start()
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        fid = result["flow_id"]
        await hass.config_entries.flow.async_configure(
            fid,
            {"api_key": "K", "home_entity": "zone.home", "home_lat": 48.1, "home_lon": 2.1},
        )
        await hass.config_entries.flow.async_configure(
            fid, {"next_step_id": "destination_search"}
        )
        await hass.config_entries.flow.async_configure(fid, {"query": "d"})
        with patch(SETUP, return_value=True):
            result = await hass.config_entries.flow.async_configure(
                fid, {"destination_id": DEST.id}
            )
    finally:
        for p in ps:
            p.stop()
    assert result["data"]["home_lat"] == 48.1
    assert result["data"]["home_lon"] == 2.1


async def test_no_results(hass):
    ps = _patch(search_places=AsyncMock(return_value=[]))
    try:
        result = await _start(hass, ps)
        fid = result["flow_id"]
        await hass.config_entries.flow.async_configure(fid, {"next_step_id": "stop_search"})
        result = await hass.config_entries.flow.async_configure(fid, {"query": "zzz"})
    finally:
        for p in ps:
            p.stop()
    assert result["step_id"] == "stop_search"
    assert result["errors"] == {"base": "no_results"}


async def test_duplicate_aborts(hass):
    uid = "journey_stop_area:IDFM:62000__48.8584_2.3470"
    MockConfigEntry(domain=DOMAIN, unique_id=uid, data={}).add_to_hass(hass)
    ps = _patch(search_places=AsyncMock(return_value=[DEST]))
    try:
        result = await _start(hass, ps)
        fid = result["flow_id"]
        await hass.config_entries.flow.async_configure(
            fid, {"next_step_id": "destination_search"}
        )
        await hass.config_entries.flow.async_configure(fid, {"query": "d"})
        result = await hass.config_entries.flow.async_configure(
            fid, {"destination_id": DEST.id}
        )
    finally:
        for p in ps:
            p.stop()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="u", data={"api_key": "OLD"})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with (
        patch.object(PrimClient, "validate_key", AsyncMock(return_value=None)),
        patch(SETUP, return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "NEW"}
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["api_key"] == "NEW"


async def test_options_flow(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="u", data={"api_key": "K"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "margin_min": 5,
                "scan_interval_s": 300,
                "journey_refresh_min": 15,
                "active_start": "06:00:00",
                "active_end": "23:00:00",
                "departures_count": 4,
            },
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["margin_min"] == 5
    assert "walk_override_min" not in result["data"]
    assert result["data"]["departures_count"] == 4


async def test_options_quota_exceeded_single_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="u", data={"api_key": "K"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    # 05:30-01:00 = 19.5 h = 70200 s; /60 s = 1170 calls/day > 900
    user = {
        "margin_min": 3,
        "scan_interval_s": 60,
        "journey_refresh_min": 10,
        "active_start": "05:30:00",
        "active_end": "01:00:00",
        "departures_count": 3,
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], user)
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "quota_exceeded"}
    # 120 s -> 585 calls/day: accepted
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**user, "scan_interval_s": 120}
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_options_quota_sums_entries_sharing_key(hass):
    # other entry with same key at 120 s default: 70200/120 = 585 calls/day
    other = MockConfigEntry(domain=DOMAIN, unique_id="o", data={"api_key": "K"})
    other.add_to_hass(hass)
    unrelated = MockConfigEntry(
        domain=DOMAIN, unique_id="x", data={"api_key": "OTHER"},
        options={"scan_interval_s": 60},
    )
    unrelated.add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, unique_id="u", data={"api_key": "K"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    user = {
        "margin_min": 3,
        "scan_interval_s": 300,  # 234 alone, 819 with other: fine
        "journey_refresh_min": 10,
        "active_start": "05:30:00",
        "active_end": "01:00:00",
        "departures_count": 3,
    }
    with patch(SETUP, return_value=True):
        ok = await hass.config_entries.options.async_configure(result["flow_id"], user)
    assert ok["type"] == FlowResultType.CREATE_ENTRY
    result = await hass.config_entries.options.async_init(entry.entry_id)
    # 70200/180 = 390 + 585 = 975 > 900 although 390 alone is fine
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**user, "scan_interval_s": 180}
    )
    assert result["errors"] == {"base": "quota_exceeded"}


_OPTS = {
    "margin_min": 5,
    "scan_interval_s": 300,
    "journey_refresh_min": 15,
    "active_start": "06:00:00",
    "active_end": "23:00:00",
    "departures_count": 4,
}


async def test_options_no_destination_hides_dest_fields(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="u", data={"api_key": "K"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    keys = {str(k) for k in result["data_schema"].schema}
    assert "direct_only" not in keys and "clear_destination" not in keys


async def test_options_direct_only_and_keep_destination(hass):
    data = {"api_key": "K", "stop_dest_id": DEST.id, "stop_dest_name": DEST.name}
    entry = MockConfigEntry(domain=DOMAIN, unique_id="u", data=data)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    keys = {str(k) for k in result["data_schema"].schema}
    assert {"direct_only", "clear_destination"} <= keys
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**_OPTS, "direct_only": False}
        )
    assert result["data"]["direct_only"] is False
    assert "clear_destination" not in result["data"]
    assert entry.data["stop_dest_id"] == DEST.id


async def test_options_direct_only_defaults_true(hass):
    data = {"api_key": "K", "stop_dest_id": DEST.id, "stop_dest_name": DEST.name}
    entry = MockConfigEntry(domain=DOMAIN, unique_id="u", data=data)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], dict(_OPTS)
        )
    assert result["data"]["direct_only"] is True


async def test_options_clear_destination(hass):
    data = {"api_key": "K", "stop_dest_id": DEST.id, "stop_dest_name": DEST.name}
    entry = MockConfigEntry(domain=DOMAIN, unique_id="u", data=data)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**_OPTS, "clear_destination": True}
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert "stop_dest_id" not in entry.data
    assert "stop_dest_name" not in entry.data
    assert entry.data["api_key"] == "K"
    assert "clear_destination" not in result["data"]

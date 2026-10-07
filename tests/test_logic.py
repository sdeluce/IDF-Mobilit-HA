"""Tests for the pure logic module."""

from datetime import UTC, datetime, time, timedelta

import pytest

from custom_components.idfm_departure.const import SOURCE_NAVITIA, SOURCE_SIRI
from custom_components.idfm_departure.logic import (
    _val,
    compute_leave_at,
    coord,
    departures_from_journeys,
    departures_from_visits,
    estimate_walk_s,
    filter_visits,
    format_navitia_datetime,
    in_active_window,
    line_icon,
    matches_direction,
    merge_departures,
    minutes_until,
    navitia_to_siri,
    normalize_mode,
    numeric_id,
    parse_hhmm,
    parse_journeys,
    parse_lines,
    parse_navitia_datetime,
    parse_places,
    parse_siri_datetime,
    parse_stop_monitoring,
    parse_walking_duration,
    same_line,
    siri_to_navitia,
)
from custom_components.idfm_departure.models import (
    IdfmData,
    JourneyOption,
    PlannedDeparture,
)

from .conftest import load_fixture_json  # noqa: E402

NOW = datetime(2026, 10, 7, 7, 0, tzinfo=UTC)


def utc(h: int, m: int, s: int = 0) -> datetime:
    return datetime(2026, 10, 7, h, m, s, tzinfo=UTC)


# ---------- _val ----------
def test_val_variants():
    assert _val("x") == "x"
    assert _val({"value": "x"}) == "x"
    assert _val([{"value": "a"}, {"value": "b"}]) == "a"
    assert _val([]) is None
    assert _val(None) is None
    assert _val("") is None
    assert _val({"value": None}) is None
    assert _val([{"value": None}, {"value": "b"}]) == "b"


# ---------- datetimes ----------
def test_parse_siri_datetime():
    assert parse_siri_datetime("2026-10-07T07:20:00.000Z") == utc(7, 20)
    assert parse_siri_datetime("2026-10-07T09:35:00.000+02:00") == utc(7, 35)
    assert parse_siri_datetime("2026-10-07T07:20:00").tzinfo is not None
    assert parse_siri_datetime(None) is None
    assert parse_siri_datetime("garbage") is None


def test_navitia_datetime_roundtrip_summer_and_winter():
    # CEST = UTC+2
    assert parse_navitia_datetime("20261007T092200") == utc(7, 22)
    # CET = UTC+1
    assert parse_navitia_datetime("20261215T092200") == datetime(2026, 12, 15, 8, 22, tzinfo=UTC)
    assert format_navitia_datetime(utc(7, 22)) == "20261007T092200"
    assert format_navitia_datetime(datetime(2026, 12, 15, 8, 22, tzinfo=UTC)) == "20261215T092200"


def test_coord_is_lon_lat():
    assert coord(48.85, 2.35) == "2.35;48.85"


# ---------- ids ----------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stop_area:IDFM:71517", "71517"),
        ("STIF:StopArea:SP:71517:", "71517"),
        ("stop_point:IDFM:22113", "22113"),
        ("STIF:StopPoint:Q:22113:", "22113"),
        ("line:IDFM:C01742", "C01742"),
        ("STIF:Line::C01742:", "C01742"),
        ("", None),
    ],
)
def test_numeric_id(raw, expected):
    assert numeric_id(raw) == expected


def test_id_mapping_both_ways():
    pairs = {
        "stop_point:IDFM:22113": "STIF:StopPoint:Q:22113:",
        "stop_area:IDFM:71517": "STIF:StopArea:SP:71517:",
        "line:IDFM:C01742": "STIF:Line::C01742:",
    }
    for nav, siri in pairs.items():
        assert navitia_to_siri(nav) == siri
        assert siri_to_navitia(siri) == nav
    assert siri_to_navitia("STIF:Line::C01742") == "line:IDFM:C01742"  # no trailing colon
    for bad in ("foo:bar", "stop_area:RATP:1", ""):
        with pytest.raises(ValueError):
            navitia_to_siri(bad)
    with pytest.raises(ValueError):
        siri_to_navitia("nonsense")


def test_same_line():
    assert same_line("STIF:Line::C01742:", "line:IDFM:C01742")
    assert not same_line("STIF:Line::C01742:", "line:IDFM:C01371")
    assert not same_line(None, "line:IDFM:C01742")
    assert not same_line("line:IDFM:C01742", None)


def test_normalize_mode_and_icon():
    cases = {
        "Métro": "metro", "metro": "metro", "RER": "rer", "Train RER": "rer",
        "Tramway": "tram", "Bus": "bus", "Transilien": "train", "TER": "train",
        "Funiculaire": "other", None: "other", "": "other",
    }
    for raw, mode in cases.items():
        assert normalize_mode(raw) == mode, raw
    assert line_icon("metro") == "mdi:subway-variant"
    assert line_icon("unknown-mode") == "mdi:transit-connection-variant"


# ---------- SIRI parsing ----------
def test_parse_stop_monitoring_fixture(siri_payload):
    visits = parse_stop_monitoring(siri_payload)
    # 7 raw visits; the one with no time at all is dropped
    assert len(visits) == 6
    v1, v2, v3, v4, v5, v6 = visits
    # wrapped values, Expected used
    assert (v1.line_ref, v1.line_name, v1.destination, v1.direction) == (
        "STIF:Line::C01742:", "RER A", "La Défense", "Marne-la-Vallée")
    assert v1.departure_at == utc(7, 20) and v1.realtime is True
    assert v1.stop_ref == "STIF:StopPoint:Q:22113:"
    # plain strings + timezone offset
    assert (v2.line_name, v2.destination) == ("RER A", "Marne-la-Vallée Chessy")
    assert v2.departure_at == utc(7, 35) and v2.realtime is True
    assert v3.destination == "Gare de Lyon" and v3.departure_at == utc(7, 12)
    assert v4.departure_at == utc(6, 50)  # past departure is still parsed
    # aimed only -> not realtime
    assert v5.departure_at == utc(7, 40) and v5.realtime is False
    # arrival fallback (Expected arrival => realtime)
    assert v6.departure_at == utc(7, 50) and v6.realtime is True
    assert v6.direction is None


def test_parse_stop_monitoring_empty_and_garbage(siri_empty):
    assert parse_stop_monitoring(siri_empty) == []
    assert parse_stop_monitoring({}) == []
    assert parse_stop_monitoring({"Siri": None}) == []


def test_filter_visits(siri_payload):
    visits = parse_stop_monitoring(siri_payload)
    rer = filter_visits(visits, "line:IDFM:C01742", None)
    assert [v.destination for v in rer] == [
        "La Défense", "Marne-la-Vallée Chessy", "La Défense", "Cergy"]
    bus = filter_visits(visits, "line:IDFM:C01371", None)
    assert [v.destination for v in bus] == ["Gare de Lyon", "Montparnasse"]
    # line filter miss
    assert filter_visits(visits, "line:IDFM:C00001", None) == []
    # no filter at all keeps everything
    assert filter_visits(visits, None, None) == visits
    # direction filter on accent-stripped substring
    assert [v.destination for v in filter_visits(visits, None, "la defense")] == [
        "La Défense", "La Défense"]
    # direction matches the DirectionName field too
    assert len(filter_visits(visits, "line:IDFM:C01742", "marne-la-vallee")) == 2
    # combined
    assert filter_visits(visits, "line:IDFM:C01371", "defense") == []


def test_matches_direction(siri_payload):
    v1 = parse_stop_monitoring(siri_payload)[0]
    assert matches_direction(v1, None) and matches_direction(v1, "")
    assert matches_direction(v1, "DÉFENSE")
    assert matches_direction(v1, "marne")  # via direction field
    assert not matches_direction(v1, "cergy")


# ---------- places / lines ----------
def test_parse_places(places_payload):
    p = parse_places(places_payload)
    assert [x.id for x in p] == ["stop_area:IDFM:71517", "poi:osm:1", "admin:fr:75056"]
    assert p[0].kind == "stop_area" and p[0].lat == pytest.approx(48.862725)
    assert p[0].lon == pytest.approx(2.346747)
    assert p[1].kind == "address" and p[1].lat == pytest.approx(48.8602)
    assert p[2].lat is None and p[2].lon is None


def test_parse_lines(lines_payload):
    lines = {x.id: x for x in parse_lines(lines_payload)}
    a = lines["line:IDFM:C01742"]
    assert (a.code, a.name, a.mode, a.network, a.color) == ("A", "RER A", "rer", "RATP", "#E2231A")
    assert lines["line:IDFM:C01371"].mode == "bus"
    assert lines["line:IDFM:C01379"].mode == "metro"
    assert lines["line:IDFM:C01379"].network is None and lines["line:IDFM:C01379"].color is None
    odd = lines["line:IDFM:C99999"]
    assert odd.code == "" and odd.mode == "other"


# ---------- journeys ----------
def test_parse_journeys(journeys_payload):
    opts = parse_journeys(journeys_payload)
    assert len(opts) == 2  # walking-only journey dropped
    o1, o2 = opts
    # walk = 300 (street) before first PT; waiting excluded; later transfer/street excluded
    assert o1.walk_s == 300
    assert o1.pt_departure_at == utc(7, 22)
    assert o1.stop_point_id == "stop_point:IDFM:22113"
    assert o1.stop_name == "Châtelet-Les Halles"
    assert o1.line_id == "line:IDFM:C01742"  # first "line" link, not the route link
    assert (o1.line_code, o1.mode) == ("A", "rer")
    assert o1.direction == "La Défense (Puteaux)"
    assert o1.arrival_at == utc(7, 55)
    assert (o1.color, o1.text_color) == ("#E2231A", "#FFFFFF")
    assert (o2.color, o2.text_color) == (None, None)
    # street 200 + transfer 61 = 261, waiting 30 excluded
    assert o2.walk_s == 261
    assert o2.pt_departure_at == utc(7, 30)
    assert o2.stop_point_id == "stop_point:IDFM:33333"
    assert (o2.line_code, o2.mode, o2.line_id) == ("91", "bus", "line:IDFM:C01371")


def test_parse_journeys_empty():
    assert parse_journeys({}) == []
    assert parse_journeys({"journeys": []}) == []


def test_parse_walking_duration(walking_payload, journeys_payload):
    assert parse_walking_duration(walking_payload) == 412
    # the walking-only journey is the 3rd one in the journeys fixture
    assert parse_walking_duration(journeys_payload) == 3600
    assert parse_walking_duration({"journeys": [
        {"duration": 10, "sections": [{"type": "public_transport"}]}]}) is None
    assert parse_walking_duration({}) is None


# ---------- planning ----------
def test_compute_leave_at_and_minutes_until():
    assert compute_leave_at(utc(7, 20), 400, 3) == utc(7, 20) - timedelta(seconds=580)
    assert compute_leave_at(utc(7, 20), 400, 3) == utc(7, 10, 20)
    assert compute_leave_at(utc(7, 20), 0, 0) == utc(7, 20)
    assert minutes_until(utc(7, 10, 20), NOW) == 10
    assert minutes_until(utc(7, 0, 59), NOW) == 0
    assert minutes_until(utc(6, 59, 30), NOW) == -1  # floor, not truncation
    assert minutes_until(NOW, NOW) == 0


def _lines(lines_payload):
    return {numeric_id(line.id): line for line in parse_lines(lines_payload)}


def test_departures_from_visits(siri_payload, lines_payload):
    visits = parse_stop_monitoring(siri_payload)
    deps = departures_from_visits(visits, 400, 3, NOW, 10, _lines(lines_payload))
    # v4 (06:50 - 9m40s = 06:40:20) is in the past -> skipped; sorted by leave_at
    assert [d.leave_at for d in deps] == [
        utc(7, 2, 20), utc(7, 10, 20), utc(7, 25, 20), utc(7, 30, 20), utc(7, 40, 20)]
    assert [d.stop_departure for d in deps] == [
        utc(7, 12), utc(7, 20), utc(7, 35), utc(7, 40), utc(7, 50)]
    assert [d.line for d in deps] == ["91", "A", "A", "91", "A"]
    assert [d.mode for d in deps] == ["bus", "rer", "rer", "bus", "rer"]
    assert [d.realtime for d in deps] == [True, True, True, False, True]
    assert all(d.walk_min == 7 for d in deps)  # ceil(400/60)
    assert all(d.source == SOURCE_SIRI for d in deps)
    assert deps[0].direction == "Gare de Lyon"
    # cap
    capped = departures_from_visits(visits, 400, 3, NOW, 3, _lines(lines_payload))
    assert [d.stop_departure for d in capped] == [utc(7, 12), utc(7, 20), utc(7, 35)]


def test_departures_from_visits_line_fallbacks(siri_payload):
    visits = parse_stop_monitoring(siri_payload)
    # no lines info: line_name, mode "other"
    deps = departures_from_visits(visits, 0, 0, NOW, 10, {})
    assert deps[0].line == "91" and deps[0].mode == "other"
    # leave_at exactly == now is kept
    exact = departures_from_visits(visits, 0, 0, utc(7, 12), 10, {})
    assert exact[0].leave_at == utc(7, 12)
    # unreachable: huge walk makes everything past
    assert departures_from_visits(visits, 3600, 0, NOW, 10, {}) == []


def test_departures_from_journeys(journeys_payload):
    opts = parse_journeys(journeys_payload)
    deps = departures_from_journeys(opts, None, 3, NOW, 10)
    # opt1: 07:22 - 300s - 3min = 07:14 ; opt2: 07:30 - 261s - 3min = 07:22:39
    assert [d.leave_at for d in deps] == [utc(7, 14), utc(7, 22, 39)]
    assert [d.walk_min for d in deps] == [5, 5]  # ceil(300/60), ceil(261/60)
    assert all(d.source == SOURCE_NAVITIA and d.realtime is False for d in deps)
    assert deps[0].line == "A" and deps[0].direction == "La Défense (Puteaux)"
    # override walk 600s
    deps = departures_from_journeys(opts, 600, 3, NOW, 10)
    assert [d.leave_at for d in deps] == [utc(7, 9), utc(7, 17)]
    assert [d.walk_min for d in deps] == [10, 10]
    # unreachable: override walk 20 min -> opt1 leaves 06:59 (past)
    deps = departures_from_journeys(opts, 1200, 3, NOW, 10)
    assert [d.line for d in deps] == ["91"]
    assert deps[0].leave_at == utc(7, 7)
    # cap
    assert len(departures_from_journeys(opts, None, 3, NOW, 1)) == 1


def _pd(line, dep, leave, src):
    return PlannedDeparture(line, "bus", None, dep, leave, src == SOURCE_SIRI, 5, src)


def _pdl(line, dep, src, line_id=None):
    leave = dep - timedelta(minutes=10)
    return PlannedDeparture(
        line, "bus", None, dep, leave, src == SOURCE_SIRI, 5, src, line_id)


def test_merge_delayed_train_shows_once():
    siri = _pdl("A", utc(7, 23), SOURCE_SIRI, "C01742")  # delayed +3 min
    nav = _pdl("A", utc(7, 20), SOURCE_NAVITIA, "C01742")  # scheduled
    merged = merge_departures([siri], [nav], NOW, 10)
    assert merged == [siri]


def test_merge_navitia_beyond_siri_horizon_kept():
    s1 = _pdl("A", utc(7, 20), SOURCE_SIRI, "C01742")
    s2 = _pdl("A", utc(7, 35), SOURCE_SIRI, "C01742")
    inside = _pdl("A", utc(7, 28), SOURCE_NAVITIA, "C01742")  # <= 07:36 -> dropped
    edge = _pdl("A", utc(7, 36), SOURCE_NAVITIA, "C01742")  # exactly +60s -> dropped
    later = _pdl("A", utc(7, 36, 1), SOURCE_NAVITIA, "C01742")  # kept
    other = _pdl("B", utc(7, 21), SOURCE_NAVITIA, "C01371")  # different line kept
    past = _pdl("C", utc(6, 50), SOURCE_NAVITIA, "C9")
    merged = merge_departures([s2, s1], [inside, edge, later, other, past], NOW, 10)
    assert merged == [s1, other, s2, later]
    assert merge_departures([s2, s1], [inside, edge, later, other], NOW, 2) == [s1, other]


def test_merge_line_key_falls_back_to_code():
    siri = _pdl("A", utc(7, 20), SOURCE_SIRI, None)
    nav_same = _pdl("A", utc(7, 15), SOURCE_NAVITIA, "C01742")  # one lacks id -> code
    nav_diff_id = _pdl("A", utc(7, 15), SOURCE_NAVITIA, "C01742")
    siri_id = _pdl("A", utc(7, 20), SOURCE_SIRI, "C99999")
    assert merge_departures([siri], [nav_same], NOW, 10) == [siri]
    # both have ids and they differ: different lines even with same code
    assert nav_diff_id in merge_departures([siri_id], [nav_diff_id], NOW, 10)


def test_line_id_populated():
    v = parse_stop_monitoring(
        {"Siri": {"ServiceDelivery": {"StopMonitoringDelivery": [{"MonitoredStopVisit": [{
            "MonitoredVehicleJourney": {
                "LineRef": {"value": "STIF:Line::C01742:"},
                "MonitoredCall": {"ExpectedDepartureTime": "2026-10-07T07:20:00Z"}}}]}]}}})
    assert departures_from_visits(v, 0, 0, NOW, 5, {})[0].line_id == "C01742"
    opt = JourneyOption(0, utc(7, 20), "stop_point:IDFM:1", "S", "line:IDFM:C01371",
                        "B", "bus", None, None)
    assert departures_from_journeys([opt], None, 0, NOW, 5)[0].line_id == "C01371"
    opt2 = JourneyOption(0, utc(7, 20), "stop_point:IDFM:1", "S", None, "B", "bus", None, None)
    assert departures_from_journeys([opt2], None, 0, NOW, 5)[0].line_id is None


def test_estimate_walk_s():
    # 0.009 deg of latitude ~ 1000.7 m -> *1.3/1.2 = ~1084 s
    est = estimate_walk_s(48.0, 2.0, 48.009, 2.0)
    assert 1080 <= est <= 1090
    assert estimate_walk_s(48.0, 2.0, 48.0, 2.0) == 0


def test_monomodal_ids_both_ways():
    nav = "stop_point:IDFM:monomodalStopPlace:47887"
    siri = "STIF:StopPoint:Q:monomodalStopPlace:47887:"
    assert navitia_to_siri(nav) == siri
    assert siri_to_navitia(siri) == nav
    assert numeric_id(nav) == "47887"
    assert siri_to_navitia("STIF:StopArea:SP:ab_c:12:") == "stop_area:IDFM:ab_c:12"
    assert navitia_to_siri("line:IDFM:C01742") == "STIF:Line::C01742:"
    with pytest.raises(ValueError):
        navitia_to_siri("stop_point:IDFM:")


def test_normalize_mode_no_substring_false_positives():
    assert normalize_mode("Interurbain") == "other"
    assert normalize_mode("Noctilien") == "bus"
    assert normalize_mode("Navette") == "bus"
    assert normalize_mode("Train / TER") == "train"
    assert normalize_mode("physical_mode:Tramway") == "tram"
    assert normalize_mode("Tramway") == "tram"
    assert normalize_mode("Rail") == "train"
    assert normalize_mode("Bus scolaire") == "bus"


def test_siri_odd_shapes_fixture():
    payload = load_fixture_json("siri_odd_shapes.json")
    visits = parse_stop_monitoring(payload)
    assert [(v.line_ref, v.line_name, v.departure_at, v.realtime) for v in visits] == [
        ("STIF:Line::C01742:", "A", utc(7, 20), True),
        ("STIF:Line::C01371:", None, utc(7, 30), False),
    ]
    assert visits[0].destination == "Marne-la-Vallee"
    assert visits[0].stop_ref == "STIF:StopPoint:Q:22113:"


def test_navitia_odd_shapes_skipped_not_raised():
    good_pt = {
        "type": "public_transport",
        "from": {"stop_point": {"id": "stop_point:IDFM:1", "name": "S"}},
        "departure_date_time": "20261007T092200",
        "display_informations": {"code": "A"},
    }
    iso_pt = dict(good_pt, departure_date_time="2026-10-07T09:25:00+02:00")
    bad_dt = dict(good_pt, departure_date_time="not a date")
    payload = {"journeys": [
        None,
        {"sections": [None, {"type": "street_network", "duration": "120.0"}, good_pt],
         "arrival_date_time": "garbage"},
        {"sections": [{"type": "transfer", "duration": 30.7}, iso_pt]},
        {"sections": [bad_dt]},
        {"sections": "oops"},
    ]}
    opts = parse_journeys(payload)
    assert [(o.walk_s, o.pt_departure_at) for o in opts] == [
        (120, utc(7, 22)), (30, utc(7, 25))]
    assert opts[0].arrival_at is None
    walking = {"journeys": [None, {"duration": "412.0", "sections": [
        {"type": "street_network", "duration": 412}]}]}
    assert parse_walking_duration(walking) == 412


# ---------- time window ----------
def test_parse_hhmm():
    assert parse_hhmm("05:30") == time(5, 30)
    assert parse_hhmm("01:00:15") == time(1, 0, 15)
    with pytest.raises(ValueError):
        parse_hhmm("5")


def test_in_active_window():
    start, end = time(5, 30), time(1, 0)  # crosses midnight
    assert in_active_window(time(5, 30), start, end)
    assert in_active_window(time(23, 59), start, end)
    assert in_active_window(time(0, 59), start, end)
    assert not in_active_window(time(1, 0), start, end)
    assert not in_active_window(time(3, 0), start, end)
    assert not in_active_window(time(5, 29), start, end)
    # same-day window
    assert in_active_window(time(10, 0), time(8, 0), time(18, 0))
    assert not in_active_window(time(18, 0), time(8, 0), time(18, 0))
    assert not in_active_window(time(7, 59), time(8, 0), time(18, 0))
    # start == end -> always
    assert in_active_window(time(3, 0), time(6, 0), time(6, 0))


# ---------- models ----------
def test_planned_departure_attr_and_upcoming():
    d1 = PlannedDeparture("A", "rer", "X", utc(7, 20), utc(7, 10), True, 7, SOURCE_SIRI)
    d2 = PlannedDeparture("A", "rer", None, utc(6, 20), utc(6, 10), False, 7, SOURCE_SIRI)
    assert d1.as_attr() == {
        "line": "A", "mode": "rer", "direction": "X",
        "stop_departure": "2026-10-07T07:20:00+00:00",
        "leave_at": "2026-10-07T07:10:00+00:00",
        "realtime": True, "walk_min": 7, "line_id": None,
            "line_color": None, "line_text_color": None,
    }
    data = IdfmData("stop", [d2, d1], 400, "auto", None, None, True, {"siri": 0, "navitia": 0})
    assert data.upcoming(NOW) == [d1]
    assert data.upcoming(utc(7, 10)) == [d1]  # leave_at == now kept


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("e2231a", "#E2231A"),
        ("#e2231a", "#E2231A"),
        ("  00AaBb ", "#00AABB"),
        ("E2231", None),
        ("E2231AA", None),
        ("GGGGGG", None),
        ("", None),
        (None, None),
        (123456, None),
    ],
)
def test_normalize_color(raw, expected):
    from custom_components.idfm_departure.logic import normalize_color

    assert normalize_color(raw) == expected


def test_parse_lines_text_color_and_departure_colors():
    from custom_components.idfm_departure.logic import parse_lines
    from custom_components.idfm_departure.models import StopVisit

    payload = {"lines": [{"id": "line:IDFM:C1", "code": "1", "color": "ffbe00",
                          "text_color": "000000"},
                         {"id": "line:IDFM:C2", "code": "2", "color": "zz"}]}
    infos = {i.id: i for i in parse_lines(payload)}
    assert (infos["line:IDFM:C1"].color, infos["line:IDFM:C1"].text_color) == ("#FFBE00", "#000000")
    assert (infos["line:IDFM:C2"].color, infos["line:IDFM:C2"].text_color) == (None, None)
    visit = StopVisit("STIF:Line::C1:", "1", "X", None, None, NOW + timedelta(minutes=20), True)
    dep = departures_from_visits([visit], 300, 3, NOW, 5, {"C1": infos["line:IDFM:C1"]})[0]
    assert (dep.line_color, dep.line_text_color) == ("#FFBE00", "#000000")
    assert dep.as_attr()["line_color"] == "#FFBE00"

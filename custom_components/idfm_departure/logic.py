"""Pure logic: parsing of SIRI / Navitia payloads and departure planning."""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .const import (
    MODE_ICONS,
    PARIS_TZ,
    SOURCE_NAVITIA,
    SOURCE_SIRI,
)
from .models import (
    JourneyOption,
    LineInfo,
    Place,
    PlannedDeparture,
    StopVisit,
)

_PARIS = ZoneInfo(PARIS_TZ)


def _val(x: Any) -> str | None:
    """Extract a string from str | {"value": ..} | [{"value": ..}, ...] | None."""
    if x is None:
        return None
    if isinstance(x, str):
        return x or None
    if isinstance(x, dict):
        return _val(x.get("value"))
    if isinstance(x, list):
        for item in x:
            v = _val(item)
            if v is not None:
                return v
        return None
    return str(x)


def parse_siri_datetime(s: str | None) -> datetime | None:
    """Parse an ISO datetime ('Z' accepted) to UTC-aware."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_navitia_datetime(s: str) -> datetime:
    """Parse 'YYYYMMDDTHHMMSS' (Paris local) to UTC-aware."""
    naive = datetime.strptime(s, "%Y%m%dT%H%M%S")  # noqa: DTZ007
    return naive.replace(tzinfo=_PARIS).astimezone(UTC)


def format_navitia_datetime(dt: datetime) -> str:
    """Format an aware datetime as a Paris-local naive Navitia string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(_PARIS).strftime("%Y%m%dT%H%M%S")


def coord(lat: float, lon: float) -> str:
    """Navitia coordinate string: 'lon;lat'."""
    return f"{lon};{lat}"


def numeric_id(any_id: str) -> str | None:
    """Return the trailing identifier of a Navitia or SIRI id."""
    if not any_id:
        return None
    tokens = [t for t in any_id.strip().split(":") if t]
    return tokens[-1] if tokens else None


_N2S = (
    (re.compile(r"^stop_point:IDFM:(.+)$"), "STIF:StopPoint:Q:{}:"),
    (re.compile(r"^stop_area:IDFM:(.+)$"), "STIF:StopArea:SP:{}:"),
    (re.compile(r"^line:IDFM:(.+)$"), "STIF:Line::{}:"),
)
_S2N = (
    (re.compile(r"^STIF:StopPoint:Q:(.+?):?$"), "stop_point:IDFM:{}"),
    (re.compile(r"^STIF:StopArea:SP:(.+?):?$"), "stop_area:IDFM:{}"),
    (re.compile(r"^STIF:Line::(.+?):?$"), "line:IDFM:{}"),
)


def navitia_to_siri(navitia_id: str) -> str:
    """Convert a Navitia id to its SIRI reference."""
    for rx, tpl in _N2S:
        m = rx.match(navitia_id or "")
        if m:
            return tpl.format(m.group(1))
    raise ValueError(f"Unsupported Navitia id: {navitia_id!r}")


def siri_to_navitia(siri_ref: str) -> str:
    """Convert a SIRI reference to its Navitia id."""
    for rx, tpl in _S2N:
        m = rx.match(siri_ref or "")
        if m:
            return tpl.format(m.group(1))
    raise ValueError(f"Unsupported SIRI ref: {siri_ref!r}")


def same_line(a: str | None, b: str | None) -> bool:
    """True when both ids share the same numeric id."""
    if a is None or b is None:
        return False
    na, nb = numeric_id(a), numeric_id(b)
    return na is not None and na == nb


_MODE_WORDS = (
    ("metro", {"metro", "métro", "metros", "métros"}),
    ("rer", {"rer"}),
    ("tram", {"tram", "tramway", "tramways", "trams"}),
    ("bus", {"bus", "noctilien", "navette", "navettes", "autocar"}),
    (
        "train",
        {"train", "trains", "transilien", "ter", "rail", "localtrain", "rapidtransit"},
    ),
)


def normalize_mode(raw: str | None) -> str:
    """Normalize a Navitia mode label (whole-word match, no substrings)."""
    words = set(re.findall(r"[^\W_]+", (raw or "").casefold()))
    for mode, vocab in _MODE_WORDS:
        if words & vocab:
            return mode
    return "other"


def _mode_of(*raws: Any) -> str:
    for raw in raws:
        mode = normalize_mode(raw if isinstance(raw, str) else None)
        if mode != "other":
            return mode
    return "other"


def line_icon(mode: str) -> str:
    """Icon for a normalized mode."""
    return MODE_ICONS.get(mode, MODE_ICONS["other"])


def _as_list(x: Any) -> list:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _first_dict(x: Any) -> dict:
    for item in _as_list(x):
        if isinstance(item, dict):
            return item
    return {}


def parse_stop_monitoring(payload: dict) -> list[StopVisit]:
    """Parse a SIRI stop-monitoring response (tolerant of odd shapes)."""
    visits: list[StopVisit] = []
    try:
        deliveries = payload["Siri"]["ServiceDelivery"]["StopMonitoringDelivery"]
    except (KeyError, TypeError):
        return visits
    for delivery in _as_list(deliveries):
        if not isinstance(delivery, dict):
            continue
        for msv in _as_list(delivery.get("MonitoredStopVisit")):
            if not isinstance(msv, dict):
                continue
            mvj = _first_dict(msv.get("MonitoredVehicleJourney"))
            inner = _first_dict(mvj.get("MonitoredVehicleJourney"))
            if inner:  # wrapped MonitoredVehicleJourney
                mvj = inner
            call = _first_dict(mvj.get("MonitoredCall"))
            chosen: datetime | None = None
            realtime = False
            for key, is_rt in (
                ("ExpectedDepartureTime", True),
                ("AimedDepartureTime", False),
                ("ExpectedArrivalTime", True),
                ("AimedArrivalTime", False),
            ):
                dt = parse_siri_datetime(_val(call.get(key)))
                if dt is not None:
                    chosen, realtime = dt, is_rt
                    break
            if chosen is None:
                continue
            stop_ref = (
                _val(msv.get("MonitoringRef"))
                or _val(call.get("StopPointRef"))
                or _val(mvj.get("MonitoringRef"))
            )
            visits.append(
                StopVisit(
                    line_ref=_val(mvj.get("LineRef")) or "",
                    line_name=_val(mvj.get("PublishedLineName")),
                    destination=_val(mvj.get("DestinationName")),
                    direction=_val(mvj.get("DirectionName")),
                    stop_ref=stop_ref,
                    departure_at=chosen,
                    realtime=realtime,
                )
            )
    return visits


def _coord_of(obj: dict) -> tuple[float | None, float | None]:
    for key in ("stop_area", "stop_point", "address", "poi", "administrative_region"):
        c = (obj.get(key) or {}).get("coord")
        if c:
            try:
                return float(c["lat"]), float(c["lon"])
            except (KeyError, TypeError, ValueError):
                return None, None
    return None, None


def parse_places(payload: dict) -> list[Place]:
    """Parse a Navitia /places response."""
    places: list[Place] = []
    for p in payload.get("places") or []:
        pid = p.get("id")
        if not pid:
            continue
        lat, lon = _coord_of(p)
        places.append(
            Place(
                id=pid,
                name=p.get("name") or pid,
                kind=p.get("embedded_type") or "",
                lat=lat,
                lon=lon,
            )
        )
    return places


def normalize_color(value: Any) -> str | None:
    """Return '#RRGGBB' (uppercase) from a Navitia hex color, or None if invalid."""
    if not isinstance(value, str):
        return None
    v = value.strip().lstrip("#")
    if len(v) != 6 or any(c not in "0123456789abcdefABCDEF" for c in v):
        return None
    return f"#{v.upper()}"


def parse_lines(payload: dict) -> list[LineInfo]:
    """Parse a Navitia lines response."""
    lines: list[LineInfo] = []
    for ln in payload.get("lines") or []:
        lid = ln.get("id")
        if not lid:
            continue
        cm = (ln.get("commercial_mode") or {}).get("name")
        pm = [(m or {}).get("name") for m in ln.get("physical_modes") or []]
        lines.append(
            LineInfo(
                id=lid,
                code=ln.get("code") or "",
                name=ln.get("name") or "",
                mode=_mode_of(cm, *pm),
                network=(ln.get("network") or {}).get("name"),
                color=normalize_color(ln.get("color")),
                text_color=normalize_color(ln.get("text_color")),
            )
        )
    return lines


def _int(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError, OverflowError):
        return default


def _navitia_dt(s: Any) -> datetime | None:
    """Navitia 'YYYYMMDDTHHMMSS' with ISO fallback; None when unparseable."""
    if not isinstance(s, str) or not s:
        return None
    try:
        return parse_navitia_datetime(s)
    except ValueError:
        return parse_siri_datetime(s)


def _journey_option(j: dict) -> JourneyOption | None:
    walk_s = 0
    pt: dict | None = None
    for sec in j.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        stype = sec.get("type")
        if stype == "public_transport":
            pt = sec
            break
        if stype in ("street_network", "transfer"):
            walk_s += _int(sec.get("duration"))
    if pt is None:
        return None
    frm = pt.get("from") or {}
    sp = frm.get("stop_point") or {}
    sp_id = sp.get("id") or (
        frm.get("id") if frm.get("embedded_type") == "stop_point" else None
    )
    dep = _navitia_dt(pt.get("departure_date_time"))
    if not sp_id or dep is None:
        return None
    di = pt.get("display_informations") or {}
    line_id = next(
        (
            link.get("id")
            for link in pt.get("links") or []
            if isinstance(link, dict) and link.get("type") == "line"
        ),
        None,
    )
    return JourneyOption(
        walk_s=walk_s,
        pt_departure_at=dep,
        stop_point_id=sp_id,
        stop_name=sp.get("name") or frm.get("name") or "",
        line_id=line_id,
        line_code=di.get("code") or "",
        mode=_mode_of(di.get("commercial_mode"), di.get("physical_mode")),
        direction=di.get("direction"),
        arrival_at=_navitia_dt(j.get("arrival_date_time")),
        color=normalize_color(di.get("color")),
        text_color=normalize_color(di.get("text_color")),
    )


def parse_journeys(payload: dict) -> list[JourneyOption]:
    """Parse a Navitia /journeys response; bad / PT-less journeys are skipped."""
    options: list[JourneyOption] = []
    for j in payload.get("journeys") or []:
        if not isinstance(j, dict):
            continue
        try:
            opt = _journey_option(j)
        except (AttributeError, TypeError, ValueError):
            continue
        if opt is not None:
            options.append(opt)
    return options


def parse_walking_duration(payload: dict) -> int | None:
    """Duration of the first journey made only of non-PT sections."""
    for j in payload.get("journeys") or []:
        if not isinstance(j, dict):
            continue
        sections = [s for s in j.get("sections") or [] if isinstance(s, dict)]
        if sections and all(s.get("type") != "public_transport" for s in sections):
            dur = j.get("duration")
            if dur is None:
                return sum(_int(s.get("duration")) for s in sections)
            return _int(dur)
    return None


def _fold(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def matches_direction(visit: StopVisit, needle: str | None) -> bool:
    """Accent/case-insensitive substring match on destination or direction."""
    if not needle:
        return True
    n = _fold(needle)
    return any(n in _fold(f) for f in (visit.destination, visit.direction) if f)


def filter_visits(
    visits: list[StopVisit], line_id: str | None, direction_filter: str | None
) -> list[StopVisit]:
    """Keep visits on the requested line and direction."""
    return [
        v
        for v in visits
        if (not line_id or same_line(v.line_ref, line_id))
        and matches_direction(v, direction_filter)
    ]


def compute_leave_at(
    stop_departure: datetime, walk_s: int, margin_min: int
) -> datetime:
    """leave_at = stop_departure - walk - margin."""
    return stop_departure - timedelta(seconds=walk_s) - timedelta(minutes=margin_min)


def minutes_until(leave_at: datetime, now: datetime) -> int:
    """Whole minutes (floored) until leave_at; negative when past."""
    return math.floor((leave_at - now).total_seconds() / 60)


def departures_from_visits(
    visits: list[StopVisit],
    walk_s: int,
    margin_min: int,
    now: datetime,
    count: int,
    lines: dict[str, LineInfo],
) -> list[PlannedDeparture]:
    """Plan departures from SIRI visits."""
    out: list[PlannedDeparture] = []
    for v in visits:
        leave_at = compute_leave_at(v.departure_at, walk_s, margin_min)
        if leave_at < now:
            continue
        nid = numeric_id(v.line_ref)
        info = lines.get(nid) if nid else None
        out.append(
            PlannedDeparture(
                line=(info.code if info else "") or v.line_name or nid or "",
                mode=info.mode if info else "other",
                direction=v.destination or v.direction,
                stop_departure=v.departure_at,
                leave_at=leave_at,
                realtime=v.realtime,
                walk_min=math.ceil(walk_s / 60),
                source=SOURCE_SIRI,
                line_id=nid,
                line_color=info.color if info else None,
                line_text_color=info.text_color if info else None,
            )
        )
    out.sort(key=lambda d: d.leave_at)
    return out[:count]


def departures_from_journeys(
    options: list[JourneyOption],
    walk_override_s: int | None,
    margin_min: int,
    now: datetime,
    count: int,
) -> list[PlannedDeparture]:
    """Plan departures from Navitia journeys."""
    out: list[PlannedDeparture] = []
    for o in options:
        walk_s = walk_override_s if walk_override_s is not None else o.walk_s
        leave_at = compute_leave_at(o.pt_departure_at, walk_s, margin_min)
        if leave_at < now:
            continue
        out.append(
            PlannedDeparture(
                line=o.line_code,
                mode=o.mode,
                direction=o.direction,
                stop_departure=o.pt_departure_at,
                leave_at=leave_at,
                realtime=False,
                walk_min=math.ceil(walk_s / 60),
                source=SOURCE_NAVITIA,
                line_id=numeric_id(o.line_id) if o.line_id else None,
                line_color=o.color,
                line_text_color=o.text_color,
            )
        )
    out.sort(key=lambda d: d.leave_at)
    return out[:count]


def _same_line_key(p: PlannedDeparture, s: PlannedDeparture) -> bool:
    if p.line_id and s.line_id:
        return p.line_id == s.line_id
    return p.line == s.line


def merge_departures(
    primary: list[PlannedDeparture],
    secondary: list[PlannedDeparture],
    now: datetime,
    count: int,
) -> list[PlannedDeparture]:
    """Merge SIRI (primary) with Navitia (secondary).

    For each line present in primary, secondary entries up to the last primary
    stop_departure of that line + 60s are dropped (SIRI is authoritative there).
    """
    kept = list(primary)
    for s in secondary:
        matching = [p for p in primary if _same_line_key(p, s)]
        if matching:
            horizon = max(p.stop_departure for p in matching) + timedelta(seconds=60)
            if s.stop_departure <= horizon:
                continue
        kept.append(s)
    kept = [d for d in kept if d.leave_at >= now]
    kept.sort(key=lambda d: d.leave_at)
    return kept[:count]


def estimate_walk_s(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Walking estimate in seconds: haversine * 1.3 detour at 1.2 m/s, ceiled."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    meters = 2 * r * math.asin(min(1.0, math.sqrt(h)))
    return math.ceil(meters * 1.3 / 1.2)


def parse_hhmm(s: str) -> time:
    """Parse 'HH:MM' or 'HH:MM:SS'."""
    parts = s.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid time: {s!r}")
    h, m = int(parts[0]), int(parts[1])
    sec = int(parts[2]) if len(parts) == 3 else 0
    return time(h, m, sec)


def in_active_window(now_local: time, start: time, end: time) -> bool:
    """Active window check; start > end crosses midnight; start == end is always."""
    if start == end:
        return True
    if start < end:
        return start <= now_local < end
    return now_local >= start or now_local < end

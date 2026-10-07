"""Live check against the real PRIM API (needs PRIM_API_KEY).

Run with the venv python (the package __init__ imports Home Assistant):

    PRIM_API_KEY=... .venv/bin/python scripts/live_check.py \
        --stop stop_area:IDFM:71517 --home 48.8584,2.3470 --dest-query "La Défense"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.idfm_departure.api import PrimClient, PrimError  # noqa: E402
from custom_components.idfm_departure.const import (  # noqa: E402
    DEFAULT_MARGIN_MIN,
    NAVITIA_BASE_URL,
)
from custom_components.idfm_departure.logic import (  # noqa: E402
    coord,
    departures_from_journeys,
    departures_from_visits,
    filter_visits,
    merge_departures,
    navitia_to_siri,
    numeric_id,
)


class _LoggingSession:
    """Proxy printing the raw HTTP status of each call."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    @asynccontextmanager
    async def get(self, url, **kwargs):
        async with self._session.get(url, **kwargs) as resp:
            print(f"  HTTP {resp.status} GET {resp.url.with_query(None)}")
            yield resp


def _show(title: str, items) -> None:
    print(f"\n== {title} ({len(items)})")
    for item in items:
        print("  ", item)


async def run(args: argparse.Namespace) -> None:
    key = os.environ.get("PRIM_API_KEY")
    if not key:
        raise SystemExit("PRIM_API_KEY is not set")
    lat, lon = (float(x) for x in args.home.split(","))
    now = datetime.now(UTC)
    home = coord(lat, lon)

    async with aiohttp.ClientSession() as raw:
        client = PrimClient(_LoggingSession(raw), key)  # type: ignore[arg-type]

        print("== validate_key")
        await client.validate_key()
        prefix = client._prefix
        print(f"  Navitia path prefix chosen: {prefix!r} -> {NAVITIA_BASE_URL}{prefix}")

        print("\n== stop mode")
        lines = await client.get_stop_area_lines(args.stop)
        _show("lines", lines)
        walk_s = await client.get_walking_time(home, args.stop, now)
        print(f"\nwalking seconds: {walk_s}")
        visits = await client.get_stop_monitoring(navitia_to_siri(args.stop))
        visits = filter_visits(visits, None, None)
        _show("StopVisits", visits)
        by_line = {numeric_id(x.id): x for x in lines}
        deps = departures_from_visits(
            visits, walk_s or 0, DEFAULT_MARGIN_MIN, now, 5, by_line
        )
        _show("PlannedDepartures (stop)", deps)

        print("\n== journey mode")
        places = await client.search_places(args.dest_query)
        _show("places", places)
        if not places:
            print("no destination found")
            return
        dest = places[0]
        options = await client.get_journeys(home, dest.id, now)
        _show(f"JourneyOptions to {dest.name}", options)
        jdeps = departures_from_journeys(options, None, DEFAULT_MARGIN_MIN, now, 5)
        if options:
            p = options[0]
            sv = await client.get_stop_monitoring(
                navitia_to_siri(p.stop_point_id),
                navitia_to_siri(p.line_id) if p.line_id else None,
            )
            sv = filter_visits(sv, p.line_id, None)
            _show("StopVisits at first PT stop", sv)
            sdeps = departures_from_visits(
                sv, p.walk_s, DEFAULT_MARGIN_MIN, now, 5, {}
            )
            jdeps = merge_departures(sdeps, jdeps, now, 5)
        _show("PlannedDepartures (journey)", jdeps)
        print(f"\nusage: {client.usage}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", required=True, help="Navitia stop_area id")
    ap.add_argument("--home", required=True, help="lat,lon")
    ap.add_argument("--dest-query", required=True)
    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except PrimError as err:
        print(f"PRIM ERROR: {type(err).__name__}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Async client for the IDFM PRIM marketplace (SIRI + Navitia)."""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .const import (
    HTTP_TIMEOUT_S,
    NAVITIA_BASE_URL,
    NAVITIA_PATH_PREFIXES,
    PARIS_TZ,
    RATE_LIMIT_MIN_INTERVAL_S,
    SIRI_STOP_MONITORING_URL,
)
from .logic import (
    format_navitia_datetime,
    parse_journeys,
    parse_lines,
    parse_places,
    parse_stop_monitoring,
    parse_walking_duration,
)
from .models import JourneyOption, LineInfo, Place, StopVisit

Params = list[tuple[str, str]]


class PrimError(Exception):
    """Base PRIM error."""


class PrimAuthError(PrimError):
    """401 / 403."""


class PrimRateLimitError(PrimError):
    """429."""


class PrimServerError(PrimError):
    """5xx."""


class PrimNotFoundError(PrimError):
    """404."""


class PrimConnectionError(PrimError):
    """Timeout, aiohttp.ClientError, invalid JSON."""


class _BadRequestError(PrimError):
    """400 (internal; lets SIRI retry without LineRef)."""


class _NavitiaNoResultError(PrimNotFoundError):
    """404 carrying a Navitia error body (no_solution, date_out_of_bounds...)."""


# Shared per API key (sha256 hex digest; the raw key is never a dict key).
_USAGE: dict[str, dict[str, int]] = {}
_USAGE_DAY: dict[str, Any] = {}
_PREFIX: dict[str, str] = {}
_NO_LINEREF: set[str] = set()


def _key_hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


async def _has_navitia_error(resp: Any) -> bool:
    """True when a 404 body is a Navitia {"error": {"id": ...}} document."""
    try:
        body = await resp.json(content_type=None)
    except (ValueError, aiohttp.ClientError):
        return False
    err = body.get("error") if isinstance(body, dict) else None
    return isinstance(err, dict) and bool(err.get("id"))


def _paris_today() -> Any:
    return datetime.now(UTC).astimezone(ZoneInfo(PARIS_TZ)).date()


class PrimClient:
    """Rate-limited PRIM client."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key
        self._khash = _key_hash(api_key)
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        _USAGE.setdefault(self._khash, {"siri": 0, "navitia": 0})
        _USAGE_DAY.setdefault(self._khash, _paris_today())

    @property
    def usage(self) -> dict[str, int]:
        """Shared per-key usage counters for the current Paris day."""
        return _USAGE[self._khash]

    @property
    def _prefix(self) -> str | None:
        return _PREFIX.get(self._khash)

    @_prefix.setter
    def _prefix(self, value: str | None) -> None:
        if value is None:
            _PREFIX.pop(self._khash, None)
        else:
            _PREFIX[self._khash] = value

    def _count(self, kind: str) -> None:
        today = _paris_today()
        usage = _USAGE[self._khash]
        if today != _USAGE_DAY.get(self._khash):
            _USAGE_DAY[self._khash] = today
            usage["siri"] = 0
            usage["navitia"] = 0
        usage[kind] += 1

    async def _get(self, kind: str, url: str, params: Params) -> Any:
        """One serialized, rate-limited GET returning decoded JSON."""
        headers = {"apikey": self._api_key, "Accept": "application/json"}
        async with self._lock:
            wait = RATE_LIMIT_MIN_INTERVAL_S - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._count(kind)
            try:
                async with self._session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
                ) as resp:
                    status = resp.status
                    if status in (401, 403):
                        raise PrimAuthError(f"HTTP {status}")
                    if status == 429:
                        raise PrimRateLimitError("HTTP 429")
                    if status == 404:
                        if kind == "navitia" and await _has_navitia_error(resp):
                            raise _NavitiaNoResultError(f"HTTP 404 for {url}")
                        raise PrimNotFoundError(f"HTTP 404 for {url}")
                    if status == 400:
                        raise _BadRequestError(f"HTTP 400 for {url}")
                    if status >= 500:
                        raise PrimServerError(f"HTTP {status}")
                    if status >= 400:
                        raise PrimError(f"HTTP {status}")
                    try:
                        return await resp.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError) as err:
                        raise PrimConnectionError(f"Invalid JSON: {err}") from err
            except TimeoutError as err:
                raise PrimConnectionError("Timeout") from err
            except aiohttp.ClientError as err:
                raise PrimConnectionError(str(err)) from err
            finally:
                self._last_request = time.monotonic()

    async def _navitia(self, path: str, params: Params) -> Any:
        """Navitia GET, probing path prefixes until a non-404."""
        prefixes = (
            (self._prefix,) if self._prefix is not None else NAVITIA_PATH_PREFIXES
        )
        last: PrimNotFoundError | None = None
        for prefix in prefixes:
            try:
                data = await self._get(
                    "navitia", f"{NAVITIA_BASE_URL}{prefix}{path}", params
                )
            except _NavitiaNoResultError:
                # Prefix is right; the API just has no result for this query.
                self._prefix = prefix
                raise
            except PrimNotFoundError as err:
                last = err
                continue
            except _BadRequestError as err:
                self._prefix = prefix
                raise PrimError(str(err)) from err
            self._prefix = prefix
            return data
        raise last or PrimNotFoundError(path)

    async def validate_key(self) -> None:
        """Raise PrimAuthError if the key is rejected."""
        await self._navitia("/places", [("q", "Chatelet"), ("count", "1")])

    async def get_stop_monitoring(
        self, monitoring_ref: str, line_ref: str | None = None
    ) -> list[StopVisit]:
        """SIRI stop monitoring; empty/missing deliveries give []."""
        params: Params = [("MonitoringRef", monitoring_ref)]
        if line_ref and self._khash not in _NO_LINEREF:
            params.append(("LineRef", line_ref))
        else:
            line_ref = None
        try:
            data = await self._get("siri", SIRI_STOP_MONITORING_URL, params)
        except _BadRequestError as err:
            if not line_ref:
                raise PrimError(str(err)) from err
            try:
                data = await self._get(
                    "siri", SIRI_STOP_MONITORING_URL, params[:1]
                )
            except _BadRequestError as err2:
                raise PrimError(str(err2)) from err2
            _NO_LINEREF.add(self._khash)
        return parse_stop_monitoring(data) if isinstance(data, dict) else []

    async def search_places(
        self, query: str, types: tuple[str, ...] = ("stop_area", "address")
    ) -> list[Place]:
        """Navitia /places search."""
        params: Params = [("q", query), ("count", "10")]
        params += [("type[]", t) for t in types]
        data = await self._navitia("/places", params)
        return parse_places(data) if isinstance(data, dict) else []

    async def get_stop_area_lines(self, stop_area_id: str) -> list[LineInfo]:
        """Lines serving a stop area."""
        data = await self._navitia(
            f"/stop_areas/{stop_area_id}/lines", [("count", "100")]
        )
        return parse_lines(data) if isinstance(data, dict) else []

    async def get_journeys(
        self, from_: str, to: str, when: datetime, count: int = 3
    ) -> list[JourneyOption]:
        """Navitia journeys; no solution gives []."""
        params: Params = [
            ("from", from_),
            ("to", to),
            ("datetime", format_navitia_datetime(when)),
            ("data_freshness", "realtime"),
            ("count", str(count)),
        ]
        try:
            data = await self._navitia("/journeys", params)
        except PrimNotFoundError:
            return []
        return parse_journeys(data) if isinstance(data, dict) else []

    async def get_walking_time(
        self, from_: str, to: str, when: datetime
    ) -> int | None:
        """Walking duration in seconds (UNVERIFIED direct_path params)."""
        params: Params = [
            ("from", from_),
            ("to", to),
            ("datetime", format_navitia_datetime(when)),
            ("direct_path", "only"),
            ("direct_path_mode[]", "walking"),
        ]
        try:
            data = await self._navitia("/journeys", params)
        except PrimNotFoundError:
            return None
        return parse_walking_duration(data) if isinstance(data, dict) else None

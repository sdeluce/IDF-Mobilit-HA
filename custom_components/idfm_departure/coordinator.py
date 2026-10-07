"""Data coordinator for IDFM Prochain Départ."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import logic
from .api import (
    PrimAuthError,
    PrimClient,
    PrimConnectionError,
    PrimError,
    PrimRateLimitError,
    PrimServerError,
)
from .const import (
    CONF_ACTIVE_END,
    CONF_ACTIVE_START,
    CONF_DEPARTURES_COUNT,
    CONF_DESTINATION_ID,
    CONF_DIRECTION_FILTER,
    CONF_HOME_LAT,
    CONF_HOME_LON,
    CONF_JOURNEY_REFRESH_MIN,
    CONF_LINE_ID,
    CONF_MARGIN_MIN,
    CONF_MODE,
    CONF_SCAN_INTERVAL_S,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_WALK_OVERRIDE_MIN,
    DEFAULT_ACTIVE_END,
    DEFAULT_ACTIVE_START,
    DEFAULT_DEPARTURES_COUNT,
    DEFAULT_JOURNEY_REFRESH_MIN,
    DEFAULT_MARGIN_MIN,
    DEFAULT_SCAN_INTERVAL_S,
    DOMAIN,
    LOCAL_TICK_S,
    MODE_JOURNEY,
    MODE_STOP,
    PARIS_TZ,
    WALK_REFRESH_S,
    WALK_SOURCE_AUTO,
    WALK_SOURCE_MANUAL,
)
from .logic import (
    coord,
    departures_from_journeys,
    departures_from_visits,
    filter_visits,
    in_active_window,
    merge_departures,
    navitia_to_siri,
    numeric_id,
    parse_hhmm,
)
from .models import IdfmData, JourneyOption, LineInfo

_LOGGER = logging.getLogger(__name__)

# Stop coordinates stored in entry data by the config flow (not in const.py).
CONF_STOP_LAT = "stop_lat"
CONF_STOP_LON = "stop_lon"
WALK_SOURCE_ESTIMATED = "estimated"
WALK_RETRY_S = 3600  # back-off between failed walk API calls
LINES_RETRY_S = 900  # retry delay after a failed stop-lines call

# Per-task force flag: only the task that called async_force_refresh sees it,
# so concurrently scheduled updates can never consume it.
_FORCE: ContextVar[bool] = ContextVar("idfm_force_refresh", default=False)


class IdfmCoordinator(DataUpdateCoordinator[IdfmData]):
    """Fetch departures and compute leave times."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: PrimClient) -> None:
        opts = entry.options
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=opts.get(CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S)
            ),
        )
        self.client = client
        self._walk_s: int | None = None
        self._walk_source: str = WALK_SOURCE_AUTO
        self._walk_retry_at: datetime | None = None
        self._walk_at: datetime | None = None
        self._lines: dict[str, LineInfo] = {}
        self._lines_at: datetime | None = None
        self._journeys: list[JourneyOption] | None = None
        self._journeys_at: datetime | None = None
        self._unsub_tick: CALLBACK_TYPE | None = async_track_time_interval(
            hass, self._async_tick, timedelta(seconds=LOCAL_TICK_S)
        )

    async def _async_tick(self, _now: datetime) -> None:
        self.async_update_listeners()

    async def async_shutdown(self) -> None:
        """Cancel the local tick."""
        if self._unsub_tick is not None:
            self._unsub_tick()
            self._unsub_tick = None
        await super().async_shutdown()

    async def async_force_refresh(self) -> None:
        """Refresh now, ignoring the active window."""
        token = _FORCE.set(True)
        try:
            await self.async_refresh()
        finally:
            _FORCE.reset(token)

    # ------------------------------------------------------------------
    def _opt(self, key: str, default):
        value = self.config_entry.options.get(key)
        return default if value is None else value

    def _is_active(self, now: datetime) -> bool:
        local = now.astimezone(ZoneInfo(PARIS_TZ)).time()
        start = parse_hhmm(self._opt(CONF_ACTIVE_START, DEFAULT_ACTIVE_START))
        end = parse_hhmm(self._opt(CONF_ACTIVE_END, DEFAULT_ACTIVE_END))
        return in_active_window(local, start, end)

    def _fresh(self, at: datetime | None, now: datetime, ttl_s: float) -> bool:
        return at is not None and (now - at).total_seconds() < ttl_s

    def _stop_name(self, cfg, mode: str) -> str | None:
        if mode == MODE_JOURNEY:
            return (self._journeys[0].stop_name or None) if self._journeys else None
        return cfg.get(CONF_STOP_NAME) or self.config_entry.title or None

    def _empty(self, mode: str, active: bool) -> IdfmData:
        override = self.config_entry.options.get(CONF_WALK_OVERRIDE_MIN)
        return IdfmData(
            mode=mode,
            departures=[],
            walk_s=None,
            walk_source=WALK_SOURCE_MANUAL if override else WALK_SOURCE_AUTO,
            stop_name=self._stop_name(self.config_entry.data, mode),
            last_api_update=None,
            active=active,
            api_usage=dict(self.client.usage),
        )

    async def _async_update_data(self) -> IdfmData:
        data = self.config_entry.data
        mode = data.get(CONF_MODE, MODE_STOP)
        now = dt_util.utcnow()
        forced = _FORCE.get()

        if not forced and not self._is_active(now):
            if self.data is None:
                return self._empty(mode, False)
            self.data.active = False
            return self.data

        try:
            result = await self._fetch(mode, now)
        except PrimAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PrimRateLimitError as err:
            raise UpdateFailed("PRIM quota exceeded (429)") from err
        except (PrimServerError, PrimConnectionError) as err:
            raise UpdateFailed(str(err) or type(err).__name__) from err
        except PrimError as err:
            raise UpdateFailed(str(err) or type(err).__name__) from err
        result.active = True
        result.api_usage = dict(self.client.usage)
        result.last_api_update = now
        return result

    async def _get_walk(self, now: datetime, home: str, mode: str) -> tuple[int | None, str]:
        override = self.config_entry.options.get(CONF_WALK_OVERRIDE_MIN)
        if override:
            return int(override) * 60, WALK_SOURCE_MANUAL
        if mode == MODE_JOURNEY:
            return None, WALK_SOURCE_AUTO
        cfg = self.config_entry.data
        have_fresh = (
            self._walk_s is not None
            and self._walk_source == WALK_SOURCE_AUTO
            and self._fresh(self._walk_at, now, WALK_REFRESH_S)
        )
        if not have_fresh and (self._walk_retry_at is None or now >= self._walk_retry_at):
            walk: int | None = None
            try:
                walk = await self.client.get_walking_time(home, cfg[CONF_STOP_ID], now)
            except PrimAuthError:
                raise
            except PrimError as err:
                _LOGGER.warning("Walking time request failed: %s", err)
            if walk is not None:
                self._walk_s, self._walk_at = walk, now
                self._walk_source = WALK_SOURCE_AUTO
                self._walk_retry_at = None
            else:
                self._walk_retry_at = now + timedelta(seconds=WALK_RETRY_S)
                lat, lon = cfg.get(CONF_STOP_LAT), cfg.get(CONF_STOP_LON)
                if self._walk_s is None and lat is not None and lon is not None:
                    self._walk_s = logic.estimate_walk_s(
                        cfg[CONF_HOME_LAT], cfg[CONF_HOME_LON], lat, lon
                    )
                    self._walk_source = WALK_SOURCE_ESTIMATED
        if self._walk_s is None:
            raise UpdateFailed(
                "Walking time unavailable (API failed, stop coordinates unknown); "
                "set the walk_override_min option"
            )
        return self._walk_s, self._walk_source

    async def _fetch(self, mode: str, now: datetime) -> IdfmData:
        cfg = self.config_entry.data
        home = coord(cfg[CONF_HOME_LAT], cfg[CONF_HOME_LON])
        margin = self._opt(CONF_MARGIN_MIN, DEFAULT_MARGIN_MIN)
        count = self._opt(CONF_DEPARTURES_COUNT, DEFAULT_DEPARTURES_COUNT)
        walk_s, source = await self._get_walk(now, home, mode)
        if mode == MODE_JOURNEY:
            departures, walk_s = await self._fetch_journey(
                cfg, home, now, walk_s, margin, count
            )
        else:
            departures = await self._fetch_stop(cfg, now, walk_s, margin, count)
        return IdfmData(
            mode=mode,
            departures=departures,
            walk_s=walk_s,
            walk_source=source,
            stop_name=self._stop_name(cfg, mode),
            last_api_update=now,
            active=True,
            api_usage=dict(self.client.usage),
        )

    async def _fetch_stop(self, cfg, now, walk_s, margin, count):
        stop_id = cfg[CONF_STOP_ID]
        line_id = cfg.get(CONF_LINE_ID)
        if not self._fresh(self._lines_at, now, WALK_REFRESH_S):
            try:
                infos = await self.client.get_stop_area_lines(stop_id)
                self._lines = {numeric_id(i.id) or i.id: i for i in infos}
            except PrimAuthError:
                raise
            except PrimError as err:
                _LOGGER.warning("Could not fetch stop lines: %s", err)
                self._lines = {}
                # retry in LINES_RETRY_S instead of caching {} for a day
                self._lines_at = now - timedelta(seconds=WALK_REFRESH_S - LINES_RETRY_S)
            else:
                self._lines_at = now
        visits = await self.client.get_stop_monitoring(
            navitia_to_siri(stop_id), navitia_to_siri(line_id) if line_id else None
        )
        visits = filter_visits(visits, line_id, cfg.get(CONF_DIRECTION_FILTER))
        return departures_from_visits(visits, walk_s, margin, now, count, self._lines)

    async def _fetch_journey(self, cfg, home, now, override_s, margin, count):
        ttl = self._opt(CONF_JOURNEY_REFRESH_MIN, DEFAULT_JOURNEY_REFRESH_MIN) * 60
        if self._journeys is None or not self._fresh(self._journeys_at, now, ttl):
            try:
                # first journey must still be reachable after the walking margin
                self._journeys = await self.client.get_journeys(
                    home, cfg[CONF_DESTINATION_ID], now + timedelta(minutes=margin)
                )
                self._journeys_at = now
            except PrimAuthError:
                raise
            except PrimError as err:
                if self._journeys is None:
                    raise
                _LOGGER.warning("Journeys refresh failed, keeping cached journeys: %s", err)
        options = self._journeys
        if not options:
            return [], override_s
        primary = options[0]
        walk_s = override_s if override_s is not None else primary.walk_s
        nav = departures_from_journeys(options, override_s, margin, now, count)
        siri: list = []
        try:
            visits = await self.client.get_stop_monitoring(
                navitia_to_siri(primary.stop_point_id),
                navitia_to_siri(primary.line_id) if primary.line_id else None,
            )
            visits = filter_visits(visits, primary.line_id, None)
            lines = {}
            if primary.line_id:
                key = numeric_id(primary.line_id) or primary.line_id
                lines[key] = LineInfo(
                    id=primary.line_id, code=primary.line_code, name=primary.line_code,
                    mode=primary.mode, network=None, color=primary.color,
                    text_color=primary.text_color,
                )
            siri = departures_from_visits(visits, walk_s, margin, now, count, lines)
            siri = [replace(d, mode=primary.mode) for d in siri]
        except PrimAuthError:
            raise
        except (PrimError, ValueError) as err:
            _LOGGER.warning("SIRI refinement failed, using Navitia only: %s", err)
        return merge_departures(siri, nav, now, count), walk_s

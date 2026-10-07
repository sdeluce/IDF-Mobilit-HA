"""Config flow for IDFM Prochain Départ."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import time
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)

from .api import PrimAuthError, PrimClient, PrimError
from .const import (
    CONF_ACTIVE_END,
    CONF_ACTIVE_START,
    CONF_API_KEY,
    CONF_DEPARTURES_COUNT,
    CONF_DESTINATION_ID,
    CONF_DESTINATION_NAME,
    CONF_DIRECT_ONLY,
    CONF_DIRECTION_FILTER,
    CONF_HOME_ENTITY,
    CONF_HOME_LAT,
    CONF_HOME_LON,
    CONF_JOURNEY_REFRESH_MIN,
    CONF_LINE_ID,
    CONF_LINE_NAME,
    CONF_MARGIN_MIN,
    CONF_MODE,
    CONF_SCAN_INTERVAL_S,
    CONF_STOP_DEST_ID,
    CONF_STOP_DEST_NAME,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_WALK_OVERRIDE_MIN,
    DEFAULT_ACTIVE_END,
    DEFAULT_ACTIVE_START,
    DEFAULT_DEPARTURES_COUNT,
    DEFAULT_DIRECT_ONLY,
    DEFAULT_JOURNEY_REFRESH_MIN,
    DEFAULT_MARGIN_MIN,
    DEFAULT_SCAN_INTERVAL_S,
    DOMAIN,
    MAX_SCAN_INTERVAL_S,
    MIN_SCAN_INTERVAL_S,
    MODE_JOURNEY,
    MODE_STOP,
)
from .coordinator import CONF_STOP_LAT, CONF_STOP_LON
from .logic import parse_hhmm
from .models import LineInfo, Place

_LOGGER = logging.getLogger(__name__)

CONF_QUERY = "query"
CONF_CLEAR_DESTINATION = "clear_destination"
MAX_CALLS_PER_DAY = 900  # PRIM quota is 1000/day; keep headroom


def _window_seconds(start: time, end: time) -> int:
    """Length of the active window in seconds (start == end means 24h)."""
    s = start.hour * 3600 + start.minute * 60 + start.second
    e = end.hour * 3600 + end.minute * 60 + end.second
    return (e - s) % 86400 or 86400


def _select(options: list[dict[str, str]]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
    )


class IdfmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._api_key: str = ""
        self._home_entity: str | None = None
        self._lat: float | None = None
        self._lon: float | None = None
        self._places: dict[str, Place] = {}
        self._stop: Place | None = None
        self._lines: list[LineInfo] = []
        self._pending: dict[str, Any] = {}
        self._pending_title: str = ""
        self._pending_line_id: str | None = None

    def _client(self, api_key: str | None = None) -> PrimClient:
        return PrimClient(async_get_clientsession(self.hass), api_key or self._api_key)

    async def _check_key(self, api_key: str) -> str | None:
        """Return an error code or None."""
        try:
            await self._client(api_key).validate_key()
        except PrimAuthError:
            return "invalid_auth"
        except PrimError:
            return "cannot_connect"
        return None

    # ---- step 1: user -------------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            lat = user_input.get(CONF_HOME_LAT)
            lon = user_input.get(CONF_HOME_LON)
            entity = user_input.get(CONF_HOME_ENTITY)
            if lat is None or lon is None:
                lat = lon = None
                state = self.hass.states.get(entity) if entity else None
                if state is not None:
                    lat = state.attributes.get("latitude")
                    lon = state.attributes.get("longitude")
            if lat is None or lon is None:
                errors["base"] = "no_home"
            else:
                error = await self._check_key(user_input[CONF_API_KEY])
                if error:
                    errors["base"] = error
                else:
                    self._api_key = user_input[CONF_API_KEY]
                    self._home_entity = entity
                    self._lat = float(lat)
                    self._lon = float(lon)
                    return await self.async_step_mode()

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): TextSelector(),
                vol.Optional(
                    CONF_HOME_ENTITY, default="zone.home"
                ): EntitySelector(EntitySelectorConfig(domain=["zone", "person"])),
                vol.Optional(CONF_HOME_LAT): vol.Coerce(float),
                vol.Optional(CONF_HOME_LON): vol.Coerce(float),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    # ---- step 2: mode menu --------------------------------------------
    async def async_step_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="mode", menu_options=["stop_search", "destination_search"]
        )

    # ---- stop branch --------------------------------------------------
    async def _search(
        self, step_id: str, user_input: dict[str, Any] | None, types: tuple[str, ...] | None
    ) -> tuple[ConfigFlowResult | None, dict[str, str]]:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                if types is None:
                    places = await self._client().search_places(user_input[CONF_QUERY])
                else:
                    places = await self._client().search_places(
                        user_input[CONF_QUERY], types
                    )
            except PrimAuthError:
                errors["base"] = "invalid_auth"
            except PrimError:
                errors["base"] = "cannot_connect"
            else:
                if not places:
                    errors["base"] = "no_results"
                else:
                    self._places = {p.id: p for p in places}
                    return None, errors
        return (
            self.async_show_form(
                step_id=step_id,
                data_schema=vol.Schema({vol.Required(CONF_QUERY): TextSelector()}),
                errors=errors,
            ),
            errors,
        )

    async def async_step_stop_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        form, _ = await self._search("stop_search", user_input, ("stop_area",))
        if form is not None:
            return form
        return await self.async_step_stop_select()

    async def async_step_stop_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._stop = self._places[user_input[CONF_STOP_ID]]
            try:
                self._lines = await self._client().get_stop_area_lines(self._stop.id)
            except PrimError:
                self._lines = []
            return await self.async_step_stop_options()
        options = [{"value": p.id, "label": p.name} for p in self._places.values()]
        return self.async_show_form(
            step_id="stop_select",
            data_schema=vol.Schema({vol.Required(CONF_STOP_ID): _select(options)}),
        )

    async def async_step_stop_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._stop is not None
        if user_input is not None:
            line_id = user_input.get(CONF_LINE_ID) or None
            direction = (user_input.get(CONF_DIRECTION_FILTER) or "").strip()
            data: dict[str, Any] = {
                CONF_API_KEY: self._api_key,
                CONF_HOME_ENTITY: self._home_entity,
                CONF_HOME_LAT: self._lat,
                CONF_HOME_LON: self._lon,
                CONF_MODE: MODE_STOP,
                CONF_STOP_ID: self._stop.id,
                CONF_STOP_NAME: self._stop.name,
            }
            if self._stop.lat is not None and self._stop.lon is not None:
                data[CONF_STOP_LAT] = self._stop.lat
                data[CONF_STOP_LON] = self._stop.lon
            title = self._stop.name
            if line_id:
                line = next((x for x in self._lines if x.id == line_id), None)
                data[CONF_LINE_ID] = line_id
                if line is not None:
                    data[CONF_LINE_NAME] = line.name
                    if line.code:
                        title = f"{self._stop.name} ({line.code})"
            if direction:
                data[CONF_DIRECTION_FILTER] = direction
            self._pending = data
            self._pending_title = title
            self._pending_line_id = line_id
            return await self.async_step_stop_destination()

        fields: dict[Any, Any] = {}
        if self._lines:
            options = [
                {
                    "value": x.id,
                    "label": f"{x.code} – {x.name}" if x.code else x.name,
                }
                for x in self._lines
            ]
            fields[vol.Optional(CONF_LINE_ID)] = _select(options)
        fields[vol.Optional(CONF_DIRECTION_FILTER)] = TextSelector()
        return self.async_show_form(
            step_id="stop_options", data_schema=vol.Schema(fields)
        )

    async def _finish_stop(self, dest: Place | None) -> ConfigFlowResult:
        assert self._stop is not None
        data = dict(self._pending)
        title = self._pending_title
        uid_line = self._pending_line_id
        if dest is not None:
            data[CONF_STOP_DEST_ID] = dest.id
            data[CONF_STOP_DEST_NAME] = dest.name
            title = f"{title} → {dest.name}"
            uid_line = f"{uid_line or ''}_{dest.id}"
        await self.async_set_unique_id(self._unique_id(MODE_STOP, self._stop.id, uid_line))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=title, data=data)

    async def async_step_stop_destination(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optional destination station; empty query skips."""
        errors: dict[str, str] = {}
        if user_input is not None:
            query = (user_input.get(CONF_QUERY) or "").strip()
            if not query:
                return await self._finish_stop(None)
            try:
                places = await self._client().search_places(query, ("stop_area",))
            except PrimAuthError:
                errors["base"] = "invalid_auth"
            except PrimError:
                errors["base"] = "cannot_connect"
            else:
                if not places:
                    errors["base"] = "no_results"
                else:
                    self._places = {p.id: p for p in places}
                    return await self.async_step_stop_destination_select()
        return self.async_show_form(
            step_id="stop_destination",
            data_schema=vol.Schema({vol.Optional(CONF_QUERY): TextSelector()}),
            errors=errors,
        )

    async def async_step_stop_destination_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._finish_stop(self._places[user_input[CONF_STOP_DEST_ID]])
        options = [{"value": p.id, "label": p.name} for p in self._places.values()]
        return self.async_show_form(
            step_id="stop_destination_select",
            data_schema=vol.Schema({vol.Required(CONF_STOP_DEST_ID): _select(options)}),
        )

    # ---- destination branch -------------------------------------------
    async def async_step_destination_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        form, _ = await self._search("destination_search", user_input, None)
        if form is not None:
            return form
        return await self.async_step_destination_select()

    async def async_step_destination_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            place = self._places[user_input[CONF_DESTINATION_ID]]
            await self.async_set_unique_id(
                self._unique_id(MODE_JOURNEY, place.id, None)
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Domicile → {place.name}",
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_HOME_ENTITY: self._home_entity,
                    CONF_HOME_LAT: self._lat,
                    CONF_HOME_LON: self._lon,
                    CONF_MODE: MODE_JOURNEY,
                    CONF_DESTINATION_ID: place.id,
                    CONF_DESTINATION_NAME: place.name,
                },
            )
        options = [
            {"value": p.id, "label": p.name} for p in self._places.values()
        ]
        return self.async_show_form(
            step_id="destination_select",
            data_schema=vol.Schema(
                {vol.Required(CONF_DESTINATION_ID): _select(options)}
            ),
        )

    def _unique_id(self, mode: str, target: str, line_id: str | None) -> str:
        return f"{mode}_{target}_{line_id or ''}_{self._lat:.4f}_{self._lon:.4f}"

    # ---- reauth -------------------------------------------------------
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._check_key(user_input[CONF_API_KEY])
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): TextSelector()}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> IdfmOptionsFlow:
        return IdfmOptionsFlow()


class IdfmOptionsFlow(OptionsFlow):
    """Options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {k: v for k, v in user_input.items() if v is not None}
            clear = data.pop(CONF_CLEAR_DESTINATION, False)
            if self._estimated_calls_per_day(data) > MAX_CALLS_PER_DAY:
                errors["base"] = "quota_exceeded"
            else:
                if clear:
                    new_data = {
                        k: v
                        for k, v in self.config_entry.data.items()
                        if k not in (CONF_STOP_DEST_ID, CONF_STOP_DEST_NAME)
                    }
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=new_data
                    )
                return self.async_create_entry(title="", data=data)

        opts = self.config_entry.options
        walk = opts.get(CONF_WALK_OVERRIDE_MIN)
        walk_key = (
            vol.Optional(CONF_WALK_OVERRIDE_MIN, description={"suggested_value": walk})
        )
        has_dest = bool(self.config_entry.data.get(CONF_STOP_DEST_ID))
        dest_fields: dict[Any, Any] = {}
        if has_dest:
            dest_fields[
                vol.Required(
                    CONF_DIRECT_ONLY,
                    default=opts.get(CONF_DIRECT_ONLY, DEFAULT_DIRECT_ONLY),
                )
            ] = bool
            dest_fields[vol.Required(CONF_CLEAR_DESTINATION, default=False)] = bool
        schema = vol.Schema(
            {
                **dest_fields,
                vol.Required(
                    CONF_MARGIN_MIN, default=opts.get(CONF_MARGIN_MIN, DEFAULT_MARGIN_MIN)
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=30)),
                walk_key: vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                vol.Required(
                    CONF_SCAN_INTERVAL_S,
                    default=opts.get(CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL_S, max=MAX_SCAN_INTERVAL_S),
                ),
                vol.Required(
                    CONF_JOURNEY_REFRESH_MIN,
                    default=opts.get(
                        CONF_JOURNEY_REFRESH_MIN, DEFAULT_JOURNEY_REFRESH_MIN
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
                vol.Required(
                    CONF_ACTIVE_START,
                    default=opts.get(CONF_ACTIVE_START, DEFAULT_ACTIVE_START),
                ): TimeSelector(),
                vol.Required(
                    CONF_ACTIVE_END,
                    default=opts.get(CONF_ACTIVE_END, DEFAULT_ACTIVE_END),
                ): TimeSelector(),
                vol.Required(
                    CONF_DEPARTURES_COUNT,
                    default=opts.get(CONF_DEPARTURES_COUNT, DEFAULT_DEPARTURES_COUNT),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
            }
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    def _estimated_calls_per_day(self, new_opts: dict[str, Any]) -> float:
        """SIRI calls/day over all entries sharing this API key."""
        api_key = self.config_entry.data.get(CONF_API_KEY)
        total = 0.0
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_API_KEY) != api_key:
                continue
            opts = new_opts if entry.entry_id == self.config_entry.entry_id else entry.options
            interval = opts.get(CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S)
            start = parse_hhmm(opts.get(CONF_ACTIVE_START, DEFAULT_ACTIVE_START))
            end = parse_hhmm(opts.get(CONF_ACTIVE_END, DEFAULT_ACTIVE_END))
            total += _window_seconds(start, end) / max(interval, 1)
        return total

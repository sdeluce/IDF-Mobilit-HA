# CONTRACT — `idfm_departure` sprint 1 (greenfield)

## 1. Scope

Ships: a HACS custom component `idfm_departure` ("IDFM Prochain Départ") that computes
**when to leave home** (`leave_at = stop_departure − walk − margin`) for the next N departures
near home, in two modes per config entry: `stop` (SIRI stop-monitoring on a chosen stop_area,
optional line + direction filters) and `journey` (Navitia `/journeys` home→destination, refined
by SIRI at the first PT stop). UI config flow + options flow + reauth (en/fr), sensors + one
binary_sensor, service `idfm_departure.refresh`, pytest suite on pure logic with realistic
fixtures, `scripts/live_check.py`.

Not shipped: multi-leg realtime (only the first PT section is refined), shared per-API-key quota
accounting across entries, notifications/automations, Lovelace card, diagnostics platform,
HA core submission, any live verification of UNVERIFIED API formats (deferred to the user's key).

All datetimes inside the component are **timezone-aware UTC** `datetime`. Navitia naive local
strings are converted at the parse boundary (logic.py). Durations are **seconds (int)** unless
the name ends in `_min`.

## 2. Shared interface — `const.py` (owner A, written VERBATIM)

```python
DOMAIN = "idfm_departure"
PLATFORMS = ["sensor", "binary_sensor"]          # B converts to Platform enum in __init__
MANUFACTURER = "Île-de-France Mobilités"

PRIM_BASE_URL = "https://prim.iledefrance-mobilites.fr/marketplace"
SIRI_STOP_MONITORING_URL = f"{PRIM_BASE_URL}/stop-monitoring"
NAVITIA_BASE_URL = f"{PRIM_BASE_URL}/v2/navitia"
NAVITIA_PATH_PREFIXES = ("", "/coverage/idfm")   # tried in order; first non-404 is cached
HTTP_TIMEOUT_S = 30
RATE_LIMIT_MIN_INTERVAL_S = 0.25                 # 5 req/s max per client
PARIS_TZ = "Europe/Paris"

# config entry .data keys
CONF_API_KEY = "api_key"
CONF_HOME_ENTITY = "home_entity"                 # optional, e.g. "zone.home"
CONF_HOME_LAT = "home_lat"                       # float, resolved at setup
CONF_HOME_LON = "home_lon"
CONF_MODE = "mode"                               # MODE_STOP | MODE_JOURNEY
CONF_STOP_ID = "stop_id"                         # Navitia "stop_area:IDFM:71517"
CONF_STOP_NAME = "stop_name"
CONF_LINE_ID = "line_id"                         # optional Navitia "line:IDFM:C01742"
CONF_LINE_NAME = "line_name"                     # optional
CONF_DIRECTION_FILTER = "direction_filter"       # optional substring
CONF_DESTINATION_ID = "destination_id"           # Navitia place id or "lon;lat"
CONF_DESTINATION_NAME = "destination_name"
MODE_STOP = "stop"
MODE_JOURNEY = "journey"

# options keys + defaults
CONF_MARGIN_MIN = "margin_min";               DEFAULT_MARGIN_MIN = 3
CONF_WALK_OVERRIDE_MIN = "walk_override_min"  # absent/None = auto
CONF_SCAN_INTERVAL_S = "scan_interval_s";     DEFAULT_SCAN_INTERVAL_S = 120
CONF_JOURNEY_REFRESH_MIN = "journey_refresh_min"; DEFAULT_JOURNEY_REFRESH_MIN = 10
CONF_ACTIVE_START = "active_start";           DEFAULT_ACTIVE_START = "05:30"
CONF_ACTIVE_END = "active_end";               DEFAULT_ACTIVE_END = "01:00"
CONF_DEPARTURES_COUNT = "departures_count";   DEFAULT_DEPARTURES_COUNT = 3
MIN_SCAN_INTERVAL_S = 60; MAX_SCAN_INTERVAL_S = 3600

WALK_REFRESH_S = 86400            # walk time + stop lines re-fetched at most daily
LOCAL_TICK_S = 30                 # local recompute, no API call
TIME_TO_LEAVE_THRESHOLD_MIN = 1   # binary_sensor on when 0 <= minutes_until_leave <= 1

SERVICE_REFRESH = "refresh"
ATTR_ENTRY_ID = "entry_id"

WALK_SOURCE_AUTO = "auto"; WALK_SOURCE_MANUAL = "manual"
SOURCE_SIRI = "siri"; SOURCE_NAVITIA = "navitia"

# normalized modes -> icons
MODE_ICONS = {
    "metro": "mdi:subway-variant", "bus": "mdi:bus", "rer": "mdi:train",
    "train": "mdi:train", "tram": "mdi:tram", "other": "mdi:transit-connection-variant",
}
```

## 3. Shared interface — `models.py` (owner A, written VERBATIM)

All `@dataclass(frozen=True, slots=True)` except `IdfmData` (`slots=True`, mutable).

```python
class Place:            # Navitia /places result
    id: str             # "stop_area:IDFM:71517" | "admin:..."/address id | etc.
    name: str           # Navitia "name" (label)
    kind: str           # Navitia "embedded_type": "stop_area" | "address" | ...
    lat: float | None
    lon: float | None

class LineInfo:         # Navitia line
    id: str             # "line:IDFM:C01742"
    code: str           # display code "A", "14", "91" ("" if missing)
    name: str           # Navitia line "name"
    mode: str           # normalized: metro|bus|rer|tram|train|other
    network: str | None
    color: str | None   # hex without '#', as Navitia gives it

class StopVisit:        # one SIRI MonitoredStopVisit
    line_ref: str               # "STIF:Line::C01742:" as received
    line_name: str | None       # PublishedLineName via _val
    destination: str | None     # DestinationName via _val
    direction: str | None       # DirectionName via _val
    stop_ref: str | None        # MonitoringRef / StopPointRef via _val
    departure_at: datetime      # UTC aware; first non-null of ExpectedDeparture, AimedDeparture,
                                # ExpectedArrival, AimedArrival (MonitoredCall)
    realtime: bool              # True iff an Expected* field was used

class JourneyOption:    # one Navitia journey, reduced to what we need
    walk_s: int                 # sum of street_network+transfer durations BEFORE first public_transport section
    pt_departure_at: datetime   # first public_transport section departure_date_time (UTC aware)
    stop_point_id: str          # that section's from.stop_point.id, "stop_point:IDFM:22113"
    stop_name: str
    line_id: str | None         # from section links type "line", "line:IDFM:C01742"
    line_code: str              # display_informations.code
    mode: str                   # normalized from display_informations.physical_mode/commercial_mode
    direction: str | None       # display_informations.direction
    arrival_at: datetime | None # journey arrival_date_time

class PlannedDeparture:  # what entities display
    line: str                   # display code
    mode: str                   # normalized
    direction: str | None
    stop_departure: datetime    # UTC aware
    leave_at: datetime          # UTC aware
    realtime: bool
    walk_min: int               # ceil(walk_s / 60)
    source: str                 # SOURCE_SIRI | SOURCE_NAVITIA
    def as_attr(self) -> dict[str, Any]:
        # {"line","mode","direction","stop_departure"(ISO),"leave_at"(ISO),"realtime","walk_min"}

class IdfmData:
    mode: str                           # MODE_STOP | MODE_JOURNEY
    departures: list[PlannedDeparture]  # sorted by leave_at, already capped to departures_count
    walk_s: int | None                  # walk used for the primary departure (None = unknown)
    walk_source: str                    # WALK_SOURCE_AUTO | WALK_SOURCE_MANUAL
    stop_name: str | None
    last_api_update: datetime | None    # UTC
    active: bool                        # False when outside active window
    api_usage: dict[str, int]           # {"siri": n, "navitia": n} today (local day)
    def upcoming(self, now: datetime) -> list[PlannedDeparture]:  # leave_at >= now
```

## 4. `api.py` public surface (owner A). No `homeassistant` import. aiohttp only.

```python
class PrimError(Exception): ...
class PrimAuthError(PrimError): ...        # 401, 403
class PrimRateLimitError(PrimError): ...   # 429
class PrimServerError(PrimError): ...      # 5xx
class PrimNotFoundError(PrimError): ...    # 404
class PrimConnectionError(PrimError): ...  # timeout, aiohttp.ClientError, invalid JSON

class PrimClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None
    usage: dict[str, int]          # {"siri","navitia"}; reset when local Paris date changes
    async def validate_key(self) -> None                  # Navitia /places?q=Chatelet&count=1; raises PrimAuthError
    async def get_stop_monitoring(self, monitoring_ref: str, line_ref: str | None = None) -> list[StopVisit]
    async def search_places(self, query: str, types: tuple[str, ...] = ("stop_area", "address")) -> list[Place]
    async def get_stop_area_lines(self, stop_area_id: str) -> list[LineInfo]   # /stop_areas/{id}/lines
    async def get_journeys(self, from_: str, to: str, when: datetime, count: int = 3) -> list[JourneyOption]
    async def get_walking_time(self, from_: str, to: str, when: datetime) -> int | None  # seconds
```
Rules: headers `apikey`, `Accept: application/json`; timeout `HTTP_TIMEOUT_S`; serialize requests
with an `asyncio.Lock` + `RATE_LIMIT_MIN_INTERVAL_S`; increment `usage` per request sent.
`from_`/`to` are Navitia ids or `logic.coord(lat, lon)`. Journeys params:
`from,to,datetime=format_navitia_datetime(when),data_freshness=realtime,count`.
Walking: same endpoint + `direct_path=only&direct_path_mode[]=walking` (UNVERIFIED).
SIRI with `line_ref`: if server answers 400, retry once without `LineRef`; caller always filters locally.
SIRI empty `MonitoredStopVisit` / missing key -> `[]`, not an error.

## 5. `logic.py` public surface (owner A). Pure, stdlib + models + const only.

```python
def _val(x: Any) -> str | None             # str | {"value":..} | [{"value":..}, ...] | None
def parse_siri_datetime(s: str | None) -> datetime | None          # ISO, 'Z' accepted -> UTC
def parse_navitia_datetime(s: str) -> datetime                     # "YYYYMMDDTHHMMSS" Paris -> UTC
def format_navitia_datetime(dt: datetime) -> str                   # UTC/aware -> Paris naive string
def coord(lat: float, lon: float) -> str                           # "lon;lat"
def numeric_id(any_id: str) -> str | None   # "stop_area:IDFM:71517"/"STIF:StopArea:SP:71517:" -> "71517"; lines -> "C01742"
def navitia_to_siri(navitia_id: str) -> str # stop_point:IDFM:N->STIF:StopPoint:Q:N: ; stop_area:IDFM:N->STIF:StopArea:SP:N: ; line:IDFM:CN->STIF:Line::CN: ; else ValueError
def siri_to_navitia(siri_ref: str) -> str   # inverse; ValueError if unknown
def same_line(a: str | None, b: str | None) -> bool   # numeric_id equality, False if either None
def normalize_mode(raw: str | None) -> str  # casefold contains: "metro"/"métro"->metro, "rer"->rer, "tram"->tram,
                                            # "bus"->bus, "train"/"transilien"/"rail"/"ter"->train, else "other"
def line_icon(mode: str) -> str             # MODE_ICONS.get(mode, MODE_ICONS["other"])
def parse_stop_monitoring(payload: dict) -> list[StopVisit]   # drops visits with no usable time
def parse_places(payload: dict) -> list[Place]
def parse_lines(payload: dict) -> list[LineInfo]
def parse_journeys(payload: dict) -> list[JourneyOption]      # drops journeys with no PT section
def parse_walking_duration(payload: dict) -> int | None       # first journey whose sections are all non-PT: its "duration"
def matches_direction(visit: StopVisit, needle: str | None) -> bool  # None/"" -> True; casefold + accent-stripped
                                            # substring of destination OR direction
def filter_visits(visits: list[StopVisit], line_id: str | None, direction_filter: str | None) -> list[StopVisit]
def compute_leave_at(stop_departure: datetime, walk_s: int, margin_min: int) -> datetime
def minutes_until(leave_at: datetime, now: datetime) -> int   # floor((leave_at-now).total_seconds()/60)
def departures_from_visits(visits: list[StopVisit], walk_s: int, margin_min: int, now: datetime, count: int,
                           lines: dict[str, LineInfo]) -> list[PlannedDeparture]
    # lines keyed by numeric_id; line display = lines[...].code or visit.line_name or numeric_id;
    # skip leave_at < now; sort by leave_at; cap to count; source=SOURCE_SIRI
def departures_from_journeys(options: list[JourneyOption], walk_override_s: int | None, margin_min: int,
                             now: datetime, count: int) -> list[PlannedDeparture]  # source=SOURCE_NAVITIA, realtime=False
def merge_departures(primary: list[PlannedDeparture], secondary: list[PlannedDeparture],
                     now: datetime, count: int) -> list[PlannedDeparture]
    # drop secondary entries with same line and |stop_departure diff| < 60s of a primary; skip past; sort; cap
def parse_hhmm(s: str) -> time               # accepts "HH:MM" and "HH:MM:SS"
def in_active_window(now_local: time, start: time, end: time) -> bool  # start>end crosses midnight; start==end -> always True
```

## 6. Runtime behaviour (owner B, `coordinator.py`)

`class IdfmCoordinator(DataUpdateCoordinator[IdfmData])`,
`__init__(self, hass, entry: ConfigEntry, client: PrimClient)`; `update_interval =
timedelta(seconds=options[CONF_SCAN_INTERVAL_S])`; `async def async_force_refresh(self) -> None`
(sets a flag so the next update ignores the active window, then `async_refresh()`);
`async def async_shutdown()` cancels the tick. Registers `async_track_time_interval(LOCAL_TICK_S)`
that only calls `self.async_update_listeners()` (no I/O).

`_async_update_data`:
1. Outside active window (Paris local time) and not forced: return previous data with
   `active=False` and no API call (first refresh outside window returns empty departures).
2. Walk: if `walk_override_min` set -> `walk_s = override*60`, source manual. Else (stop mode)
   `get_walking_time(coord(home), stop_id, now)` cached for `WALK_REFRESH_S`. If still None ->
   `UpdateFailed("walk time unavailable; set walk_override_min")`.
3. Stop mode: lines cache `get_stop_area_lines(stop_id)` refreshed every `WALK_REFRESH_S`
   (failure non-fatal -> empty dict); `get_stop_monitoring(navitia_to_siri(stop_id),
   navitia_to_siri(line_id) if line_id else None)` -> `filter_visits` -> `departures_from_visits`.
4. Journey mode: `get_journeys(coord(home), destination_id, now)` cached `journey_refresh_min`.
   Primary option = first option. SIRI at `navitia_to_siri(primary.stop_point_id)` filtered by
   `primary.line_id` -> visits converted with walk = override or `primary.walk_s`. Merge with
   `departures_from_journeys(...)` via `merge_departures`. SIRI failure (any PrimError except
   auth) -> Navitia-only, log warning. No journeys -> empty departures (not an error).
5. Errors: `PrimAuthError` -> `ConfigEntryAuthFailed`; `PrimRateLimitError` ->
   `UpdateFailed("PRIM quota exceeded (429)")`; `PrimServerError`/`PrimConnectionError` ->
   `UpdateFailed` with the message.

Quota budget (documented in README): SIRI at 120 s over 05:30–01:00 = 585 req/day; journey
mode adds Navitia 117/day at 10 min + 2/day walk/lines. Quota is per key, entries add up.

## 7. Entities (owner B)

`has_entity_name=True`; `unique_id=f"{entry.entry_id}_{key}"`; `translation_key=key`;
DeviceInfo `identifiers={(DOMAIN, entry.entry_id)}`, `name=entry.title`,
`manufacturer=MANUFACTURER`, `model="PRIM"`, `entry_type=DeviceEntryType.SERVICE`.
All states computed at read time from `coordinator.data.upcoming(dt_util.utcnow())`; first item = "next".

| key | platform | state | unit / class | extra attrs |
|---|---|---|---|---|
| `leave_at` | sensor | next.leave_at | device_class timestamp | `departures` = [d.as_attr()], `active`, `api_usage`, `last_api_update` |
| `minutes_until_leave` | sensor | `minutes_until(next.leave_at, now)` int | `min`, measurement | — |
| `departure_at_stop` | sensor | next.stop_departure | timestamp | `realtime`, `source` |
| `line` | sensor | next.line | icon `line_icon(next.mode)` | `mode`, `direction` |
| `walk_time` | sensor | `ceil(walk_s/60)` | `min`, duration | `source` (auto/manual) |
| `time_to_leave` | binary_sensor | `0 <= minutes_until <= TIME_TO_LEAVE_THRESHOLD_MIN` | — | — |

No upcoming departure -> state `None`, binary_sensor `False`.

`__init__.py`: `type IdfmConfigEntry = ConfigEntry[IdfmCoordinator]`; setup creates
`PrimClient(async_get_clientsession(hass), data[CONF_API_KEY])`, coordinator,
`await coordinator.async_config_entry_first_refresh()`, `entry.runtime_data = coordinator`,
forwards PLATFORMS, `entry.async_on_unload(entry.add_update_listener(reload))`.
Service `idfm_departure.refresh` (registered in `async_setup`, schema `{vol.Optional(ATTR_ENTRY_ID): cv.string}`)
calls `async_force_refresh()` on that entry or on all loaded entries.

## 8. Config flow (owner C)

Steps (ids = translation keys):
1. `user`: `api_key` (str, required), `home_entity` (EntitySelector domains zone/person,
   default `zone.home`), `home_lat`/`home_lon` (optional floats; when both set they win over
   entity). Validate via `validate_key()` -> errors `invalid_auth` / `cannot_connect`; missing
   coords -> `no_home`. Store resolved lat/lon.
2. `mode` (menu): `stop_search` | `destination_search`.
3. `stop_search`: `query` -> `search_places(query, ("stop_area",))`; empty -> `no_results`.
   `stop_select`: `stop_id` (SelectSelector of results). `stop_options`: `line_id` optional
   (select from `get_stop_area_lines`, label `"{code} – {name}"`), `direction_filter` optional
   -> create entry, `mode=stop`, title `"{stop_name}"` or `"{stop_name} ({line code})"`.
4. `destination_search`: `query` -> `search_places(query)`; `destination_select`: `destination_id`
   -> create entry `mode=journey`, title `"Domicile → {destination_name}"`.
5. `reauth` / `reauth_confirm`: new `api_key`, validated, `async_update_reload_and_abort`.
Unique id: `f"{mode}_{stop_id or destination_id}_{line_id or ''}_{lat:.4f}_{lon:.4f}"`,
abort `already_configured`.

Options flow (`init`): `margin_min` int 0–30, `walk_override_min` optional int 1–60 (empty = auto),
`scan_interval_s` int 60–3600, `journey_refresh_min` int 5–120, `active_start`/`active_end`
TimeSelector, `departures_count` int 1–10. Defaults = const DEFAULT_*.

`strings.json` (C) must contain: config steps above, errors `invalid_auth`, `cannot_connect`,
`no_home`, `no_results`, aborts `already_configured`, `reauth_successful`; options step `init`;
`entity.sensor.{leave_at,minutes_until_leave,departure_at_stop,line,walk_time}.name`,
`entity.binary_sensor.time_to_leave.name`; `services.refresh` (name, description,
field `entry_id`). `translations/en.json` = copy of strings.json; `fr.json` same keys in French.

## 9. Ownership split (no overlap)

**A — API & pure logic** (lands interface files first; B/C code against sections 2–5 meanwhile)
- `custom_components/idfm_departure/const.py`, `models.py`, `api.py`, `logic.py`
- `tests/__init__.py`, `tests/conftest.py` (autouse `enable_custom_integrations`), `tests/test_logic.py`,
  `tests/test_api.py` (aiohttp mocked via `aioclient_mock` or `aioresponses`-free fake session),
  `tests/fixtures/siri_stop_monitoring.json`, `siri_empty.json`, `navitia_places.json`,
  `navitia_lines.json`, `navitia_journeys.json`, `navitia_walking.json`
- `pyproject.toml` (pytest `asyncio_mode = "auto"`, `testpaths = ["tests"]`, ruff config), `requirements_test.txt`
- `scripts/live_check.py`
Fixture minimum: SIRI >= 5 visits, 2+ lines, both wrapped `[{"value":..}]` and plain-string values,
one past departure, one visit with no Expected* (aimed only), one with only arrival times;
journeys >= 2 with walking + waiting + public_transport + transfer sections.

**B — runtime**
- `custom_components/idfm_departure/__init__.py`, `coordinator.py`, `sensor.py`, `binary_sensor.py`,
  `services.yaml`, `manifest.json`, `hacs.json`, `tests/test_coordinator.py`
- manifest: `{"domain":"idfm_departure","name":"IDFM Prochain Départ","codeowners":[],
  "config_flow":true,"documentation":"https://github.com/<owner>/idfm_departure",
  "integration_type":"service","iot_class":"cloud_polling","requirements":[],"version":"0.1.0"}`
- hacs.json: `{"name":"IDFM Prochain Départ","homeassistant":"2024.12.0","render_readme":true}`

**C — UX**
- `custom_components/idfm_departure/config_flow.py`, `strings.json`, `translations/en.json`,
  `translations/fr.json`, `README.md` (French: install HACS, PRIM key creation, modes, options,
  quota table from §6, service), `tests/test_config_flow.py`, `tests/test_translations.py`
  (en/fr key sets equal strings.json key set).

Nobody edits another owner's file. Interface mismatch -> report to lead, do not patch.

## 10. Deferred dependencies / stubs

- B and C until A lands: import from `const`, `models`, `api`, `logic` exactly as in §2–5. In tests,
  patch `custom_components.idfm_departure.api.PrimClient` methods (`AsyncMock`) returning
  model instances built directly; do not depend on fixtures or parsers.
- C depends on B's `__init__.py` only for `async_setup_entry` during flow tests: patch
  `custom_components.idfm_departure.async_setup_entry` to return `True`.
- B's `services.yaml` field names must match C's `services.refresh` strings (`entry_id`).
- A's `live_check.py` runs with the venv python (package `__init__` imports HA).

## 11. Verification gate (run in order, from repo root)

```bash
cd /home/stephane/Documents/Perso/idfMob
python3 -m venv .venv && .venv/bin/pip install -U pip pytest-homeassistant-custom-component ruff  # Python 3.12/3.13
.venv/bin/python -m compileall -q custom_components tests scripts
.venv/bin/ruff check custom_components tests scripts
for f in custom_components/idfm_departure/*.json custom_components/idfm_departure/translations/*.json hacs.json; do .venv/bin/python -m json.tool "$f" >/dev/null || echo "BAD $f"; done
.venv/bin/pytest tests -q
# LIVE gate (deferred, needs user key) — must print >=1 parsed departure in daytime:
PRIM_API_KEY=... .venv/bin/python scripts/live_check.py --stop stop_area:IDFM:71517 \
    --home 48.8584,2.3470 --dest-query "La Défense"
```
`live_check.py` prints: raw HTTP status per call, prefix chosen for Navitia, parsed StopVisits,
walking seconds, JourneyOptions, and PlannedDepartures for both modes. Non-zero exit on any PrimError.

## 12. Open questions (lead to answer; contract defaults stated)

1. Config flow order: spec lists stop step then optional destination. Contract uses a menu
   (stop OR destination) since journey mode never uses the chosen stop. Confirm; if journey
   should start from the chosen stop instead of home, §6.4 changes.
2. Walk time unavailable with no override: contract raises UpdateFailed. Alternative
   (haversine estimate) is not in the spec — want it?
3. Journey mode: only the primary option's (stop, line) is SIRI-refined (quota). OK?
4. Navitia walking via `direct_path=only&direct_path_mode[]=walking` and SIRI `LineRef` param
   are UNVERIFIED — confirm with live gate.
5. `journey_refresh_min` exposed as an option (spec gave only the default). Keep?
6. Quota shared across entries with the same key is not enforced, only reported (`api_usage`).

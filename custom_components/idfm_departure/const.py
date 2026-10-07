"""Constants for the IDFM Prochain Départ integration."""

DOMAIN = "idfm_departure"
PLATFORMS = ["sensor", "binary_sensor"]
MANUFACTURER = "Île-de-France Mobilités"

PRIM_BASE_URL = "https://prim.iledefrance-mobilites.fr/marketplace"
SIRI_STOP_MONITORING_URL = f"{PRIM_BASE_URL}/stop-monitoring"
NAVITIA_BASE_URL = f"{PRIM_BASE_URL}/v2/navitia"
NAVITIA_PATH_PREFIXES = ("", "/coverage/idfm")  # tried in order; first non-404 is cached
HTTP_TIMEOUT_S = 30
RATE_LIMIT_MIN_INTERVAL_S = 0.25  # 5 req/s max per client
PARIS_TZ = "Europe/Paris"

# config entry .data keys
CONF_API_KEY = "api_key"
CONF_HOME_ENTITY = "home_entity"
CONF_HOME_LAT = "home_lat"
CONF_HOME_LON = "home_lon"
CONF_MODE = "mode"
CONF_STOP_ID = "stop_id"
CONF_STOP_NAME = "stop_name"
CONF_LINE_ID = "line_id"
CONF_LINE_NAME = "line_name"
CONF_DIRECTION_FILTER = "direction_filter"
CONF_DESTINATION_ID = "destination_id"
CONF_DESTINATION_NAME = "destination_name"
CONF_STOP_DEST_ID = "stop_dest_id"
CONF_STOP_DEST_NAME = "stop_dest_name"
MODE_STOP = "stop"
MODE_JOURNEY = "journey"

# options keys + defaults
CONF_MARGIN_MIN = "margin_min"
DEFAULT_MARGIN_MIN = 3
CONF_WALK_OVERRIDE_MIN = "walk_override_min"
CONF_SCAN_INTERVAL_S = "scan_interval_s"
DEFAULT_SCAN_INTERVAL_S = 120
CONF_JOURNEY_REFRESH_MIN = "journey_refresh_min"
DEFAULT_JOURNEY_REFRESH_MIN = 10
CONF_ACTIVE_START = "active_start"
DEFAULT_ACTIVE_START = "05:30"
CONF_ACTIVE_END = "active_end"
DEFAULT_ACTIVE_END = "01:00"
CONF_DEPARTURES_COUNT = "departures_count"
DEFAULT_DEPARTURES_COUNT = 3
CONF_DIRECT_ONLY = "direct_only"
DEFAULT_DIRECT_ONLY = True
MIN_SCAN_INTERVAL_S = 60
MAX_SCAN_INTERVAL_S = 3600

WALK_REFRESH_S = 86400  # walk time + stop lines re-fetched at most daily
LOCAL_TICK_S = 30  # local recompute, no API call
TIME_TO_LEAVE_THRESHOLD_MIN = 1  # binary_sensor on when 0 <= minutes_until_leave <= 1

SERVICE_REFRESH = "refresh"
ATTR_ENTRY_ID = "entry_id"

WALK_SOURCE_AUTO = "auto"
WALK_SOURCE_MANUAL = "manual"
SOURCE_SIRI = "siri"
SOURCE_NAVITIA = "navitia"

# normalized modes -> icons
MODE_ICONS = {
    "metro": "mdi:subway-variant",
    "bus": "mdi:bus",
    "rer": "mdi:train",
    "train": "mdi:train",
    "tram": "mdi:tram",
    "other": "mdi:transit-connection-variant",
}

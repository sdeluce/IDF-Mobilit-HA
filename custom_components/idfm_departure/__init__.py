"""IDFM Prochain Départ integration."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .api import PrimClient
from .const import ATTR_ENTRY_ID, CONF_API_KEY, DOMAIN, PLATFORMS, SERVICE_REFRESH
from .coordinator import IdfmCoordinator

_LOGGER = logging.getLogger(__name__)

type IdfmConfigEntry = ConfigEntry[IdfmCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

STATIC_URL = "/idfm_departure_static"
CARD_FILE = "idfm-departure-card.js"
_WWW_DIR = Path(__file__).parent / "www"
_REGISTERED_KEY = f"{DOMAIN}_frontend_registered"


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the Lovelace card once."""
    if hass.data.get(_REGISTERED_KEY) or getattr(hass, "http", None) is None:
        return
    hass.data[_REGISTERED_KEY] = True
    version = json.loads((Path(__file__).parent / "manifest.json").read_text())[
        "version"
    ]
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(_WWW_DIR), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{STATIC_URL}/{CARD_FILE}?v={version}")

    async def _register_resource(hass: HomeAssistant) -> None:
        await _async_register_resource(hass, version)

    async_at_started(hass, _register_resource)


def _get_lovelace_resources(hass: HomeAssistant) -> object | None:
    """Return the Lovelace resources collection (new or legacy HA layout)."""
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA

        data = hass.data.get(LOVELACE_DATA)
    except ImportError:
        data = hass.data.get("lovelace")
    if data is None:
        return None
    if isinstance(data, dict):
        return data.get("resources")
    return getattr(data, "resources", None)


async def _async_register_resource(hass: HomeAssistant, version: str) -> None:
    """Add or refresh the card as a Lovelace module resource (storage mode)."""
    try:
        resources = _get_lovelace_resources(hass)
        if resources is None or not hasattr(resources, "async_create_item"):
            _LOGGER.debug("Lovelace resources not in storage mode; skipping")
            return
        if not resources.loaded:
            await resources.async_load()
            resources.loaded = True
        base = f"{STATIC_URL}/{CARD_FILE}"
        new_url = f"{base}?v={version}"
        for item in resources.async_items():
            if item.get("url", "").split("?", 1)[0] == base:
                if item["url"] != new_url:
                    await resources.async_update_item(
                        item["id"], {"res_type": "module", "url": new_url}
                    )
                return
        await resources.async_create_item({"res_type": "module", "url": new_url})
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Could not register Lovelace resource", exc_info=True)


SERVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the refresh service."""

    async def _handle_refresh(call: ServiceCall) -> None:
        entry_id = call.data.get(ATTR_ENTRY_ID)
        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if getattr(e, "runtime_data", None) is not None
            and (entry_id is None or e.entry_id == entry_id)
        ]
        if entry_id is not None and not entries:
            raise ServiceValidationError(f"No loaded entry with id {entry_id}")
        for entry in entries:
            coordinator = entry.runtime_data
            await coordinator.async_force_refresh()
            if not coordinator.last_update_success:
                err = coordinator.last_exception
                raise HomeAssistantError(
                    f"Refresh failed for {entry.title}: {err or 'unknown error'}"
                )

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _handle_refresh, schema=SERVICE_SCHEMA
    )
    await _async_register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IdfmConfigEntry) -> bool:
    """Set up a config entry."""
    client = PrimClient(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    coordinator = IdfmCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(p) for p in PLATFORMS]
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: IdfmConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: IdfmConfigEntry) -> bool:
    """Unload a config entry."""
    ok = await hass.config_entries.async_unload_platforms(
        entry, [Platform(p) for p in PLATFORMS]
    )
    if ok:
        await entry.runtime_data.async_shutdown()
    return ok

"""Sensors for IDFM Prochain Départ."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER, MODE_ICONS
from .coordinator import IdfmCoordinator
from .logic import line_icon, minutes_until
from .models import IdfmData, PlannedDeparture


def _next(data: IdfmData | None) -> PlannedDeparture | None:
    if data is None:
        return None
    up = data.upcoming(dt_util.utcnow())
    return up[0] if up else None


def _val_leave_at(data: IdfmData) -> datetime | None:
    n = _next(data)
    return n.leave_at if n else None


def _val_minutes(data: IdfmData) -> int | None:
    n = _next(data)
    return minutes_until(n.leave_at, dt_util.utcnow()) if n else None


def _val_stop_dep(data: IdfmData) -> datetime | None:
    n = _next(data)
    return n.stop_departure if n else None


def _val_line(data: IdfmData) -> str | None:
    n = _next(data)
    return n.line if n else None


def _val_walk(data: IdfmData) -> int | None:
    return None if data.walk_s is None else math.ceil(data.walk_s / 60)


def _attrs_leave_at(data: IdfmData) -> dict[str, Any]:
    now = dt_util.utcnow()
    upcoming = data.upcoming(now)
    n = upcoming[0] if upcoming else None
    nxt: dict[str, Any] = {
        "line": n.line if n else None,
        "line_color": n.line_color if n else None,
        "line_text_color": n.line_text_color if n else None,
        "mode": n.mode if n else None,
        "direction": n.direction if n else None,
        "stop_departure": n.stop_departure.astimezone(UTC).isoformat() if n else None,
        "walk_min": n.walk_min if n else None,
        "realtime": n.realtime if n else None,
    }
    return {
        "stop_name": data.stop_name,
        **nxt,
        "departures": [d.as_attr() for d in upcoming],
        "active": data.active,
        "api_usage": dict(data.api_usage),
        "last_api_update": data.last_api_update.isoformat()
        if data.last_api_update
        else None,
    }


def _attrs_stop_dep(data: IdfmData) -> dict[str, Any]:
    n = _next(data)
    return {"realtime": n.realtime, "source": n.source} if n else {}


def _attrs_line(data: IdfmData) -> dict[str, Any]:
    n = _next(data)
    return {"mode": n.mode, "direction": n.direction} if n else {}


def _attrs_walk(data: IdfmData) -> dict[str, Any]:
    return {"source": data.walk_source}


@dataclass(frozen=True, kw_only=True)
class IdfmSensorDescription(SensorEntityDescription):
    """Sensor description with value and attribute getters."""

    value_fn: Callable[[IdfmData], Any]
    attrs_fn: Callable[[IdfmData], dict[str, Any]] | None = None


SENSORS: tuple[IdfmSensorDescription, ...] = (
    IdfmSensorDescription(
        key="leave_at",
        translation_key="leave_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_val_leave_at,
        attrs_fn=_attrs_leave_at,
    ),
    IdfmSensorDescription(
        key="minutes_until_leave",
        translation_key="minutes_until_leave",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_val_minutes,
    ),
    IdfmSensorDescription(
        key="departure_at_stop",
        translation_key="departure_at_stop",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_val_stop_dep,
        attrs_fn=_attrs_stop_dep,
    ),
    IdfmSensorDescription(
        key="line",
        translation_key="line",
        value_fn=_val_line,
        attrs_fn=_attrs_line,
    ),
    IdfmSensorDescription(
        key="walk_time",
        translation_key="walk_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        value_fn=_val_walk,
        attrs_fn=_attrs_walk,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors."""
    coordinator: IdfmCoordinator = entry.runtime_data
    async_add_entities(IdfmSensor(coordinator, d) for d in SENSORS)


class IdfmSensor(CoordinatorEntity[IdfmCoordinator], SensorEntity):
    """A computed IDFM sensor."""

    _attr_has_entity_name = True
    entity_description: IdfmSensorDescription

    def __init__(
        self, coordinator: IdfmCoordinator, description: IdfmSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model="PRIM",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        return None if data is None else self.entity_description.value_fn(data)

    @property
    def icon(self) -> str | None:
        if self.entity_description.key != "line":
            return None
        n = _next(self.coordinator.data)
        return line_icon(n.mode) if n else MODE_ICONS["other"]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        fn = self.entity_description.attrs_fn
        return fn(data) if data is not None and fn else None

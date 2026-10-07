"""Binary sensor: time to leave."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER, TIME_TO_LEAVE_THRESHOLD_MIN
from .coordinator import IdfmCoordinator
from .logic import minutes_until


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the binary sensor."""
    async_add_entities([IdfmTimeToLeave(entry.runtime_data)])


class IdfmTimeToLeave(CoordinatorEntity[IdfmCoordinator], BinarySensorEntity):
    """On when it is time to leave."""

    _attr_has_entity_name = True
    _attr_translation_key = "time_to_leave"

    def __init__(self, coordinator: IdfmCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_time_to_leave"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model="PRIM",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        if data is None:
            return False
        now = dt_util.utcnow()
        up = data.upcoming(now)
        if not up:
            return False
        return 0 <= minutes_until(up[0].leave_at, now) <= TIME_TO_LEAVE_THRESHOLD_MIN

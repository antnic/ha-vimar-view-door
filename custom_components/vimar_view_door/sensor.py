"""Sensor platform for Vimar VIEW Door."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vimar VIEW Door sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    sensors = [
        VimarStatusSensor(coordinator, api, "info_version", "Firmware Version", "mdi:information-outline"),
        VimarStatusSensor(coordinator, api, "info_mac", "MAC Address", "mdi:network"),
    ]

    async_add_entities(sensors)

class VimarStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Vimar VIEW Door status."""

    def __init__(self, coordinator, api, key, name, icon):
        super().__init__(coordinator)
        self.api = api
        self.key = key
        self._attr_name = f"{api.device_info.get('name', 'Vimar Intercom')} {name}"
        self._attr_unique_id = f"{api.device_info.get('id', 'vimar')}_{key}"
        self._attr_icon = icon

    @property
    def native_value(self):
        """Return native value of the sensor."""
        return self.coordinator.data.get(self.key)

    @property
    def device_info(self):
        """Return device info for Home Assistant."""
        return {
            "identifiers": {(DOMAIN, self.api.device_info.get("id", "vimar"))},
            "name": self.api.device_info.get("name", "Vimar Intercom"),
            "manufacturer": "Vimar",
            "model": self.api.device_info.get("model", "VIEW Door"),
            "sw_version": self.coordinator.data.get("info_version", "1.0.0"),
        }

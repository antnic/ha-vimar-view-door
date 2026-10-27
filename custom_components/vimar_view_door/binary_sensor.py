"""Binary sensor platform for Vimar VIEW Door."""
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up Vimar VIEW Door binary sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    sensors = [
        VimarBinarySensor(coordinator, api, "calling", "Doorbell Call", BinarySensorDeviceClass.OCCUPANCY, "mdi:doorbell-video"),
        VimarBinarySensor(coordinator, api, "humandete", "Human Detection", BinarySensorDeviceClass.MOTION, "mdi:motion-sensor"),
        VimarBinarySensor(coordinator, api, "smd_peds", "Pedestrian Detection", BinarySensorDeviceClass.MOTION, "mdi:walk"),
        VimarBinarySensor(coordinator, api, "smd_vehc", "Vehicle Detection", BinarySensorDeviceClass.MOTION, "mdi:car"),
    ]

    async_add_entities(sensors)

class VimarBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for Vimar VIEW Door."""

    def __init__(self, coordinator, api, key, name, device_class, icon):
        super().__init__(coordinator)
        self.api = api
        self.key = key
        self._attr_name = f"{api.device_info.get('name', 'Vimar Intercom')} {name}"
        self._attr_unique_id = f"{api.device_info.get('id', 'vimar')}_{key}"
        self._attr_device_class = device_class
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        return bool(self.coordinator.data.get(self.key, False))

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

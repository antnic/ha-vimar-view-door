"""Button platform for Vimar VIEW Door."""
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vimar VIEW Door buttons."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    buttons = [
        VimarOpenButton(coordinator, api, door=1, locknumber=1, name="Open Pedestrian Door", icon="mdi:door-open"),
        VimarOpenButton(coordinator, api, door=1, locknumber=2, name="Open Driveway Gate", icon="mdi:gate"),
    ]

    async_add_entities(buttons)

class VimarOpenButton(CoordinatorEntity, ButtonEntity):
    """Button to open door or gate."""

    def __init__(self, coordinator, api, door=0, locknumber=0, name="Open Door", icon="mdi:door-open"):
        super().__init__(coordinator)
        self.api = api
        self.door = door
        self.locknumber = locknumber
        self._attr_name = f"{api.device_info.get('name', 'Vimar Intercom')} {name}"
        self._attr_unique_id = f"{api.device_info.get('id', 'vimar')}_btn_open_{locknumber}"
        self._attr_icon = icon

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.info("Opening Vimar door %s lock %s...", self.door, self.locknumber)
        await self.hass.async_add_executor_job(
            self.api.unlock, self.door, self.locknumber
        )
        await self.coordinator.async_request_refresh()

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

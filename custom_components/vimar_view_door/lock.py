"""Lock platform for Vimar VIEW Door."""
import asyncio
import logging
from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Duration (in seconds) that the lock stays in 'unlocked' state before automatically relocking
AUTO_LOCK_DELAY = 5

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vimar VIEW Door lock."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    locks = [
        VimarLock(coordinator, api, door=1, locknumber=1, name="Pedestrian Door Lock"),
        VimarLock(coordinator, api, door=1, locknumber=2, name="Driveway Gate Lock"),
    ]

    async_add_entities(locks)

class VimarLock(CoordinatorEntity, LockEntity):
    """Representation of a Vimar VIEW Door Lock (pulse electric strike / gate trigger)."""

    _attr_supported_features = LockEntityFeature.OPEN

    def __init__(self, coordinator, api, door=0, locknumber=0, name="Lock"):
        super().__init__(coordinator)
        self.api = api
        self.door = door
        self.locknumber = locknumber
        self._attr_name = f"{api.device_info.get('name', 'Vimar Intercom')} {name}"
        self._attr_unique_id = f"{api.device_info.get('id', 'vimar')}_lock_{locknumber}"
        self._attr_icon = "mdi:door-open" if locknumber == 1 else "mdi:gate"
        self._attr_is_locked = True
        self._attr_is_unlocking = False
        self._auto_lock_task = None

    @property
    def is_locked(self) -> bool:
        """Return true if lock is locked."""
        return self._attr_is_locked

    @property
    def is_unlocking(self) -> bool:
        """Return true if lock is currently unlocking."""
        return self._attr_is_unlocking

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the door/gate with an automatic re-lock pulse timer."""
        _LOGGER.info("Unlocking Vimar Door %s (Lock %s)...", self.door, self.locknumber)
        
        # Set state to unlocking
        self._attr_is_unlocking = True
        self.async_write_ha_state()

        success = await self.hass.async_add_executor_job(
            self.api.unlock, self.door, self.locknumber
        )

        self._attr_is_unlocking = False

        if success:
            # Set state to unlocked for visual feedback in Home Assistant & Apple Home
            self._attr_is_locked = False
            self.async_write_ha_state()

            # Schedule automatic re-lock after AUTO_LOCK_DELAY seconds
            if self._auto_lock_task and not self._auto_lock_task.done():
                self._auto_lock_task.cancel()
            self._auto_lock_task = self.hass.async_create_task(self._async_auto_relock())
        else:
            self._attr_is_locked = True
            self.async_write_ha_state()

    async def _async_auto_relock(self) -> None:
        """Automatically reset lock state to locked after the pulse duration."""
        try:
            await asyncio.sleep(AUTO_LOCK_DELAY)
            _LOGGER.info("Vimar Lock %s pulse ended: auto-resetting to locked", self.locknumber)
            self._attr_is_locked = True
            self.async_write_ha_state()
        except asyncio.CancelledError:
            pass

    async def async_open(self, **kwargs: Any) -> None:
        """Open the latch (same as unlock for momentary pulse locks)."""
        await self.async_unlock(**kwargs)

    async def async_lock(self, **kwargs: Any) -> None:
        """Manual lock command: immediately reset state to locked."""
        if self._auto_lock_task and not self._auto_lock_task.done():
            self._auto_lock_task.cancel()
        self._attr_is_locked = True
        self._attr_is_unlocking = False
        self.async_write_ha_state()

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

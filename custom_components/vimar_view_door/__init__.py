"""The Vimar VIEW Door Integration."""
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_DEVICE_IP,
    CONF_AUTH_CODE,
    CONF_DEVICE_ID,
    DEFAULT_POLL_INTERVAL,
)
from .vimar_api import VimarDeviceApi

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "lock", "button", "sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Vimar VIEW Door from a config entry."""
    email = entry.data.get(CONF_EMAIL, "")
    password = entry.data.get(CONF_PASSWORD, "")
    device_ip = entry.data.get(CONF_DEVICE_IP, "")
    auth_code = entry.data.get(CONF_AUTH_CODE)
    device_id = entry.data.get(CONF_DEVICE_ID)

    api = VimarDeviceApi(
        email=email,
        password=password,
        device_ip=device_ip,
        out_auth_code=auth_code,
        device_id=device_id,
    )

    # Initial cloud sync only if auth_code is missing
    if not api.out_auth_code:
        await hass.async_add_executor_job(api.authenticate_and_fetch_devices)

    async def async_update_data():
        """Fetch status from local device."""
        try:
            return await hass.async_add_executor_job(api.get_status)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Vimar device: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="vimar_view_door",
        update_method=async_update_data,
        update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

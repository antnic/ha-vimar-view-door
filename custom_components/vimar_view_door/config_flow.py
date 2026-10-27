"""Config flow for Vimar VIEW Door integration."""
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import AbortFlow
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_DEVICE_IP,
    CONF_AUTH_CODE,
    CONF_DEVICE_ID,
)
from .vimar_api import VimarDeviceApi

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    vol.Optional(CONF_EMAIL, default=""): cv.string,
    vol.Optional(CONF_PASSWORD, default=""): cv.string,
    vol.Optional(CONF_DEVICE_IP, default=""): cv.string,
    vol.Optional(CONF_AUTH_CODE, default=""): cv.string,
})

class VimarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vimar VIEW Door."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            email = user_input.get(CONF_EMAIL, "").strip()
            password = user_input.get(CONF_PASSWORD, "").strip()
            device_ip = user_input.get(CONF_DEVICE_IP, "").strip()
            auth_code = user_input.get(CONF_AUTH_CODE, "").strip()

            if not auth_code and (not email or not password):
                errors["base"] = "no_auth_provided"
            else:
                api = VimarDeviceApi(
                    email=email,
                    password=password,
                    device_ip=device_ip,
                    out_auth_code=auth_code if auth_code else None,
                )
                device_info = None
                try:
                    device_info = await self.hass.async_add_executor_job(
                        api.authenticate_and_fetch_devices
                    )
                except AbortFlow:
                    raise
                except ValueError as err:
                    _LOGGER.error("Authentication error for Vimar View Door: %s", err)
                    errors["base"] = "invalid_auth"
                except Exception as err:
                    _LOGGER.error("Cannot connect to Vimar View Door: %s", err)
                    if "JSONDecodeError" in str(type(err)) or "SSO Login failed" in str(err):
                        errors["base"] = "invalid_auth"
                    else:
                        errors["base"] = "cannot_connect"

                if device_info is not None and not errors:
                    import hashlib
                    fallback_id = hashlib.md5((auth_code or email).encode()).hexdigest()[:12]
                    unique_id = device_info.get("id") or f"vimar_{fallback_id}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    entry_data = {
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                        CONF_DEVICE_IP: device_ip,
                        CONF_AUTH_CODE: device_info.get("out_auth_code", auth_code),
                        CONF_DEVICE_ID: unique_id,
                    }

                    return self.async_create_entry(
                        title=f"{device_info.get('name', 'Vimar Intercom')} ({device_info.get('model', 'VIEW Door')})",
                        data=entry_data,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

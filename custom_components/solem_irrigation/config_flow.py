"""Config flow for Solem Irrigation integration."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_FAST_SCAN_INTERVAL,
    DEFAULT_FULL_REFRESH_INTERVAL,
    DEFAULT_MANUAL_DURATION,
    CONF_FAST_SCAN_INTERVAL,
    CONF_FULL_REFRESH_INTERVAL,
    CONF_MANUAL_DURATION,
)
from .solem_api import SolemAPI, AuthenticationError, APIError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
})


class SolemConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Solem Irrigation."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._username: Optional[str] = None
        self._password: Optional[str] = None

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}
        
        if user_input is not None:
            try:
                # Test the credentials
                await self._test_credentials(
                    user_input[CONF_USERNAME], 
                    user_input[CONF_PASSWORD]
                )
                
                # Create unique ID based on username
                await self.async_set_unique_id(user_input[CONF_USERNAME])
                self._abort_if_unique_id_configured()
                
                # Store credentials
                self._username = user_input[CONF_USERNAME]
                self._password = user_input[CONF_PASSWORD]
                
                return self.async_create_entry(
                    title=f"Solem Irrigation ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )
                
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Dict[str, Any]) -> FlowResult:
        """Handle reauth flow."""
        self.context["entry_id"] = self.context.get("entry_id")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle reauth confirmation."""
        errors: Dict[str, str] = {}
        
        # Get the existing entry
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if not entry:
            return self.async_abort(reason="reauth_failed")
        
        if user_input is not None:
            try:
                # Test new credentials
                await self._test_credentials(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD]
                )
                
                # Update the config entry
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, **user_input}
                )
                
                # Clear stored tokens to force refresh
                if DOMAIN in self.hass.data and entry.entry_id in self.hass.data[DOMAIN]:
                    coordinator = self.hass.data[DOMAIN][entry.entry_id]["coordinator"]
                    await coordinator.token_manager.clear_tokens()
                
                return self.async_abort(reason="reauth_successful")
                
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during reauth")
                errors["base"] = "unknown"

        # Show form with current username pre-filled
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            description_placeholders={"username": entry.data.get(CONF_USERNAME, "")},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return SolemOptionsFlowHandler(config_entry)

    async def _test_credentials(self, username: str, password: str) -> None:
        """Test if we can authenticate with the credentials."""
        api = SolemAPI()
        try:
            success = await api.login(username, password)
            if not success:
                raise AuthenticationError("Login failed")
                
            # Try to get modules to verify full API access
            await api.get_modules()
            
        except AuthenticationError:
            raise
        except (APIError, Exception) as e:
            _LOGGER.error("Failed to connect to Solem API: %s", e)
            raise CannotConnect from e
        finally:
            await api.close()


class SolemOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Solem options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options_schema = vol.Schema({
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
            vol.Optional(
                CONF_FAST_SCAN_INTERVAL,
                default=self.config_entry.options.get(CONF_FAST_SCAN_INTERVAL, DEFAULT_FAST_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=15, max=300)),
            vol.Optional(
                CONF_FULL_REFRESH_INTERVAL,
                default=self.config_entry.options.get(CONF_FULL_REFRESH_INTERVAL, DEFAULT_FULL_REFRESH_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=300, max=7200)),
            vol.Optional(
                CONF_MANUAL_DURATION,
                default=self.config_entry.options.get(CONF_MANUAL_DURATION, DEFAULT_MANUAL_DURATION),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
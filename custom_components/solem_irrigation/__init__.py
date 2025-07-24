"""
Solem Irrigation System integration for Home Assistant.

This integration provides control and monitoring of Solem irrigation systems.
"""
import asyncio
import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_FAST_SCAN_INTERVAL,
    DEFAULT_FULL_REFRESH_INTERVAL,
    DEFAULT_MANUAL_DURATION,
    CONF_FAST_SCAN_INTERVAL,
    CONF_FULL_REFRESH_INTERVAL,
    CONF_MANUAL_DURATION,
    SERVICE_START_MANUAL_WATERING,
    SERVICE_STOP_WATERING,
    SERVICE_TEST_ALL_VALVES,
    SERVICE_START_PROGRAM,
)
from .solem_api import SolemAPI, AuthenticationError, APIError, ZoneNotAvailableError
from .token_manager import SolemTokenManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
]

# Service schemas
START_MANUAL_WATERING_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.entity_id,
    vol.Optional("duration", default=DEFAULT_MANUAL_DURATION): cv.positive_int,
})

STOP_WATERING_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.entity_id,
})

TEST_ALL_VALVES_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.entity_id,
    vol.Optional("duration", default=2): cv.positive_int,
})

START_PROGRAM_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.entity_id,
})


class SolemDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Solem data from the API."""

    def __init__(self, hass: HomeAssistant, api: SolemAPI, config_entry: ConfigEntry):
        """Initialize the coordinator."""
        self.api = api
        self.config_entry = config_entry
        self.token_manager = SolemTokenManager(hass, config_entry)
        
        # Get configuration
        scan_interval = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        
        # Polling management
        self.fast_poll_modules = set()
        self.last_full_refresh = None
        self.consecutive_failures = 0
        
        # Configuration
        self.fast_interval = config_entry.options.get(CONF_FAST_SCAN_INTERVAL, DEFAULT_FAST_SCAN_INTERVAL)
        self.full_refresh_interval = config_entry.options.get(CONF_FULL_REFRESH_INTERVAL, DEFAULT_FULL_REFRESH_INTERVAL)

    async def _async_update_data(self):
        """Fetch data from API with smart polling."""
        try:
            # Ensure tokens are valid
            await self.token_manager.ensure_valid_tokens(self.api)
            
            # Determine update strategy
            now = dt_util.utcnow()
            needs_full_refresh = (
                self.last_full_refresh is None or 
                (now - self.last_full_refresh).total_seconds() > self.full_refresh_interval
            )
            
            if needs_full_refresh:
                data = await self._full_refresh()
                self.last_full_refresh = now
            elif self.fast_poll_modules:
                data = await self._fast_update()
            else:
                data = await self._normal_update()
            
            # Reset failure counter on success
            self.consecutive_failures = 0
            
            # Adjust polling interval based on watering status
            self._adjust_polling_interval()
            
            return data
            
        except AuthenticationError as e:
            _LOGGER.warning("Authentication error, attempting token refresh: %s", e)
            try:
                await self.token_manager.force_refresh(self.api)
                return await self._normal_update()
            except Exception as refresh_error:
                _LOGGER.error("Token refresh failed: %s", refresh_error)
                raise ConfigEntryAuthFailed("Authentication failed") from refresh_error
                
        except Exception as e:
            self.consecutive_failures += 1
            _LOGGER.error("Error fetching Solem data (attempt %d): %s", self.consecutive_failures, e)
            raise UpdateFailed(f"Error communicating with Solem API: {e}") from e

    async def _full_refresh(self):
        """Full refresh of all modules and programs."""
        _LOGGER.debug("Performing full refresh")
        
        modules = await self.api.get_modules()
        
        # Get programs for each module
        for module in modules:
            try:
                programs = await self.api.get_module_programs(module.id)
                module.programs = programs
            except Exception as e:
                _LOGGER.warning("Failed to get programs for module %s: %s", module.name, e)
        
        return {"modules": {m.id: m for m in modules}}

    async def _normal_update(self):
        """Normal status update for all modules."""
        _LOGGER.debug("Performing normal status update")
        
        if not self.data or "modules" not in self.data:
            return await self._full_refresh()
        
        updated_modules = await self.api.refresh_all_modules_status()
        
        # Check for newly started watering
        for module_id, module in updated_modules.items():
            if module.is_watering:
                self.fast_poll_modules.add(module_id)
        
        # Update existing data
        current_modules = self.data["modules"]
        for module_id, updated_module in updated_modules.items():
            if module_id in current_modules:
                # Preserve programs
                updated_module.programs = current_modules[module_id].programs
                current_modules[module_id] = updated_module
        
        return self.data

    async def _fast_update(self):
        """Fast update for modules that are currently watering."""
        _LOGGER.debug("Performing fast update for %d watering modules", len(self.fast_poll_modules))
        
        if not self.data or "modules" not in self.data:
            return await self._full_refresh()
        
        # Update only the modules that are watering
        modules_to_remove = set()
        current_modules = self.data["modules"]
        
        for module_id in self.fast_poll_modules.copy():
            try:
                status = await self.api.get_module_status_only(module_id)
                if status and module_id in current_modules:
                    current_modules[module_id].status = status
                    
                    # Update zone watering status
                    for zone in current_modules[module_id].zones:
                        zone.is_currently_watering = False
                    
                    if status.is_running and status.running_station > 0:
                        station_index = status.running_station - 1
                        if station_index < len(current_modules[module_id].zones):
                            current_modules[module_id].zones[station_index].is_currently_watering = True
                    
                    # Remove from fast polling if no longer watering
                    if not status.is_running:
                        modules_to_remove.add(module_id)
                        
            except Exception as e:
                _LOGGER.warning("Failed to update status for module %s: %s", module_id, e)
                modules_to_remove.add(module_id)
        
        # Remove modules that stopped watering
        self.fast_poll_modules.difference_update(modules_to_remove)
        
        return self.data

    def _adjust_polling_interval(self):
        """Adjust polling interval based on current watering status."""
        if self.fast_poll_modules:
            # Switch to fast polling
            new_interval = timedelta(seconds=self.fast_interval)
        else:
            # Use normal polling
            scan_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            new_interval = timedelta(seconds=scan_interval)
        
        if self.update_interval != new_interval:
            _LOGGER.debug("Adjusting polling interval to %s", new_interval)
            self.update_interval = new_interval

    async def async_start_manual_watering(self, module_id: str, zone_index: int, duration: int):
        """Start manual watering for a zone."""
        try:
            await self.token_manager.ensure_valid_tokens(self.api)
            success = await self.api.start_manual_watering(module_id, zone_index, duration)
            
            if success:
                # Add to fast polling and trigger immediate update
                self.fast_poll_modules.add(module_id)
                await self.async_request_refresh()
                
            return success
            
        except (AuthenticationError, APIError, ZoneNotAvailableError) as e:
            _LOGGER.error("Failed to start manual watering: %s", e)
            raise HomeAssistantError(str(e)) from e

    async def async_stop_watering(self, module_id: str):
        """Stop all watering on a module."""
        try:
            await self.token_manager.ensure_valid_tokens(self.api)
            success = await self.api.stop_watering(module_id)
            
            if success:
                # Remove from fast polling and trigger immediate update
                self.fast_poll_modules.discard(module_id)
                await self.async_request_refresh()
                
            return success
            
        except (AuthenticationError, APIError) as e:
            _LOGGER.error("Failed to stop watering: %s", e)
            raise HomeAssistantError(str(e)) from e

    async def async_test_all_valves(self, module_id: str, duration: int):
        """Test all valves on a module."""
        try:
            await self.token_manager.ensure_valid_tokens(self.api)
            success = await self.api.test_all_valves(module_id, duration)
            
            if success:
                # Add to fast polling and trigger immediate update
                self.fast_poll_modules.add(module_id)
                await self.async_request_refresh()
                
            return success
            
        except (AuthenticationError, APIError) as e:
            _LOGGER.error("Failed to test all valves: %s", e)
            raise HomeAssistantError(str(e)) from e

    async def async_start_program(self, module_id: str, program_index: int):
        """Start a program on a module."""
        try:
            await self.token_manager.ensure_valid_tokens(self.api)
            success = await self.api.start_program(module_id, program_index)
            
            if success:
                # Add to fast polling and trigger immediate update
                self.fast_poll_modules.add(module_id)
                await self.async_request_refresh()
                
            return success
            
        except (AuthenticationError, APIError) as e:
            _LOGGER.error("Failed to start program: %s", e)
            raise HomeAssistantError(str(e)) from e


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Solem Irrigation from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Create API instance
    api = SolemAPI()
    
    try:
        # Test authentication
        await api.login(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
        
    except AuthenticationError as e:
        _LOGGER.error("Authentication failed: %s", e)
        raise ConfigEntryAuthFailed("Invalid credentials") from e
    except Exception as e:
        _LOGGER.error("Failed to connect to Solem API: %s", e)
        return False
    
    # Create coordinator
    coordinator = SolemDataUpdateCoordinator(hass, api, entry)
    
    # Load stored tokens
    await coordinator.token_manager.load_tokens()
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()
    
    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
    }
    
    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register services
    await _async_register_services(hass)
    
    # Start token refresh scheduling
    coordinator.token_manager.schedule_refresh_check()
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # Clean up
        data = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator = data["coordinator"]
        api = data["api"]
        
        # Cancel token refresh task
        coordinator.token_manager.cancel_refresh_task()
        
        # Close API session
        await api.close()
    
    return unload_ok


async def _async_register_services(hass: HomeAssistant):
    """Register integration services."""
    
    async def async_start_manual_watering(call: ServiceCall):
        """Service to start manual watering."""
        entity_id = call.data["entity_id"]
        duration = call.data["duration"]
        
        # Find the coordinator for this entity
        coordinator = None
        for entry_data in hass.data[DOMAIN].values():
            if "coordinator" in entry_data:
                coordinator = entry_data["coordinator"]
                break
        
        if not coordinator:
            raise HomeAssistantError("No Solem coordinator found")
        
        # Parse entity_id to get module and zone info
        # Format: switch.irrigation_[module_name]_zone_[N]
        parts = entity_id.split("_")
        if len(parts) < 4 or not parts[-1].isdigit():
            raise HomeAssistantError("Invalid entity_id format")
        
        zone_index = int(parts[-1]) - 1  # Convert to 0-based
        
        # Find module by matching entity name pattern
        module_id = None
        for mid, module in coordinator.data["modules"].items():
            module_name_normalized = module.name.lower().replace(" ", "_")
            if module_name_normalized in entity_id:
                module_id = mid
                break
        
        if not module_id:
            raise HomeAssistantError("Could not find module for entity")
        
        await coordinator.async_start_manual_watering(module_id, zone_index, duration)

    async def async_stop_watering(call: ServiceCall):
        """Service to stop watering."""
        entity_id = call.data["entity_id"]
        
        # Similar logic to find coordinator and module
        coordinator = None
        for entry_data in hass.data[DOMAIN].values():
            if "coordinator" in entry_data:
                coordinator = entry_data["coordinator"]
                break
        
        if not coordinator:
            raise HomeAssistantError("No Solem coordinator found")
        
        # Find module
        module_id = None
        for mid, module in coordinator.data["modules"].items():
            module_name_normalized = module.name.lower().replace(" ", "_")
            if module_name_normalized in entity_id:
                module_id = mid
                break
        
        if not module_id:
            raise HomeAssistantError("Could not find module for entity")
        
        await coordinator.async_stop_watering(module_id)

    async def async_test_all_valves(call: ServiceCall):
        """Service to test all valves."""
        entity_id = call.data["entity_id"]
        duration = call.data["duration"]
        
        # Similar logic to find coordinator and module
        coordinator = None
        for entry_data in hass.data[DOMAIN].values():
            if "coordinator" in entry_data:
                coordinator = entry_data["coordinator"]
                break
        
        if not coordinator:
            raise HomeAssistantError("No Solem coordinator found")
        
        # Find module
        module_id = None
        for mid, module in coordinator.data["modules"].items():
            module_name_normalized = module.name.lower().replace(" ", "_")
            if module_name_normalized in entity_id:
                module_id = mid
                break
        
        if not module_id:
            raise HomeAssistantError("Could not find module for entity")
        
        await coordinator.async_test_all_valves(module_id, duration)

    async def async_start_program(call: ServiceCall):
        """Service to start a program."""
        entity_id = call.data["entity_id"]
        
        # Similar logic but for programs
        coordinator = None
        for entry_data in hass.data[DOMAIN].values():
            if "coordinator" in entry_data:
                coordinator = entry_data["coordinator"]
                break
        
        if not coordinator:
            raise HomeAssistantError("No Solem coordinator found")
        
        # Parse program entity_id: switch.irrigation_[module_name]_program_[N]
        parts = entity_id.split("_")
        if len(parts) < 4 or not parts[-1].isdigit():
            raise HomeAssistantError("Invalid program entity_id format")
        
        program_index = int(parts[-1])
        
        # Find module
        module_id = None
        for mid, module in coordinator.data["modules"].items():
            module_name_normalized = module.name.lower().replace(" ", "_")
            if module_name_normalized in entity_id:
                module_id = mid
                break
        
        if not module_id:
            raise HomeAssistantError("Could not find module for entity")
        
        await coordinator.async_start_program(module_id, program_index)

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_MANUAL_WATERING,
        async_start_manual_watering,
        schema=START_MANUAL_WATERING_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_WATERING,
        async_stop_watering,
        schema=STOP_WATERING_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_ALL_VALVES,
        async_test_all_valves,
        schema=TEST_ALL_VALVES_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_PROGRAM,
        async_start_program,
        schema=START_PROGRAM_SCHEMA,
    )


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
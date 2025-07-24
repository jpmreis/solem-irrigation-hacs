"""Switch platform for Solem Irrigation integration."""
import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    DEFAULT_MANUAL_DURATION,
    CONF_MANUAL_DURATION,
    ATTR_MODULE_ID,
    ATTR_ZONE_INDEX,
    ATTR_PROGRAM_INDEX,
    ATTR_TIME_REMAINING,
    ATTR_RUNNING_PROGRAM,
    ATTR_RUNNING_STATION,
    ATTR_ZONES_WATERING,
    ATTR_NEXT_RUN_TIME,
    ATTR_SCHEDULE_DESCRIPTION,
    ATTR_ESTIMATED_DURATION,
    ATTR_WATER_BUDGET,
    ATTR_FLOW_RATE,
    ATTR_USE_SENSOR,
    ICON_IRRIGATION,
    ICON_IRRIGATION_OFF,
    ICON_VALVE,
    ICON_PROGRAM,
    ICON_PROGRAM_OFF,
    STATE_IDLE,
    STATE_WATERING,
    STATE_PROGRAM_RUNNING,
    STATE_SENSOR_FAULT,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Solem switch entities from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    
    entities: List[SwitchEntity] = []
    
    # Create entities for each module
    for module_id, module in coordinator.data["modules"].items():
        # Module master switch
        entities.append(SolemModuleSwitch(coordinator, module_id))
        
        # Zone switches
        for zone in module.zones:
            entities.append(SolemZoneSwitch(coordinator, module_id, zone.index))
        
        # Program switches
        for program in module.programs:
            entities.append(SolemProgramSwitch(coordinator, module_id, program.index))
    
    async_add_entities(entities)


class SolemBaseSwitch(CoordinatorEntity, SwitchEntity):
    """Base class for Solem switches."""

    def __init__(self, coordinator, module_id: str):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._module_id = module_id
        self._attr_has_entity_name = True

    @property
    def module(self):
        """Get the module data."""
        return self.coordinator.data["modules"].get(self._module_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        module = self.module
        if not module:
            return None
        
        return DeviceInfo(
            identifiers={(DOMAIN, module.id)},
            name=module.name,
            manufacturer="Solem",
            model=module.type,
            serial_number=module.serial_number,
            hw_version=module.diagnostics.hardware_version if module.diagnostics else None,
            sw_version=module.diagnostics.firmware_version if module.diagnostics else None,
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.module is not None


class SolemModuleSwitch(SolemBaseSwitch):
    """Switch for entire irrigation module."""

    def __init__(self, coordinator, module_id: str):
        """Initialize the module switch."""
        super().__init__(coordinator, module_id)
        self._attr_device_class = SwitchDeviceClass.SWITCH

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_module"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Module"

    @property
    def entity_id(self) -> str:
        """Return entity ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"switch.irrigation_{module_name}"
        return f"switch.irrigation_module_{self._module_id}"

    @property
    def is_on(self) -> bool:
        """Return true if any zone is watering."""
        module = self.module
        return module and module.is_watering

    @property
    def icon(self) -> str:
        """Return the icon."""
        return ICON_IRRIGATION if self.is_on else ICON_IRRIGATION_OFF

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        module = self.module
        if not module:
            return {}

        attrs = {
            ATTR_MODULE_ID: module.id,
            "zones_total": len(module.zones),
            "programs_total": len(module.programs),
        }

        if module.status:
            attrs.update({
                ATTR_TIME_REMAINING: module.status.time_remaining,
                ATTR_RUNNING_PROGRAM: module.status.running_program,
                ATTR_RUNNING_STATION: module.status.running_station,
            })

        # List of currently watering zones
        watering_zones = [
            zone.name for zone in module.zones if zone.is_currently_watering
        ]
        if watering_zones:
            attrs[ATTR_ZONES_WATERING] = watering_zones

        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the module by starting the next scheduled program."""
        module = self.module
        if not module or not module.programs:
            raise HomeAssistantError("No programs available to start")

        # Find the next program to run (first active program)
        active_programs = [p for p in module.programs if p.is_active]
        if not active_programs:
            raise HomeAssistantError("No active programs found")

        # Start the first active program
        program = active_programs[0]
        await self.coordinator.async_start_program(self._module_id, program.index)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the module by stopping all watering."""
        await self.coordinator.async_stop_watering(self._module_id)


class SolemZoneSwitch(SolemBaseSwitch):
    """Switch for individual irrigation zone."""

    def __init__(self, coordinator, module_id: str, zone_index: int):
        """Initialize the zone switch."""
        super().__init__(coordinator, module_id)
        self._zone_index = zone_index
        self._attr_device_class = SwitchDeviceClass.OUTLET

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_zone_{self._zone_index}"

    @property
    def name(self) -> str:
        """Return the name."""
        zone = self.zone
        if zone:
            return zone.name
        return f"Zone {self._zone_index + 1}"

    @property
    def entity_id(self) -> str:
        """Return entity ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"switch.irrigation_{module_name}_zone_{self._zone_index + 1}"
        return f"switch.irrigation_module_{self._module_id}_zone_{self._zone_index + 1}"

    @property
    def zone(self):
        """Get the zone data."""
        module = self.module
        if module and 0 <= self._zone_index < len(module.zones):
            return module.zones[self._zone_index]
        return None

    @property
    def is_on(self) -> bool:
        """Return true if zone is watering."""
        zone = self.zone
        return zone and zone.is_currently_watering

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not super().available:
            return False
        zone = self.zone
        return zone is not None and not zone.has_sensor_fault

    @property
    def icon(self) -> str:
        """Return the icon."""
        return ICON_VALVE

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        zone = self.zone
        module = self.module
        
        if not zone or not module:
            return {}

        attrs = {
            ATTR_MODULE_ID: module.id,
            ATTR_ZONE_INDEX: self._zone_index,
            ATTR_FLOW_RATE: zone.flow_rate,
            ATTR_WATER_BUDGET: zone.water_budget,
            ATTR_USE_SENSOR: zone.use_sensor,
        }

        # Add time remaining if this zone is currently running
        if module.status and module.status.running_station == self._zone_index + 1:
            attrs[ATTR_TIME_REMAINING] = module.status.time_remaining

        if zone.last_watered:
            attrs["last_watered"] = zone.last_watered.isoformat()

        if zone.next_scheduled:
            attrs["next_scheduled"] = zone.next_scheduled.isoformat()

        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the zone with manual watering."""
        # Get manual duration from config
        duration = self.coordinator.config_entry.options.get(
            CONF_MANUAL_DURATION, 
            DEFAULT_MANUAL_DURATION
        )
        
        await self.coordinator.async_start_manual_watering(
            self._module_id, 
            self._zone_index, 
            duration
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the zone by stopping watering."""
        await self.coordinator.async_stop_watering(self._module_id)


class SolemProgramSwitch(SolemBaseSwitch):
    """Switch for irrigation program."""

    def __init__(self, coordinator, module_id: str, program_index: int):
        """Initialize the program switch."""
        super().__init__(coordinator, module_id)
        self._program_index = program_index
        self._attr_device_class = SwitchDeviceClass.SWITCH

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_program_{self._program_index}"

    @property
    def name(self) -> str:
        """Return the name."""
        program = self.program
        if program:
            return f"Program {program.name}"
        return f"Program {self._program_index}"

    @property
    def entity_id(self) -> str:
        """Return entity ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"switch.irrigation_{module_name}_program_{self._program_index}"
        return f"switch.irrigation_module_{self._module_id}_program_{self._program_index}"

    @property
    def program(self):
        """Get the program data."""
        module = self.module
        if module:
            for program in module.programs:
                if program.index == self._program_index:
                    return program
        return None

    @property
    def is_on(self) -> bool:
        """Return true if program is running."""
        program = self.program
        return program and program.is_currently_running

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not super().available:
            return False
        program = self.program
        return program is not None and program.is_active

    @property
    def icon(self) -> str:
        """Return the icon."""
        program = self.program
        if program and program.is_active:
            return ICON_PROGRAM if self.is_on else ICON_PROGRAM
        return ICON_PROGRAM_OFF

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        program = self.program
        module = self.module
        
        if not program or not module:
            return {}

        attrs = {
            ATTR_MODULE_ID: module.id,
            ATTR_PROGRAM_INDEX: self._program_index,
            ATTR_SCHEDULE_DESCRIPTION: program.get_schedule_description(),
            ATTR_ESTIMATED_DURATION: program.estimated_duration,
            ATTR_WATER_BUDGET: program.water_budget,
            "is_active": program.is_active,
            "start_times": program.start_times,
            "week_days": program.week_days,
        }

        if program.next_run_time:
            attrs[ATTR_NEXT_RUN_TIME] = program.next_run_time.isoformat()

        if program.last_run_time:
            attrs["last_run_time"] = program.last_run_time.isoformat()

        # Station durations
        if program.stations_duration:
            station_info = []
            for idx, duration in enumerate(program.stations_duration):
                if duration > 0 and idx < len(module.zones):
                    station_info.append({
                        "zone": module.zones[idx].name,
                        "duration": duration
                    })
            if station_info:
                attrs["stations"] = station_info

        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the program."""
        await self.coordinator.async_start_program(self._module_id, self._program_index)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the program by stopping watering."""
        await self.coordinator.async_stop_watering(self._module_id)
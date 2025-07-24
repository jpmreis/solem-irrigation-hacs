"""Sensor platform for Solem Irrigation integration."""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    ATTR_MODULE_ID,
    ATTR_BATTERY_LEVEL,
    ATTR_SIGNAL_QUALITY,
    ATTR_LAST_COMMUNICATION,
    ATTR_FIRMWARE_VERSION,
    ATTR_SERIAL_NUMBER,
    ATTR_MAC_ADDRESS,
    ATTR_RELAY_SERIAL,
    ATTR_TIME_REMAINING,
    ATTR_RUNNING_PROGRAM,
    ATTR_RUNNING_STATION,
    ICON_BATTERY,
    ICON_BATTERY_LOW,
    ICON_SIGNAL,
    ICON_IRRIGATION,
    STATE_IDLE,
    STATE_WATERING,
    STATE_PROGRAM_RUNNING,
    STATE_MANUAL_WATERING,
    STATE_TESTING,
    UNIT_MINUTES,
    UNIT_PERCENTAGE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Solem sensor entities from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    
    entities: List[SensorEntity] = []
    
    # Create entities for each module
    for module_id, module in coordinator.data["modules"].items():
        # Module sensors
        entities.extend([
            SolemModuleStatusSensor(coordinator, module_id),
            SolemModuleTimeRemainingSensor(coordinator, module_id),
            SolemModuleBatterySensor(coordinator, module_id),
            SolemModuleNextRunSensor(coordinator, module_id),
        ])
        
        # Diagnostic sensors
        if module.diagnostics:
            entities.extend([
                SolemModuleSignalQualitySensor(coordinator, module_id),
                SolemModuleLastCommunicationSensor(coordinator, module_id),
            ])
        
        # Zone sensors
        for zone in module.zones:
            entities.append(SolemZoneStatusSensor(coordinator, module_id, zone.index))
        
        # Program sensors
        for program in module.programs:
            entities.extend([
                SolemProgramNextRunSensor(coordinator, module_id, program.index),
                SolemProgramScheduleSensor(coordinator, module_id, program.index),
            ])
    
    async_add_entities(entities)


class SolemBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Solem sensors."""

    def __init__(self, coordinator, module_id: str):
        """Initialize the sensor."""
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


class SolemModuleStatusSensor(SolemBaseSensor):
    """Sensor for module watering status."""

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_status"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Status"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_status"
        return f"irrigation_module_{self._module_id}_status"

    @property
    def native_value(self) -> str:
        """Return the state."""
        module = self.module
        if not module:
            return STATE_IDLE
        
        if not module.status or not module.status.is_running:
            return STATE_IDLE
        
        # Determine the type of watering based on origin
        if module.status.origin == 1:  # Manual
            if module.status.running_program == 0:
                return STATE_MANUAL_WATERING
            else:
                return STATE_TESTING
        else:
            return STATE_PROGRAM_RUNNING

    @property
    def icon(self) -> str:
        """Return the icon."""
        return ICON_IRRIGATION

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        module = self.module
        if not module:
            return {}

        attrs = {ATTR_MODULE_ID: module.id}
        
        if module.status:
            attrs.update({
                ATTR_RUNNING_PROGRAM: module.status.running_program,
                ATTR_RUNNING_STATION: module.status.running_station,
                "origin": module.status.origin,
                "state": module.status.state,
                "rain_delay": module.status.rain_delay,
                "sensor_active": module.status.sensor_active,
            })

        return attrs


class SolemModuleTimeRemainingSensor(SolemBaseSensor):
    """Sensor for remaining watering time."""

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_time_remaining"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Time Remaining"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_time_remaining"
        return f"irrigation_module_{self._module_id}_time_remaining"

    @property
    def native_value(self) -> Optional[int]:
        """Return the state in minutes."""
        module = self.module
        if not module or not module.status or not module.status.is_running:
            return 0
        
        # Parse time remaining (format: "MM:SS")
        time_str = module.status.time_remaining
        if not time_str or time_str == "00:00":
            return 0
        
        try:
            parts = time_str.split(":")
            if len(parts) == 2:
                minutes = int(parts[0])
                seconds = int(parts[1])
                return minutes + (1 if seconds > 0 else 0)  # Round up
        except (ValueError, IndexError):
            pass
        
        return 0

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit."""
        return UnitOfTime.MINUTES

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return device class."""
        return SensorDeviceClass.DURATION

    @property
    def state_class(self) -> SensorStateClass:
        """Return state class."""
        return SensorStateClass.MEASUREMENT

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        module = self.module
        if not module or not module.status:
            return {}

        return {
            ATTR_MODULE_ID: module.id,
            "time_remaining_formatted": module.status.time_remaining,
        }


class SolemModuleBatterySensor(SolemBaseSensor):
    """Sensor for module battery level."""

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_battery"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Battery"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_battery"
        return f"irrigation_module_{self._module_id}_battery"

    @property
    def native_value(self) -> Optional[int]:
        """Return the state."""
        module = self.module
        if module and module.battery:
            return module.battery.percentage
        return None

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit."""
        return PERCENTAGE

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return device class."""
        return SensorDeviceClass.BATTERY

    @property
    def state_class(self) -> SensorStateClass:
        """Return state class."""
        return SensorStateClass.MEASUREMENT

    @property
    def entity_category(self) -> EntityCategory:
        """Return entity category."""
        return EntityCategory.DIAGNOSTIC

    @property
    def icon(self) -> str:
        """Return the icon."""
        module = self.module
        if module and module.battery and module.battery.low:
            return ICON_BATTERY_LOW
        return ICON_BATTERY

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        module = self.module
        if not module or not module.battery:
            return {}

        attrs = {
            ATTR_MODULE_ID: module.id,
            ATTR_BATTERY_LEVEL: module.battery.level,
            "battery_low": module.battery.low,
        }
        
        if module.battery.voltage:
            attrs["battery_voltage"] = module.battery.voltage

        return attrs


class SolemModuleNextRunSensor(SolemBaseSensor):
    """Sensor for next scheduled watering time."""

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_next_run"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Next Run"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_next_run"
        return f"irrigation_module_{self._module_id}_next_run"

    @property
    def native_value(self) -> Optional[datetime]:
        """Return the state."""
        module = self.module
        if module:
            return module.next_scheduled_watering
        return None

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return device class."""
        return SensorDeviceClass.TIMESTAMP

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        module = self.module
        if not module:
            return {}

        attrs = {ATTR_MODULE_ID: module.id}
        
        # Find which program is next
        next_time = module.next_scheduled_watering
        if next_time:
            for program in module.programs:
                if program.next_run_time == next_time:
                    attrs["next_program"] = program.name
                    attrs["next_program_index"] = program.index
                    break

        return attrs


class SolemModuleSignalQualitySensor(SolemBaseSensor):
    """Sensor for module signal quality."""

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_signal_quality"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Signal Quality"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_signal_quality"
        return f"irrigation_module_{self._module_id}_signal_quality"

    @property
    def native_value(self) -> Optional[int]:
        """Return the state."""
        module = self.module
        if module and module.diagnostics:
            return module.diagnostics.signal_quality
        return None

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit."""
        return PERCENTAGE

    @property
    def state_class(self) -> SensorStateClass:
        """Return state class."""
        return SensorStateClass.MEASUREMENT

    @property
    def entity_category(self) -> EntityCategory:
        """Return entity category."""
        return EntityCategory.DIAGNOSTIC

    @property
    def icon(self) -> str:
        """Return the icon."""
        return ICON_SIGNAL

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        module = self.module
        if not module:
            return {}

        return {ATTR_MODULE_ID: module.id}


class SolemModuleLastCommunicationSensor(SolemBaseSensor):
    """Sensor for last communication time."""

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_last_communication"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Last Communication"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_last_communication"
        return f"irrigation_module_{self._module_id}_last_communication"

    @property
    def native_value(self) -> Optional[datetime]:
        """Return the state."""
        module = self.module
        if module and module.diagnostics:
            return module.diagnostics.last_communication
        return None

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return device class."""
        return SensorDeviceClass.TIMESTAMP

    @property
    def entity_category(self) -> EntityCategory:
        """Return entity category."""
        return EntityCategory.DIAGNOSTIC


class SolemZoneStatusSensor(SolemBaseSensor):
    """Sensor for individual zone status."""

    def __init__(self, coordinator, module_id: str, zone_index: int):
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._zone_index = zone_index

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_zone_{self._zone_index}_status"

    @property
    def name(self) -> str:
        """Return the name."""
        zone = self.zone
        if zone:
            return f"{zone.name} Status"
        return f"Zone {self._zone_index + 1} Status"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_zone_{self._zone_index + 1}_status"
        return f"irrigation_module_{self._module_id}_zone_{self._zone_index + 1}_status"

    @property
    def zone(self):
        """Get the zone data."""
        module = self.module
        if module and 0 <= self._zone_index < len(module.zones):
            return module.zones[self._zone_index]
        return None

    @property
    def native_value(self) -> str:
        """Return the state."""
        zone = self.zone
        if not zone:
            return STATE_IDLE
        
        if zone.has_sensor_fault:
            return "sensor_fault"
        elif zone.is_currently_watering:
            return STATE_WATERING
        else:
            return STATE_IDLE

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        zone = self.zone
        module = self.module
        
        if not zone or not module:
            return {}

        attrs = {
            ATTR_MODULE_ID: module.id,
            "zone_index": self._zone_index,
            "flow_rate": zone.flow_rate,
            "water_budget": zone.water_budget,
            "use_sensor": zone.use_sensor,
        }

        if zone.last_watered:
            attrs["last_watered"] = zone.last_watered.isoformat()

        if zone.next_scheduled:
            attrs["next_scheduled"] = zone.next_scheduled.isoformat()

        return attrs


class SolemProgramNextRunSensor(SolemBaseSensor):
    """Sensor for program next run time."""

    def __init__(self, coordinator, module_id: str, program_index: int):
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._program_index = program_index

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_program_{self._program_index}_next_run"

    @property
    def name(self) -> str:
        """Return the name."""
        program = self.program
        if program:
            return f"{program.name} Next Run"
        return f"Program {self._program_index} Next Run"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_program_{self._program_index}_next_run"
        return f"irrigation_module_{self._module_id}_program_{self._program_index}_next_run"

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
    def native_value(self) -> Optional[datetime]:
        """Return the state."""
        program = self.program
        if program:
            return program.next_run_time
        return None

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return device class."""
        return SensorDeviceClass.TIMESTAMP

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not super().available:
            return False
        program = self.program
        return program is not None and program.is_active

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        program = self.program
        module = self.module
        
        if not program or not module:
            return {}

        return {
            ATTR_MODULE_ID: module.id,
            "program_index": self._program_index,
            "estimated_duration": program.estimated_duration,
            "is_active": program.is_active,
        }


class SolemProgramScheduleSensor(SolemBaseSensor):
    """Sensor for program schedule description."""

    def __init__(self, coordinator, module_id: str, program_index: int):
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._program_index = program_index

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_program_{self._program_index}_schedule"

    @property
    def name(self) -> str:
        """Return the name."""
        program = self.program
        if program:
            return f"{program.name} Schedule"
        return f"Program {self._program_index} Schedule"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_program_{self._program_index}_schedule"
        return f"irrigation_module_{self._module_id}_program_{self._program_index}_schedule"

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
    def native_value(self) -> Optional[str]:
        """Return the state."""
        program = self.program
        if program:
            return program.get_schedule_description()
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not super().available:
            return False
        program = self.program
        return program is not None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        program = self.program
        module = self.module
        
        if not program or not module:
            return {}

        attrs = {
            ATTR_MODULE_ID: module.id,
            "program_index": self._program_index,
            "start_times": program.start_times,
            "week_days": program.week_days,
            "water_budget": program.water_budget,
            "is_active": program.is_active,
            "estimated_duration": program.estimated_duration,
        }

        # Station information
        if program.stations_duration:
            stations = []
            for idx, duration in enumerate(program.stations_duration):
                if duration > 0 and idx < len(module.zones):
                    stations.append({
                        "zone": module.zones[idx].name,
                        "duration": duration
                    })
            if stations:
                attrs["stations"] = stations

        return attrs
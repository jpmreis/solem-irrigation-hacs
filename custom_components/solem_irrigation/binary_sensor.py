"""Binary sensor platform for Solem Irrigation integration."""
import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    ATTR_MODULE_ID,
    ATTR_ZONE_INDEX,
    ATTR_PROGRAM_INDEX,
    ICON_IRRIGATION,
    ICON_WATER_DROP,
    ICON_PROGRAM,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Solem binary sensor entities from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    
    entities: List[BinarySensorEntity] = []
    
    # Create entities for each module
    for module_id, module in coordinator.data["modules"].items():
        # Module binary sensors
        entities.extend([
            SolemModuleOnlineSensor(coordinator, module_id),
            SolemModuleWateringSensor(coordinator, module_id),
            SolemModuleBatteryLowSensor(coordinator, module_id),
        ])
        
        # Zone binary sensors
        for zone in module.zones:
            entities.extend([
                SolemZoneWateringSensor(coordinator, module_id, zone.index),
                SolemZoneSensorFaultSensor(coordinator, module_id, zone.index),
            ])
        
        # Program binary sensors
        for program in module.programs:
            entities.extend([
                SolemProgramActiveSensor(coordinator, module_id, program.index),
                SolemProgramRunningSensor(coordinator, module_id, program.index),
            ])
    
    async_add_entities(entities)


class SolemBaseBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Base class for Solem binary sensors."""

    def __init__(self, coordinator, module_id: str):
        """Initialize the binary sensor."""
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


class SolemModuleOnlineSensor(SolemBaseBinarySensor):
    """Binary sensor for module online status."""

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_online"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Online"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_online"
        return f"irrigation_module_{self._module_id}_online"

    @property
    def is_on(self) -> bool:
        """Return true if module is online."""
        module = self.module
        return module and module.is_online

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        """Return device class."""
        return BinarySensorDeviceClass.CONNECTIVITY

    @property
    def entity_category(self) -> EntityCategory:
        """Return entity category."""
        return EntityCategory.DIAGNOSTIC

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        module = self.module
        if not module:
            return {}

        attrs = {ATTR_MODULE_ID: module.id}
        
        if module.last_seen:
            attrs["last_seen"] = module.last_seen.isoformat()
        
        if module.diagnostics and module.diagnostics.last_communication:
            attrs["last_communication"] = module.diagnostics.last_communication.isoformat()

        return attrs


class SolemModuleWateringSensor(SolemBaseBinarySensor):
    """Binary sensor for module watering status."""

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_watering"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Watering"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_watering"
        return f"irrigation_module_{self._module_id}_watering"

    @property
    def is_on(self) -> bool:
        """Return true if module is watering."""
        module = self.module
        return module and module.is_watering

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
                "running_program": module.status.running_program,
                "running_station": module.status.running_station,
                "time_remaining": module.status.time_remaining,
            })

        # List currently watering zones
        watering_zones = [
            zone.name for zone in module.zones if zone.is_currently_watering
        ]
        if watering_zones:
            attrs["watering_zones"] = watering_zones

        return attrs


class SolemModuleBatteryLowSensor(SolemBaseBinarySensor):
    """Binary sensor for module low battery status."""

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_battery_low"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Battery Low"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_battery_low"
        return f"irrigation_module_{self._module_id}_battery_low"

    @property
    def is_on(self) -> bool:
        """Return true if battery is low."""
        module = self.module
        return module and module.battery and module.battery.low

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        """Return device class."""
        return BinarySensorDeviceClass.BATTERY

    @property
    def entity_category(self) -> EntityCategory:
        """Return entity category."""
        return EntityCategory.DIAGNOSTIC

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        module = self.module
        if not module or not module.battery:
            return {}

        return {
            ATTR_MODULE_ID: module.id,
            "battery_level": module.battery.level,
            "battery_percentage": module.battery.percentage,
            "battery_voltage": module.battery.voltage,
        }


class SolemZoneWateringSensor(SolemBaseBinarySensor):
    """Binary sensor for zone watering status."""

    def __init__(self, coordinator, module_id: str, zone_index: int):
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._zone_index = zone_index

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_zone_{self._zone_index}_watering"

    @property
    def name(self) -> str:
        """Return the name."""
        zone = self.zone
        if zone:
            return f"{zone.name} Watering"
        return f"Zone {self._zone_index + 1} Watering"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_zone_{self._zone_index + 1}_watering"
        return f"irrigation_module_{self._module_id}_zone_{self._zone_index + 1}_watering"

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
    def icon(self) -> str:
        """Return the icon."""
        return ICON_WATER_DROP

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
        }

        # Add time remaining if this zone is currently running
        if module.status and module.status.running_station == self._zone_index + 1:
            attrs["time_remaining"] = module.status.time_remaining

        return attrs


class SolemZoneSensorFaultSensor(SolemBaseBinarySensor):
    """Binary sensor for zone sensor fault status."""

    def __init__(self, coordinator, module_id: str, zone_index: int):
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._zone_index = zone_index

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_zone_{self._zone_index}_sensor_fault"

    @property
    def name(self) -> str:
        """Return the name."""
        zone = self.zone
        if zone:
            return f"{zone.name} Sensor Fault"
        return f"Zone {self._zone_index + 1} Sensor Fault"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_zone_{self._zone_index + 1}_sensor_fault"
        return f"irrigation_module_{self._module_id}_zone_{self._zone_index + 1}_sensor_fault"

    @property
    def zone(self):
        """Get the zone data."""
        module = self.module
        if module and 0 <= self._zone_index < len(module.zones):
            return module.zones[self._zone_index]
        return None

    @property
    def is_on(self) -> bool:
        """Return true if zone has sensor fault."""
        zone = self.zone
        return zone and zone.has_sensor_fault

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        """Return device class."""
        return BinarySensorDeviceClass.PROBLEM

    @property
    def entity_category(self) -> EntityCategory:
        """Return entity category."""
        return EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not super().available:
            return False
        zone = self.zone
        return zone is not None and zone.use_sensor

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        zone = self.zone
        module = self.module
        
        if not zone or not module:
            return {}

        return {
            ATTR_MODULE_ID: module.id,
            ATTR_ZONE_INDEX: self._zone_index,
            "use_sensor": zone.use_sensor,
        }


class SolemProgramActiveSensor(SolemBaseBinarySensor):
    """Binary sensor for program active status."""

    def __init__(self, coordinator, module_id: str, program_index: int):
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._program_index = program_index

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_program_{self._program_index}_active"

    @property
    def name(self) -> str:
        """Return the name."""
        program = self.program
        if program:
            return f"{program.name} Active"
        return f"Program {self._program_index} Active"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_program_{self._program_index}_active"
        return f"irrigation_module_{self._module_id}_program_{self._program_index}_active"

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
        """Return true if program is active."""
        program = self.program
        return program and program.is_active

    @property
    def icon(self) -> str:
        """Return the icon."""
        return ICON_PROGRAM

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
            "schedule_description": program.get_schedule_description(),
        }

        if program.next_run_time:
            attrs["next_run_time"] = program.next_run_time.isoformat()

        return attrs


class SolemProgramRunningSensor(SolemBaseBinarySensor):
    """Binary sensor for program running status."""

    def __init__(self, coordinator, module_id: str, program_index: int):
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._program_index = program_index

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_program_{self._program_index}_running"

    @property
    def name(self) -> str:
        """Return the name."""
        program = self.program
        if program:
            return f"{program.name} Running"
        return f"Program {self._program_index} Running"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_program_{self._program_index}_running"
        return f"irrigation_module_{self._module_id}_program_{self._program_index}_running"

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
    def icon(self) -> str:
        """Return the icon."""
        return ICON_PROGRAM

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
        }

        # Add time remaining if program is running
        if program.is_currently_running and module.status:
            attrs["time_remaining"] = module.status.time_remaining

        return attrs
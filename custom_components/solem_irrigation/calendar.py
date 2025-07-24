"""Calendar platform for Solem Irrigation integration."""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util, slugify

from .const import (
    DOMAIN,
    ATTR_MODULE_ID,
    CALENDAR_COLORS,
    ICON_CALENDAR,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Solem calendar entities from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    
    entities: List[CalendarEntity] = []
    
    # Create only system-wide calendar
    entities.append(SolemSystemCalendar(coordinator))
    
    async_add_entities(entities)


class SolemBaseCalendar(CoordinatorEntity, CalendarEntity):
    """Base class for Solem calendar entities."""

    def __init__(self, coordinator):
        """Initialize the calendar."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._events_cache: List[CalendarEvent] = []
        self._cache_expires: Optional[datetime] = None

    @property
    def icon(self) -> str:
        """Return the icon."""
        return ICON_CALENDAR

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    def _generate_events(self, start_date: datetime, end_date: datetime) -> List[CalendarEvent]:
        """Generate calendar events for the date range."""
        # Check cache first
        now = dt_util.utcnow()
        if (self._cache_expires and now < self._cache_expires and 
            self._events_cache and len(self._events_cache) > 0):
            # Filter cached events to the requested range
            return [
                event for event in self._events_cache
                if event.start_datetime_local <= end_date and event.end_datetime_local >= start_date
            ]
        
        # Generate new events
        events = []
        modules = self._get_modules_for_calendar()
        
        for module in modules:
            if not module.programs:
                continue
            
            for program in module.programs:
                if not program.is_active:
                    continue
                
                program_events = self._generate_program_events(
                    module, program, start_date, end_date
                )
                events.extend(program_events)
        
        # Sort events by start time
        events.sort(key=lambda e: e.start_datetime_local)
        
        # Cache events for 15 minutes
        self._events_cache = events
        self._cache_expires = now + timedelta(minutes=15)
        
        return events

    def _get_modules_for_calendar(self) -> List:
        """Get modules that should be included in this calendar."""
        raise NotImplementedError

    def _generate_program_events(
        self, module, program, start_date: datetime, end_date: datetime
    ) -> List[CalendarEvent]:
        """Generate events for a specific program."""
        events = []
        
        # Parse program schedule
        active_start_times = [t for t in program.start_times if t >= 0]
        if not active_start_times:
            return events
        
        # Get day names for week_days bitmask
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        # Generate events for each day in the range
        current_date = start_date.date()
        end_date_date = end_date.date()
        
        while current_date <= end_date_date:
            day_of_week = current_date.weekday()  # 0=Monday, 6=Sunday
            
            # Check if program runs on this day
            if not (program.week_days & (1 << day_of_week)):
                current_date += timedelta(days=1)
                continue
            
            # Create events for each start time
            for start_time_minutes in active_start_times:
                start_hour = start_time_minutes // 60
                start_minute = start_time_minutes % 60
                
                event_start = datetime.combine(
                    current_date,
                    datetime.min.time().replace(hour=start_hour, minute=start_minute)
                )
                event_start = dt_util.as_local(event_start)
                
                # Calculate end time (estimated_duration is in seconds)
                event_end = event_start + timedelta(seconds=program.estimated_duration)
                
                # Skip if event is completely outside our range
                if event_end < start_date or event_start > end_date:
                    continue
                
                # Create event
                event = CalendarEvent(
                    start=event_start,
                    end=event_end,
                    summary=self._get_event_title(module, program),
                    description=self._get_event_description(module, program),
                    location=self._get_event_location(module, program),
                )
                
                events.append(event)
            
            current_date += timedelta(days=1)
        
        return events

    def _get_event_title(self, module, program) -> str:
        """Get event title."""
        return f"{module.name} - {program.name}"

    def _get_event_description(self, module, program) -> str:
        """Get event description."""
        lines = [
            f"Module: {module.name}",
            f"Program: {program.name} (Program {program.index})",
            f"Estimated Duration: {program.estimated_duration // 60} min {program.estimated_duration % 60} sec",
            f"Water Budget: {program.water_budget}%",
        ]
        
        # Add zone information
        if program.stations_duration:
            lines.append("Zones:")
            for idx, duration in enumerate(program.stations_duration):
                if duration > 0 and idx < len(module.zones):
                    lines.append(f"  • {module.zones[idx].name}: {duration // 60} min {duration % 60} sec")
        
        return "\n".join(lines)

    def _get_event_location(self, module, program) -> str:
        """Get event location."""
        zones = []
        if program.stations_duration:
            for idx, duration in enumerate(program.stations_duration):
                if duration > 0 and idx < len(module.zones):
                    zones.append(module.zones[idx].name)
        
        return ", ".join(zones) if zones else module.name

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> List[CalendarEvent]:
        """Return calendar events within a datetime range."""
        return self._generate_events(start_date, end_date)

    @property
    def event(self) -> Optional[CalendarEvent]:
        """Return the next upcoming event."""
        now = dt_util.now()
        # Look for events in the next 7 days
        future_date = now + timedelta(days=7)
        
        events = self._generate_events(now, future_date)
        
        # Find the next event that hasn't started yet or is currently running
        for event in events:
            if event.end_datetime_local > now:
                return event
        
        return None


class SolemModuleCalendar(SolemBaseCalendar):
    """Calendar entity for a specific irrigation module."""

    def __init__(self, coordinator, module_id: str):
        """Initialize the module calendar."""
        super().__init__(coordinator)
        self._module_id = module_id

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self._module_id}_schedule"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Schedule"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        module = self.module
        if module:
            module_name = slugify(module.name.lower())
            return f"irrigation_{module_name}_schedule"
        return f"irrigation_module_{self._module_id}_schedule"

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
        return super().available and self.module is not None

    def _get_modules_for_calendar(self) -> List:
        """Get modules that should be included in this calendar."""
        module = self.module
        return [module] if module else []

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        module = self.module
        if not module:
            return {}

        attrs = {ATTR_MODULE_ID: module.id}
        
        # Count active programs
        active_programs = sum(1 for p in module.programs if p.is_active)
        attrs["active_programs"] = active_programs
        
        # Next scheduled run
        next_run = module.next_scheduled_watering
        if next_run:
            attrs["next_run"] = next_run.isoformat()
        
        # Total weekly runtime estimate
        weekly_runtime = 0
        for program in module.programs:
            if program.is_active:
                # Count how many days per week this program runs
                days_per_week = bin(program.week_days).count('1')
                # Count how many start times per day
                start_times_per_day = len([t for t in program.start_times if t >= 0])
                # Calculate total weekly seconds
                weekly_runtime += program.estimated_duration * days_per_week * start_times_per_day
        
        attrs["total_weekly_runtime"] = f"{weekly_runtime / 3600:.1f} hours"
        
        return attrs


class SolemSystemCalendar(SolemBaseCalendar):
    """Calendar entity for the entire irrigation system."""

    def __init__(self, coordinator):
        """Initialize the system calendar."""
        super().__init__(coordinator)

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return "solem_irrigation_system_schedule"

    @property
    def name(self) -> str:
        """Return the name."""
        return "Irrigation System Schedule"

    @property
    def suggested_object_id(self) -> str:
        """Return suggested object ID."""
        return "irrigation_system_schedule"

    def _get_modules_for_calendar(self) -> List:
        """Get modules that should be included in this calendar."""
        return list(self.coordinator.data["modules"].values())

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return extra state attributes."""
        modules = self.coordinator.data["modules"]
        
        attrs = {
            "total_modules": len(modules),
            "online_modules": sum(1 for m in modules.values() if m.is_online),
            "watering_modules": sum(1 for m in modules.values() if m.is_watering),
        }
        
        # Total active programs across all modules
        total_active_programs = 0
        total_zones = 0
        
        for module in modules.values():
            total_active_programs += sum(1 for p in module.programs if p.is_active)
            total_zones += len(module.zones)
        
        attrs["total_active_programs"] = total_active_programs
        attrs["total_zones"] = total_zones
        
        # Next system-wide watering
        next_runs = []
        for module in modules.values():
            if module.next_scheduled_watering:
                next_runs.append(module.next_scheduled_watering)
        
        if next_runs:
            attrs["next_system_run"] = min(next_runs).isoformat()
        
        return attrs

    def _get_event_title(self, module, program) -> str:
        """Get event title with module name for system calendar."""
        return f"{module.name} - {program.name}"
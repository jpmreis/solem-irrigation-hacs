"""Constants for the Solem Irrigation integration."""

DOMAIN = "solem_irrigation"

# Configuration keys
CONF_FAST_SCAN_INTERVAL = "fast_scan_interval"
CONF_FULL_REFRESH_INTERVAL = "full_refresh_interval"
CONF_MANUAL_DURATION = "manual_duration"

# Default values
DEFAULT_SCAN_INTERVAL = 300  # 5 minutes
DEFAULT_FAST_SCAN_INTERVAL = 45  # 45 seconds when watering
DEFAULT_FULL_REFRESH_INTERVAL = 1800  # 30 minutes
DEFAULT_MANUAL_DURATION = 10  # 10 minutes
DEFAULT_TEST_DURATION = 2  # 2 minutes

# Services
SERVICE_START_MANUAL_WATERING = "start_manual_watering"
SERVICE_STOP_WATERING = "stop_watering"
SERVICE_TEST_ALL_VALVES = "test_all_valves"
SERVICE_START_PROGRAM = "start_program"

# Entity attributes
ATTR_MODULE_ID = "module_id"
ATTR_ZONE_INDEX = "zone_index"
ATTR_PROGRAM_INDEX = "program_index"
ATTR_BATTERY_LEVEL = "battery_level"
ATTR_BATTERY_PERCENTAGE = "battery_percentage"
ATTR_SIGNAL_QUALITY = "signal_quality"
ATTR_LAST_COMMUNICATION = "last_communication"
ATTR_FIRMWARE_VERSION = "firmware_version"
ATTR_SERIAL_NUMBER = "serial_number"
ATTR_MAC_ADDRESS = "mac_address"
ATTR_RELAY_SERIAL = "relay_serial"
ATTR_IS_ONLINE = "is_online"
ATTR_TIME_REMAINING = "time_remaining"
ATTR_RUNNING_PROGRAM = "running_program"
ATTR_RUNNING_STATION = "running_station"
ATTR_NEXT_RUN_TIME = "next_run_time"
ATTR_LAST_RUN_TIME = "last_run_time"
ATTR_SCHEDULE_DESCRIPTION = "schedule_description"
ATTR_ESTIMATED_DURATION = "estimated_duration"
ATTR_WATER_BUDGET = "water_budget"
ATTR_FLOW_RATE = "flow_rate"
ATTR_USE_SENSOR = "use_sensor"
ATTR_ZONES_WATERING = "zones_watering"
ATTR_ACTIVE_PROGRAMS = "active_programs"

# Icons
ICON_IRRIGATION = "mdi:sprinkler"
ICON_IRRIGATION_OFF = "mdi:sprinkler-off"
ICON_WATER_DROP = "mdi:water"
ICON_WATER_OFF = "mdi:water-off"
ICON_BATTERY = "mdi:battery"
ICON_BATTERY_LOW = "mdi:battery-low"
ICON_SIGNAL = "mdi:signal"
ICON_CALENDAR = "mdi:calendar-clock"
ICON_PROGRAM = "mdi:play-circle"
ICON_PROGRAM_OFF = "mdi:stop-circle"
ICON_VALVE = "mdi:pipe-valve"
ICON_MODULE = "mdi:irrigation"

# Device classes
DEVICE_CLASS_IRRIGATION = "irrigation"

# Unit of measurement
UNIT_MINUTES = "min"
UNIT_PERCENTAGE = "%"
UNIT_VOLTS = "V"
UNIT_LPH = "L/h"

# States
STATE_IDLE = "idle"
STATE_WATERING = "watering"
STATE_TESTING = "testing"
STATE_PROGRAM_RUNNING = "program_running"
STATE_MANUAL_WATERING = "manual_watering"
STATE_SENSOR_FAULT = "sensor_fault"
STATE_OFFLINE = "offline"

# Calendar colors
CALENDAR_COLORS = {
    0: "#1f77b4",  # Blue
    1: "#ff7f0e",  # Orange  
    2: "#2ca02c",  # Green
    3: "#d62728",  # Red
    4: "#9467bd",  # Purple
    5: "#8c564b",  # Brown
    6: "#e377c2",  # Pink
    7: "#7f7f7f",  # Gray
    8: "#bcbd22",  # Olive
    9: "#17becf",  # Cyan
}

# Error messages
ERROR_AUTH_FAILED = "Authentication failed"
ERROR_API_ERROR = "API communication error"
ERROR_ZONE_NOT_AVAILABLE = "Zone not available"
ERROR_MODULE_NOT_FOUND = "Module not found"
ERROR_PROGRAM_NOT_FOUND = "Program not found"
ERROR_INVALID_DURATION = "Invalid duration"
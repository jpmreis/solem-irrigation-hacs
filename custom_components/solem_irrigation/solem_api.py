"""
Enhanced Solem Irrigation API Library

A Python library to interact with Solem irrigation systems API.
Supports authentication, module management, and comprehensive watering controls.
Enhanced for Home Assistant integration.
"""

import asyncio
import aiohttp
import base64
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from enum import Enum

_LOGGER = logging.getLogger(__name__)

class SolemError(Exception):
    """Base exception for Solem API errors."""
    pass

class AuthenticationError(SolemError):
    """Authentication related errors."""
    pass

class APIError(SolemError):
    """API related errors."""
    pass

class ZoneNotAvailableError(SolemError):
    """Zone is not available (sensor fault, etc.)."""
    pass

class ModuleType(Enum):
    """Module types based on the API response."""
    WATERING = "watering"
    LIGHTING = "lighting"
    POOL = "pool"
    AGRICULTURAL = "agricultural"
    UNKNOWN = "unknown"

@dataclass
class Battery:
    """Battery information for a module."""
    level: int  # 1-5 scale
    voltage: Optional[int] = None
    low: bool = False
    
    @property
    def percentage(self) -> int:
        """Convert 1-5 scale to percentage."""
        return min(100, max(0, (self.level - 1) * 25))

@dataclass
class WateringStatus:
    """Current watering status."""
    is_running: bool
    running_program: int
    running_station: int
    time_remaining: str
    state: int
    origin: int
    rain_delay: int = 0
    sensor_active: bool = False

@dataclass
class WateringProgram:
    """Watering program information."""
    id: str
    name: str
    index: int
    start_times: List[int]
    stations_duration: List[int]
    week_days: int
    water_budget: int
    is_active: bool
    is_currently_running: bool = False
    next_run_time: Optional[datetime] = None
    last_run_time: Optional[datetime] = None
    estimated_duration: int = 0  # Total program duration in minutes
    
    def __post_init__(self):
        """Calculate estimated duration and next run time after initialization."""
        self.estimated_duration = sum(duration for duration in self.stations_duration if duration > 0)
        self._calculate_next_run_time()
    
    def _calculate_next_run_time(self):
        """Calculate the next scheduled run time for this program."""
        if not self.is_active or not any(t >= 0 for t in self.start_times):
            return
        
        now = datetime.now()
        active_start_times = [t for t in self.start_times if t >= 0]
        
        # Find next occurrence
        for days_ahead in range(8):  # Check next 7 days
            check_date = now + timedelta(days=days_ahead)
            day_of_week = check_date.weekday()  # 0=Monday, 6=Sunday
            
            # Check if program runs on this day (bit mask)
            if not (self.week_days & (1 << day_of_week)):
                continue
            
            for start_time_minutes in active_start_times:
                start_hour = start_time_minutes // 60
                start_minute = start_time_minutes % 60
                
                scheduled_time = check_date.replace(
                    hour=start_hour, 
                    minute=start_minute, 
                    second=0, 
                    microsecond=0
                )
                
                # If it's today, make sure the time hasn't passed
                if days_ahead == 0 and scheduled_time <= now:
                    continue
                
                if self.next_run_time is None or scheduled_time < self.next_run_time:
                    self.next_run_time = scheduled_time
    
    def get_schedule_description(self) -> str:
        """Get a human-readable schedule description."""
        days = []
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        
        for i, day in enumerate(day_names):
            if self.week_days & (1 << i):
                days.append(day)
        
        times = []
        for start_time in self.start_times:
            if start_time >= 0:
                hours = start_time // 60
                minutes = start_time % 60
                times.append(f"{hours:02d}:{minutes:02d}")
        
        days_str = ", ".join(days) if days else "Never"
        times_str = ", ".join(times) if times else "No times"
        
        return f"{days_str} at {times_str}"

@dataclass
class WateringZone:
    """Watering zone (output) information."""
    id: str
    name: str
    index: int
    use_sensor: bool
    flow_rate: int
    water_budget: int
    is_currently_watering: bool = False
    last_watered: Optional[datetime] = None
    next_scheduled: Optional[datetime] = None
    has_sensor_fault: bool = False

@dataclass
class ModuleDiagnostics:
    """Diagnostic information for a module."""
    signal_quality: Optional[int] = None
    last_communication: Optional[datetime] = None
    has_sensor_fault: bool = False
    has_communication_fault: bool = False
    firmware_version: Optional[str] = None
    hardware_version: Optional[str] = None
    battery_voltage: Optional[int] = None

@dataclass
class WateringModule:
    """A watering module with its zones and programs."""
    id: str
    name: str
    serial_number: str
    mac_address: str
    type: str
    battery: Battery
    is_online: bool
    zones: List[WateringZone]
    programs: List[WateringProgram]
    status: Optional[WateringStatus] = None
    last_seen: Optional[datetime] = None
    relay_id: Optional[str] = None
    relay_serial: Optional[str] = None
    diagnostics: Optional[ModuleDiagnostics] = None
    
    @property
    def module_type(self) -> ModuleType:
        """Determine module type based on type string."""
        if "watering" in self.type.lower() or "ip-fl" in self.type.lower():
            return ModuleType.WATERING
        elif "lighting" in self.type.lower():
            return ModuleType.LIGHTING
        elif "pool" in self.type.lower():
            return ModuleType.POOL
        elif "agricultural" in self.type.lower():
            return ModuleType.AGRICULTURAL
        else:
            return ModuleType.UNKNOWN
    
    @property
    def mac_suffix(self) -> str:
        """Get the last 6 characters of MAC address for API calls."""
        if self.mac_address:
            return self.mac_address.replace(":", "").upper()[-6:]
        return ""
    
    @property
    def is_watering(self) -> bool:
        """Check if any zone is currently watering."""
        return self.status and self.status.is_running
    
    @property
    def next_scheduled_watering(self) -> Optional[datetime]:
        """Get the next scheduled watering time across all programs."""
        next_times = [p.next_run_time for p in self.programs if p.next_run_time is not None]
        return min(next_times) if next_times else None

class SolemAPI:
    """Main API client for Solem irrigation systems."""
    
    def __init__(self, base_url: str = "https://mysolem.com"):
        """Initialize the API client."""
        self.base_url = base_url.rstrip('/')
        self._session: Optional[aiohttp.ClientSession] = None
        self._app_token: Optional[str] = None
        self._user_token: Optional[str] = None
        self._user_id: Optional[str] = None
        self._modules: Dict[str, WateringModule] = {}
        self._relay_modules: Dict[str, Dict[str, str]] = {}  # relay_id -> {serial, mac}
        
        # OAuth credentials from the APK
        self._client_id = "56d93a89fd05e0a429d737c4"
        self._client_secret = "GmnJqatT96ppmJ"
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def _ensure_session(self):
        """Ensure we have an active aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
    
    async def close(self):
        """Close the API session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _get_auth_header(self) -> str:
        """Get the basic auth header for OAuth."""
        credentials = f"{self._client_id}:{self._client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded_credentials}"
    
    def _get_headers(self) -> Dict[str, str]:
        """Get standard headers for API requests."""
        return {
            "Accept": "version=2.9",
            "Content-Type": "application/json",
            "User-Agent": "SolemApp/1.0 PythonClient",
            "Cache-Control": "no-cache, no-transform"
        }
    
    def _parse_datetime(self, date_string: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string to datetime object."""
        if not date_string:
            return None
        try:
            # Handle various ISO formats
            if date_string.endswith('Z'):
                date_string = date_string[:-1] + '+00:00'
            return datetime.fromisoformat(date_string)
        except (ValueError, AttributeError):
            _LOGGER.warning(f"Could not parse datetime: {date_string}")
            return None
    
    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                      headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Make an API request."""
        await self._ensure_session()
        
        url = f"{self.base_url}{endpoint}"
        request_headers = self._get_headers()
        
        if headers:
            request_headers.update(headers)
        
        _LOGGER.debug(f"Making {method} request to {url}")
        if data:
            _LOGGER.debug(f"Request data: {json.dumps(data, indent=2)}")
        
        try:
            async with self._session.request(
                method, url, json=data, headers=request_headers
            ) as response:
                response_text = await response.text()
                
                if response.status == 401:
                    raise AuthenticationError("Authentication failed")
                elif response.status >= 400:
                    raise APIError(f"API request failed with status {response.status}: {response_text}")
                
                try:
                    return json.loads(response_text)
                except json.JSONDecodeError:
                    raise APIError(f"Invalid JSON response: {response_text}")
                    
        except aiohttp.ClientError as e:
            raise APIError(f"Network error: {e}")
    
    async def get_app_token(self) -> str:
        """Get application token for API access."""
        data = {
            "grant_type": "client_credentials",
            "scope": "*"
        }
        
        headers = {"Authorization": self._get_auth_header()}
        
        response = await self._request("POST", "/oauth2/token", data, headers)
        
        if "error" in response:
            raise AuthenticationError(f"Failed to get app token: {response.get('error')}")
        
        token_type = response.get("token_type", "Bearer")
        access_token = response.get("access_token")
        
        if not access_token:
            raise AuthenticationError("No access token in response")
        
        self._app_token = f"{token_type} {access_token}"
        _LOGGER.debug("Successfully obtained app token")
        return self._app_token
    
    async def login(self, username: str, password: str) -> bool:
        """Login with username and password."""
        # First get app token if we don't have one
        if not self._app_token:
            await self.get_app_token()
        
        data = {
            "grant_type": "password",
            "username": username,
            "password": password,
            "scope": "*"
        }
        
        headers = {"Authorization": self._get_auth_header()}
        
        try:
            response = await self._request("POST", "/oauth2/token", data, headers)
            
            if "error" in response:
                raise AuthenticationError(f"Login failed: {response.get('error')}")
            
            token_type = response.get("token_type", "Bearer")
            access_token = response.get("access_token")
            
            if not access_token:
                raise AuthenticationError("No access token in login response")
            
            self._user_token = f"{token_type} {access_token}"
            _LOGGER.info("Successfully logged in")
            
            # Get user info to store user ID
            await self._get_user_info()
            
            return True
            
        except APIError as e:
            if "401" in str(e):
                raise AuthenticationError("Invalid username or password")
            raise
    
    async def _get_user_info(self):
        """Get user information and store user ID."""
        if not self._user_token:
            raise AuthenticationError("No user token available")
        
        headers = {"Authorization": self._user_token}
        response = await self._request("GET", "/api/getUser", headers=headers)
        
        if "error" in response:
            raise APIError(f"Failed to get user info: {response.get('error')}")
        
        self._user_id = response.get("id")
        _LOGGER.debug(f"User ID: {self._user_id}")
    
    async def get_modules(self) -> List[WateringModule]:
        """Get all watering modules for the user."""
        if not self._user_token:
            raise AuthenticationError("Not logged in")
        
        headers = {"Authorization": self._user_token}
        response = await self._request("GET", "/api/getUserWithHisModules", headers=headers)
        
        if "error" in response:
            raise APIError(f"Failed to get modules: {response.get('error')}")
        
        modules = []
        raw_modules = response.get("modules", [])
        
        # First pass: identify relay modules
        for module_data in raw_modules:
            module_type = module_data.get("type", "").lower()
            if "lr-mb" in module_type or "relay" in module_type:
                relay_id = module_data.get("id")
                relay_serial = module_data.get("serialNumber", "")
                relay_mac = module_data.get("macAddress", "")
                self._relay_modules[relay_id] = {
                    "serial": relay_serial,
                    "mac": relay_mac
                }
                _LOGGER.debug(f"Found relay module {relay_id}: {relay_serial}")
        
        # Second pass: process watering modules
        for module_data in raw_modules:
            module_type = module_data.get("type", "").lower()
            if "ip-fl" in module_type or "watering" in module_type:
                module = self._parse_module(module_data)
                modules.append(module)
                self._modules[module.id] = module
        
        _LOGGER.info(f"Found {len(modules)} watering modules with {len(self._relay_modules)} relay modules")
        return modules
    
    def _parse_module(self, data: Dict[str, Any]) -> WateringModule:
        """Parse module data from API response."""
        # Parse battery info
        battery_level = data.get("battery", 1)
        battery_voltage = data.get("batteryVoltage")
        battery_low = data.get("batteryLow", False)
        
        battery = Battery(
            level=battery_level,
            voltage=battery_voltage,
            low=battery_low
        )
        
        # Parse diagnostic info
        diagnostics = ModuleDiagnostics(
            signal_quality=data.get("cellularSignalQuality"),
            last_communication=self._parse_datetime(data.get("lastRadioCommunication")),
            has_sensor_fault=data.get("sensorState", False),
            has_communication_fault=not data.get("isOnline", False),
            firmware_version=data.get("softwareVersion"),
            hardware_version=data.get("hardwareVersion"),
            battery_voltage=battery_voltage
        )
        
        # Parse zones (outputs)
        zones = []
        for output in data.get("outputs", []):
            zone = WateringZone(
                id=output.get("id", ""),
                name=output.get("name", f"Zone {output.get('index', 0) + 1}"),
                index=output.get("index", 0),
                use_sensor=output.get("useSensor", False),
                flow_rate=output.get("flowRate", 0),
                water_budget=output.get("waterBudget", 100),
                has_sensor_fault=False  # Would need additional API call to determine this
            )
            zones.append(zone)
        
        # Parse watering status
        status = None
        status_data = data.get("status", {}).get("watering")
        if status_data:
            # Better logic for determining if watering is running
            running_program = status_data.get("runningProgram", 0)
            running_station = status_data.get("runningStation", 0)
            time_remaining = status_data.get("time", "00:00")
            state = status_data.get("state", 1)
            
            # Consider it running if we have active program/station and time remaining
            is_running = (
                state == 2 or  # Original state check
                (running_program > 0 and running_station > 0 and time_remaining != "00:00")
            )
            
            status = WateringStatus(
                is_running=is_running,
                running_program=running_program,
                running_station=running_station,
                time_remaining=time_remaining,
                state=state,
                origin=status_data.get("origin", 0),
                rain_delay=status_data.get("rainDelay", 0),
                sensor_active=status_data.get("sensor", 0) == 1
            )
            
            # Update zone watering status
            if is_running and running_station > 0:
                station_index = running_station - 1  # Convert to 0-based
                if station_index < len(zones):
                    zones[station_index].is_currently_watering = True
        
        # Get relay info
        relay_id = data.get("relay")
        relay_serial = None
        if relay_id and relay_id in self._relay_modules:
            relay_serial = self._relay_modules[relay_id]["serial"]
        
        return WateringModule(
            id=data.get("id", ""),
            name=data.get("name", "Unknown Module"),
            serial_number=data.get("serialNumber", ""),
            mac_address=data.get("macAddress", ""),
            type=data.get("type", ""),
            battery=battery,
            is_online=data.get("isOnline", False),
            zones=zones,
            programs=[],  # Programs loaded separately
            status=status,
            last_seen=self._parse_datetime(data.get("seenAt")),
            relay_id=relay_id,
            relay_serial=relay_serial,
            diagnostics=diagnostics
        )
    
    async def get_module_programs(self, module_id: str) -> List[WateringProgram]:
        """Get programs for a specific module."""
        if not self._user_token:
            raise AuthenticationError("Not logged in")
        
        data = {"module": module_id}
        headers = {"Authorization": self._user_token}
        
        response = await self._request("POST", "/api/getModuleWithHisPrograms", data, headers)
        
        if "error" in response:
            raise APIError(f"Failed to get programs: {response.get('error')}")
        
        programs = []
        current_status = None
        
        # Get current status to determine running program
        if module_id in self._modules and self._modules[module_id].status:
            current_status = self._modules[module_id].status
        
        for program_data in response.get("programs", []):
            is_currently_running = (
                current_status and 
                current_status.is_running and 
                current_status.running_program == program_data.get("index", 0)
            )
            
            program = WateringProgram(
                id=program_data.get("id", ""),
                name=program_data.get("name", f"Program {program_data.get('index', 0)}"),
                index=program_data.get("index", 0),
                start_times=program_data.get("startTimes", []),
                stations_duration=program_data.get("stationsDuration", []),
                week_days=program_data.get("weekDays", 0),
                water_budget=program_data.get("waterBudget", 100),
                is_active=any(t >= 0 for t in program_data.get("startTimes", [])),
                is_currently_running=is_currently_running
            )
            programs.append(program)
        
        # Update cached module
        if module_id in self._modules:
            self._modules[module_id].programs = programs
        
        return programs
    
    async def get_module_status_only(self, module_id: str) -> Optional[WateringStatus]:
        """Get just the watering status without full module refresh."""
        if not self._user_token:
            raise AuthenticationError("Not logged in")
        
        data = {"module": module_id}
        headers = {"Authorization": self._user_token}
        
        try:
            response = await self._request("POST", "/api/getModuleWithHisUsers", data, headers)
            
            if "error" in response:
                _LOGGER.warning(f"Failed to get module status: {response.get('error')}")
                return None
            
            # Parse status from response
            status_data = response.get("status", {}).get("watering")
            if status_data:
                # Better logic for determining if watering is running
                # If we have a non-zero running program, station, and time remaining, it's likely running
                running_program = status_data.get("runningProgram", 0)
                running_station = status_data.get("runningStation", 0)
                time_remaining = status_data.get("time", "00:00")
                state = status_data.get("state", 1)
                
                # Consider it running if we have active program/station and time remaining
                is_running = (
                    state == 2 or  # Original state check
                    (running_program > 0 and running_station > 0 and time_remaining != "00:00")
                )
                
                status = WateringStatus(
                    is_running=is_running,
                    running_program=running_program,
                    running_station=running_station,
                    time_remaining=time_remaining,
                    state=state,
                    origin=status_data.get("origin", 0),
                    rain_delay=status_data.get("rainDelay", 0),
                    sensor_active=status_data.get("sensor", 0) == 1
                )
                
                # Update cached module status and zones
                if module_id in self._modules:
                    self._modules[module_id].status = status
                    
                    # Reset all zones first
                    for zone in self._modules[module_id].zones:
                        zone.is_currently_watering = False
                    
                    # Update zone watering status - API uses 1-based indexing
                    if status.is_running and status.running_station > 0:
                        station_index = status.running_station - 1  # Convert to 0-based
                        if station_index < len(self._modules[module_id].zones):
                            self._modules[module_id].zones[station_index].is_currently_watering = True
                
                return status
            
            return None
            
        except APIError as e:
            _LOGGER.warning(f"Failed to get module status: {e}")
            return None
    
    async def refresh_all_modules_status(self) -> Dict[str, WateringModule]:
        """Efficiently refresh status for all cached modules."""
        if not self._user_token:
            raise AuthenticationError("Not logged in")
        
        updated_modules = {}
        
        # Refresh each module's status
        for module_id in self._modules.keys():
            try:
                await self.get_module_status_only(module_id)
                updated_modules[module_id] = self._modules[module_id]
            except Exception as e:
                _LOGGER.warning(f"Failed to refresh status for module {module_id}: {e}")
        
        return updated_modules
    
    async def get_zone_status(self, module_id: str, zone_index: int) -> Dict[str, Any]:
        """Get detailed status for a specific zone."""
        module = self._modules.get(module_id)
        if not module:
            raise APIError(f"Module {module_id} not found. Call get_modules() first.")
        
        if zone_index < 0 or zone_index >= len(module.zones):
            raise APIError(f"Invalid zone index {zone_index}. Module has {len(module.zones)} zones.")
        
        zone = module.zones[zone_index]
        status = module.status
        
        return {
            "id": zone.id,
            "name": zone.name,
            "index": zone.index,
            "is_watering": zone.is_currently_watering,
            "use_sensor": zone.use_sensor,
            "flow_rate": zone.flow_rate,
            "water_budget": zone.water_budget,
            "has_sensor_fault": zone.has_sensor_fault,
            "last_watered": zone.last_watered,
            "next_scheduled": zone.next_scheduled,
            "time_remaining": status.time_remaining if (status and status.running_station == zone_index + 1) else "00:00"
        }
    
    def get_next_scheduled_run(self, module_id: str) -> Optional[datetime]:
        """Calculate when the next automatic watering will occur."""
        module = self._modules.get(module_id)
        if not module:
            return None
        
        return module.next_scheduled_watering
    
    async def start_manual_watering(self, module_id: str, zone_index: int, duration_minutes: int) -> bool:
        """Start manual watering for a specific zone using the correct API endpoint."""
        if not self._user_token:
            raise AuthenticationError("Not logged in")
        
        # Get the module to find relay info
        module = self._modules.get(module_id)
        if not module:
            raise APIError(f"Module {module_id} not found. Call get_modules() first.")
        
        if not module.relay_serial:
            raise APIError(f"No relay serial found for module {module.name}")
        
        if not module.mac_suffix:
            raise APIError(f"No MAC address found for module {module.name}")
        
        # Validate zone index
        if zone_index < 0 or zone_index >= len(module.zones):
            raise ZoneNotAvailableError(f"Invalid zone index {zone_index}. Module has {len(module.zones)} zones.")
        
        zone = module.zones[zone_index]
        if zone.has_sensor_fault:
            raise ZoneNotAvailableError(f"Zone {zone.name} has a sensor fault and cannot be started.")
        
        # Format duration as MM:SS
        minutes = duration_minutes
        seconds = 0
        if duration_minutes > 60:
            minutes = duration_minutes // 60
            seconds = duration_minutes % 60
        
        time_string = f"{minutes:02d}:{seconds:02d}"
        
        # Build the correct API endpoint: /api/module/{relay_serial}/manual/{mac_suffix}
        endpoint = f"/api/module/{module.relay_serial}/manual/{module.mac_suffix}"
        
        # Build the request data
        data = {
            "watering": {
                "action": 2,  # 2 = Manual Valve
                "time": time_string,
                "station": zone_index + 1  # API uses 1-based indexing
            }
        }
        
        headers = {"Authorization": self._user_token}
        
        _LOGGER.info(f"Starting manual watering on {module.name}, zone {zone_index + 1} ({zone.name}) for {duration_minutes} minutes")
        _LOGGER.debug(f"Using endpoint: {endpoint}")
        _LOGGER.debug(f"Request data: {json.dumps(data, indent=2)}")
        
        try:
            response = await self._request("POST", endpoint, data, headers)
            
            if "error" in response:
                raise APIError(f"Failed to start manual watering: {response.get('error')}")
            
            _LOGGER.info(f"Manual watering command sent successfully")
            return True
            
        except APIError as e:
            _LOGGER.error(f"Failed to start manual watering: {e}")
            raise
    
    async def stop_watering(self, module_id: str) -> bool:
        """Stop all watering on a module using the correct API endpoint."""
        if not self._user_token:
            raise AuthenticationError("Not logged in")
        
        # Get the module to find relay info
        module = self._modules.get(module_id)
        if not module:
            raise APIError(f"Module {module_id} not found. Call get_modules() first.")
        
        if not module.relay_serial:
            raise APIError(f"No relay serial found for module {module.name}")
        
        if not module.mac_suffix:
            raise APIError(f"No MAC address found for module {module.name}")
        
        # Build the correct API endpoint
        endpoint = f"/api/module/{module.relay_serial}/manual/{module.mac_suffix}"
        
        # Build the request data for stop command
        data = {
            "watering": {
                "action": 0  # 0 = Manual Stop
            }
        }
        
        headers = {"Authorization": self._user_token}
        
        _LOGGER.info(f"Stopping watering on {module.name}")
        _LOGGER.debug(f"Using endpoint: {endpoint}")
        
        try:
            response = await self._request("POST", endpoint, data, headers)
            
            if "error" in response:
                raise APIError(f"Failed to stop watering: {response.get('error')}")
            
            _LOGGER.info(f"Stop watering command sent successfully")
            return True
            
        except APIError as e:
            _LOGGER.error(f"Failed to stop watering: {e}")
            raise
    
    async def test_all_valves(self, module_id: str, duration_minutes: int) -> bool:
        """Test all valves on a module sequentially."""
        if not self._user_token:
            raise AuthenticationError("Not logged in")
        
        # Get the module to find relay info
        module = self._modules.get(module_id)
        if not module:
            raise APIError(f"Module {module_id} not found. Call get_modules() first.")
        
        if not module.relay_serial:
            raise APIError(f"No relay serial found for module {module.name}")
        
        if not module.mac_suffix:
            raise APIError(f"No MAC address found for module {module.name}")
        
        # Format duration as MM:SS
        minutes = duration_minutes
        seconds = 0
        if duration_minutes > 60:
            minutes = duration_minutes // 60
            seconds = duration_minutes % 60
        
        time_string = f"{minutes:02d}:{seconds:02d}"
        
        # Build the correct API endpoint
        endpoint = f"/api/module/{module.relay_serial}/manual/{module.mac_suffix}"
        
        # Build the request data for test all valves
        data = {
            "watering": {
                "action": 1,  # 1 = Test All Valves
                "time": time_string
            }
        }
        
        headers = {"Authorization": self._user_token}
        
        _LOGGER.info(f"Testing all valves on {module.name} for {duration_minutes} minutes each")
        
        try:
            response = await self._request("POST", endpoint, data, headers)
            
            if "error" in response:
                raise APIError(f"Failed to test all valves: {response.get('error')}")
            
            _LOGGER.info(f"Test all valves command sent successfully")
            return True
            
        except APIError as e:
            _LOGGER.error(f"Failed to test all valves: {e}")
            raise
    
    async def start_program(self, module_id: str, program_index: int) -> bool:
        """Start a specific program on a module."""
        if not self._user_token:
            raise AuthenticationError("Not logged in")
        
        # Get the module to find relay info
        module = self._modules.get(module_id)
        if not module:
            raise APIError(f"Module {module_id} not found. Call get_modules() first.")
        
        if not module.relay_serial:
            raise APIError(f"No relay serial found for module {module.name}")
        
        if not module.mac_suffix:
            raise APIError(f"No MAC address found for module {module.name}")
        
        # Validate program index
        if program_index < 0 or program_index >= len(module.programs):
            raise APIError(f"Invalid program index {program_index}. Module has {len(module.programs)} programs.")
        
        program = module.programs[program_index]
        if not program.is_active:
            raise APIError(f"Program '{program.name}' is not active and cannot be started.")
        
        # Build the correct API endpoint
        endpoint = f"/api/module/{module.relay_serial}/manual/{module.mac_suffix}"
        
        # Build the request data for program start
        data = {
            "watering": {
                "action": 4,  # 4 = Manual Program
                "program": program_index  # 0-based program index
            }
        }
        
        headers = {"Authorization": self._user_token}
        
        _LOGGER.info(f"Starting program {program_index} ({program.name}) on {module.name}")
        
        try:
            response = await self._request("POST", endpoint, data, headers)
            
            if "error" in response:
                raise APIError(f"Failed to start program: {response.get('error')}")
            
            _LOGGER.info(f"Start program command sent successfully")
            return True
            
        except APIError as e:
            _LOGGER.error(f"Failed to start program: {e}")
            raise
    
    async def refresh_module_status(self, module_id: str) -> Optional[WateringModule]:
        """Refresh status for a specific module."""
        if not self._user_token:
            raise AuthenticationError("Not logged in")
        
        data = {"module": module_id}
        headers = {"Authorization": self._user_token}
        
        try:
            response = await self._request("POST", "/api/getModuleWithHisUsers", data, headers)
            
            if "error" in response:
                _LOGGER.warning(f"Failed to refresh module status: {response.get('error')}")
                return None
            
            # The response contains module data - parse it
            updated_module = self._parse_module(response)
            
            # Update cached module while preserving programs
            if module_id in self._modules:
                # Preserve existing programs if they exist
                if self._modules[module_id].programs:
                    updated_module.programs = self._modules[module_id].programs
                    
                    # Update program running status based on current status
                    if updated_module.status:
                        for program in updated_module.programs:
                            program.is_currently_running = (
                                updated_module.status.is_running and
                                updated_module.status.running_program == program.index
                            )
                
                self._modules[module_id] = updated_module
            
            return updated_module
            
        except APIError as e:
            _LOGGER.warning(f"Failed to refresh module status: {e}")
            return None
    
    def get_cached_module(self, module_id: str) -> Optional[WateringModule]:
        """Get a cached module by ID."""
        return self._modules.get(module_id)
    
    def get_cached_modules(self) -> List[WateringModule]:
        """Get all cached modules."""
        return list(self._modules.values())


# Test script for the enhanced library
async def test_enhanced_solem_api():
    """Test script to verify the enhanced API functionality."""
    # You'll need to replace these with actual credentials
    USERNAME = "your_username@example.com"
    PASSWORD = "your_password"
    
    async with SolemAPI() as api:
        try:
            # Test login
            print("Testing login...")
            await api.login(USERNAME, PASSWORD)
            print("✓ Login successful")
            
            # Test getting modules
            print("\nGetting modules...")
            modules = await api.get_modules()
            print(f"✓ Found {len(modules)} modules")
            
            for module in modules:
                print(f"\n=== Module: {module.name} ===")
                print(f"  ID: {module.id}")
                print(f"  Serial: {module.serial_number}")
                print(f"  MAC: {module.mac_address}")
                print(f"  MAC Suffix: {module.mac_suffix}")
                print(f"  Type: {module.type}")
                print(f"  Battery: {module.battery.level}/5 ({module.battery.percentage}%)")
                print(f"  Online: {module.is_online}")
                print(f"  Is Watering: {module.is_watering}")
                print(f"  Relay Serial: {module.relay_serial}")
                print(f"  Last Seen: {module.last_seen}")
                
                # Diagnostics
                if module.diagnostics:
                    print(f"  Firmware: {module.diagnostics.firmware_version}")
                    print(f"  Signal Quality: {module.diagnostics.signal_quality}")
                    print(f"  Last Communication: {module.diagnostics.last_communication}")
                
                # Status
                if module.status:
                    print(f"  Status: Running={module.status.is_running}, Program={module.status.running_program}, Station={module.status.running_station}")
                    print(f"  Time Remaining: {module.status.time_remaining}")
                
                # Zones
                print(f"  Zones: {len(module.zones)}")
                for zone in module.zones:
                    watering_status = "🚿" if zone.is_currently_watering else "💧"
                    print(f"    {watering_status} Zone {zone.index}: {zone.name}")
                
                # Get programs for this module
                print("  Getting programs...")
                programs = await api.get_module_programs(module.id)
                print(f"  Programs: {len(programs)}")
                
                for program in programs:
                    status_icon = "▶️" if program.is_currently_running else ("✅" if program.is_active else "❌")
                    print(f"    {status_icon} {program.name}: {program.get_schedule_description()}")
                    if program.next_run_time:
                        print(f"       Next run: {program.next_run_time}")
                    print(f"       Duration: {program.estimated_duration} minutes")
                
                # Test zone status
                if module.zones:
                    print(f"  Testing zone status for zone 0...")
                    zone_status = await api.get_zone_status(module.id, 0)
                    print(f"    Zone status: {zone_status}")
                
                # Next scheduled watering
                next_watering = api.get_next_scheduled_run(module.id)
                if next_watering:
                    print(f"  Next scheduled watering: {next_watering}")
                
                # Test status-only refresh
                print("  Testing status refresh...")
                status = await api.get_module_status_only(module.id)
                if status:
                    print(f"    Status refreshed: Running={status.is_running}")
                
                print()  # Blank line between modules
            
            # Test bulk status refresh
            print("Testing bulk status refresh...")
            updated_modules = await api.refresh_all_modules_status()
            print(f"✓ Refreshed status for {len(updated_modules)} modules")
                
        except Exception as e:
            print(f"✗ Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    # Run the test
    asyncio.run(test_enhanced_solem_api())
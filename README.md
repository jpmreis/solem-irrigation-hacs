# Solem Irrigation Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Latest Release](https://img.shields.io/github/release/jpmreis/solem-irrigation-hacs.svg)](https://github.com/jpmreis/solem-irrigation-hacs/releases/latest)
[![GitHub All Releases](https://img.shields.io/github/downloads/jpmreis/solem-irrigation-hacs/total.svg)](https://github.com/jpmreis/solem-irrigation-hacs/releases)

A comprehensive Home Assistant custom component for controlling and monitoring Solem irrigation systems that have a WIFI CONNECTED CONTROLLER.

## Features

### Device Control
- **Module Control**: Master switches to start/stop entire irrigation modules
- **Zone Control**: Individual zone switches for manual watering
- **Program Control**: Run specific irrigation programs manually

### Monitoring & Status
- **Real-time Status**: Current watering status, time remaining, active zones
- **Battery Monitoring**: Battery levels and low battery alerts
- **Connectivity**: Online/offline status and signal quality
- **Diagnostics**: Last communication times, firmware versions

### Calendar Integration
- **Schedule Visualization**: View upcoming irrigation events in calendar format
- **Per-Module Calendars**: Individual calendars for each irrigation module
- **System Calendar**: Combined view of all irrigation schedules

### Smart Polling
- **Adaptive Intervals**: Fast polling during watering, normal polling when idle
- **Efficient API Usage**: Status-only updates to minimize API calls
- **Token Management**: Automatic token refresh with graceful error handling

## Installation

### HACS Installation (Recommended)
1. Add this repository to HACS as a custom repository
2. Install "Solem Irrigation" from HACS
3. Restart Home Assistant
4. Add the integration through the UI

### Manual Installation
1. Copy the `solem_irrigation` folder to your `custom_components` directory
2. Restart Home Assistant
3. Add the integration through the UI (Settings → Devices & Services → Add Integration)

## Configuration

### Initial Setup
1. Go to Settings → Devices & Services
2. Click "Add Integration" and search for "Solem Irrigation"
3. Enter your Solem account username and password
4. The integration will automatically discover your irrigation modules

### Options
Configure polling intervals and default settings:
- **Normal Scan Interval**: How often to check status when idle (default: 5 minutes)
- **Fast Scan Interval**: How often to check during watering (default: 45 seconds)
- **Full Refresh Interval**: How often to refresh all data (default: 30 minutes)
- **Manual Duration**: Default duration for manual watering (default: 10 minutes)

## Entities Created

### For Each Module

#### Switches
- `switch.irrigation_[module_name]` - Master module control
- `switch.irrigation_[module_name]_zone_[N]` - Individual zone controls
- `switch.irrigation_[module_name]_program_[N]` - Program controls

#### Sensors
- `sensor.irrigation_[module_name]_status` - Current activity status
- `sensor.irrigation_[module_name]_time_remaining` - Minutes remaining
- `sensor.irrigation_[module_name]_battery` - Battery percentage
- `sensor.irrigation_[module_name]_next_run` - Next scheduled run
- `sensor.irrigation_[module_name]_signal_quality` - Cellular signal quality

#### Binary Sensors
- `binary_sensor.irrigation_[module_name]_online` - Connection status
- `binary_sensor.irrigation_[module_name]_watering` - Currently watering
- `binary_sensor.irrigation_[module_name]_battery_low` - Low battery alert
- `binary_sensor.irrigation_[module_name]_zone_[N]_watering` - Zone watering status
- `binary_sensor.irrigation_[module_name]_program_[N]_active` - Program enabled status
- `binary_sensor.irrigation_[module_name]_program_[N]_running` - Program currently running

#### Calendar
- `calendar.irrigation_[module_name]_schedule` - Module irrigation schedule

### System-Wide
- `calendar.irrigation_system_schedule` - Complete irrigation schedule

## Services

### `solem_irrigation.start_manual_watering`
Start manual watering for a specific zone.

**Parameters:**
- `entity_id`: Zone switch entity ID
- `duration`: Duration in minutes (1-120, default: 10)

**Example:**
```yaml
service: solem_irrigation.start_manual_watering
target:
  entity_id: switch.irrigation_front_yard_zone_1
data:
  duration: 15
```

### `solem_irrigation.stop_watering`
Stop all watering on a module.

**Parameters:**
- `entity_id`: Module or zone switch entity ID

**Example:**
```yaml
service: solem_irrigation.stop_watering
target:
  entity_id: switch.irrigation_front_yard
```

### `solem_irrigation.test_all_valves`
Test all valves on a module sequentially.

**Parameters:**
- `entity_id`: Module switch entity ID
- `duration`: Duration in minutes for each valve (1-10, default: 2)

**Example:**
```yaml
service: solem_irrigation.test_all_valves
target:
  entity_id: switch.irrigation_front_yard
data:
  duration: 3
```

### `solem_irrigation.start_program`
Start a specific irrigation program.

**Parameters:**
- `entity_id`: Program switch entity ID

**Example:**
```yaml
service: solem_irrigation.start_program
target:
  entity_id: switch.irrigation_front_yard_program_1
```

## Dashboard Examples

### Basic Module Card
```yaml
type: entities
title: Front Yard Irrigation
entities:
  - switch.irrigation_front_yard
  - sensor.irrigation_front_yard_status
  - sensor.irrigation_front_yard_time_remaining
  - sensor.irrigation_front_yard_battery
  - sensor.irrigation_front_yard_next_run
```

### Zone Control Card
```yaml
type: grid
columns: 2
cards:
  - type: button
    entity: switch.irrigation_front_yard_zone_1
    name: Zone 1
    show_state: true
  - type: button
    entity: switch.irrigation_front_yard_zone_2
    name: Zone 2
    show_state: true
  - type: button
    entity: switch.irrigation_front_yard_zone_3
    name: Zone 3
    show_state: true
  - type: button
    entity: switch.irrigation_front_yard_zone_4
    name: Zone 4
    show_state: true
```

### Program Control Card
```yaml
type: entities
title: Irrigation Programs
entities:
  - switch.irrigation_front_yard_program_0
  - switch.irrigation_front_yard_program_1
  - switch.irrigation_front_yard_program_2
```

### Calendar Card
```yaml
type: calendar
entities:
  - calendar.irrigation_system_schedule
title: Irrigation Schedule
initial_view: week
```

### Status Overview
```yaml
type: glance
title: Irrigation System Status
entities:
  - entity: binary_sensor.irrigation_front_yard_online
    name: Front Yard
  - entity: binary_sensor.irrigation_back_yard_online
    name: Back Yard
  - entity: sensor.irrigation_front_yard_battery
    name: Front Battery
  - entity: sensor.irrigation_back_yard_battery
    name: Back Battery
```

## Automations

### Skip Irrigation When Raining
```yaml
alias: Skip irrigation when raining
trigger:
  - platform: calendar
    entity_id: calendar.irrigation_system_schedule
    event: start
condition:
  - condition: numeric_state
    entity_id: sensor.rainfall_24h
    above: 5
action:
  - service: solem_irrigation.stop_watering
    target:
      entity_id: switch.irrigation_{{ trigger.calendar_event.summary.split(' - ')[0].lower().replace(' ', '_') }}
```

### Low Battery Notification
```yaml
alias: Irrigation low battery alert
trigger:
  - platform: state
    entity_id: 
      - binary_sensor.irrigation_front_yard_battery_low
      - binary_sensor.irrigation_back_yard_battery_low
    to: 'on'
action:
  - service: notify.mobile_app
    data:
      title: "Irrigation Battery Low"
      message: "{{ trigger.to_state.attributes.friendly_name }} battery is low"
```

### Daily Status Report
```yaml
alias: Daily irrigation status
trigger:
  - platform: time
    at: "07:00:00"
action:
  - service: notify.mobile_app
    data:
      title: "Irrigation Status"
      message: >
        {% set modules = states.switch | selectattr('entity_id', 'match', 'switch.irrigation_.*') | selectattr('entity_id', 'match', '.*(?<!zone_\d)(?<!program_\d)) | list %}
        {% set online = modules | selectattr('attributes.is_online', 'eq', true) | list | count %}
        {% set total = modules | count %}
        {{ online }}/{{ total }} modules online.
        {% for module in modules %}
        {%- if module.attributes.next_run_time %}
        {{ module.attributes.friendly_name }}: Next run {{ as_timestamp(module.attributes.next_run_time) | timestamp_custom('%H:%M') }}
        {%- endif %}
        {%- endfor %}
```

## Troubleshooting

### Authentication Issues
1. Verify your username and password are correct
2. Check if your account can log in via the Solem mobile app
3. Try removing and re-adding the integration

### Connection Problems
1. Check your internet connection
2. Verify the Solem servers are accessible
3. Look for error messages in Home Assistant logs

### Token Refresh Errors
The integration automatically handles token refresh. If you see authentication errors:
1. The integration will trigger a re-authentication flow
2. Enter your credentials when prompted
3. Tokens are stored securely and persist across restarts

### API Rate Limiting
The integration uses smart polling to minimize API calls:
- Fast polling (45s) only when watering is active
- Normal polling (5min) for regular status checks
- Full refresh (30min) for configuration changes

### Log Debugging
Enable debug logging to troubleshoot issues:

```yaml
logger:
  default: warning
  logs:
    custom_components.solem_irrigation: debug
```

## Technical Details

### Architecture
- **Data Coordinator**: Manages API polling and data caching
- **Token Manager**: Handles OAuth token lifecycle
- **Smart Polling**: Adapts polling frequency based on system state
- **Device Organization**: Each module becomes a Home Assistant device

### API Efficiency
- Status-only updates during normal operation
- Bulk refresh only when needed
- Cached calendar events to reduce computation
- Automatic retry with exponential backoff

### Security
- Credentials stored in Home Assistant's encrypted storage
- OAuth tokens automatically refreshed
- No sensitive data logged

## Support

### Issues
Report issues on the [GitHub repository](https://github.com/jpmreis/solem-irrigation/issues).

### Feature Requests
Feature requests are welcome via GitHub issues.

### Contributing
Contributions are welcome! Please see the contributing guidelines in the repository.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by Solem. Use at your own risk.

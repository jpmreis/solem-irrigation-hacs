# Solem Irrigation Integration

Control and monitor your Solem irrigation system directly from Home Assistant.

## Features

- **Complete Control**: Start/stop watering for individual zones or entire modules
- **Real-time Monitoring**: Battery levels, watering status, time remaining
- **Calendar Integration**: View irrigation schedules in calendar format
- **Smart Polling**: Efficient API usage with adaptive polling intervals
- **Automation Ready**: Rich sensors and switches for advanced automations

## Installation via HACS

1. Add this repository to HACS as a custom repository
2. Install "Solem Irrigation" from HACS
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services

## Configuration

Enter your Solem account credentials when prompted. The integration will automatically discover your irrigation modules and create all necessary entities.

For detailed setup instructions, see the [README](https://github.com/jpmreis/solem-irrigation-hacs/blob/main/README.md).
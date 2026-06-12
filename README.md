# Real-time Electricity Generation & Carbon Emissions

A Python pipeline that fetches electricity generation and CO₂ emissions data from Australia's National Electricity Market (NEM) via the [Open Electricity API](https://docs.openelectricity.org.au/api-reference/overview), stores it locally, streams it over MQTT, and visualises it on an interactive live dashboard.

## Overview

This project simulates a real-time data stream by:

1. **Collecting** facility-level power and emissions data from the Open Electricity API
2. **Processing** and consolidating records into a single CSV dataset
3. **Publishing** records to an MQTT broker in chronological order
4. **Visualising** incoming MQTT messages on a map-based Dash dashboard

```
Open Electricity API
        │
        ▼
data_collector_publisher.py  ──►  consolidated_data.csv
        │
        ▼
   MQTT Broker  ──►  live_dashboard.py  (map + table)
```

## Project Structure

```
.
├── config.py                    # API keys, MQTT settings, date range, paths
├── data_collector_publisher.py  # Fetch, clean, save, and publish data via MQTT
├── live_dashboard.py            # Subscribe to MQTT and display live map/table
├── requirements.txt             # Python dependencies
├── data/
│   ├── consolidated_data.csv    # Merged historical dataset (generated)
│   └── cache/
│       └── facilities_list.json # Cached facility metadata (auto-generated)
```

| File / Folder | Purpose |
|---------------|---------|
| `config.py` | Central configuration: API credentials, NEM network settings, MQTT broker, time range, and file paths |
| `data_collector_publisher.py` | Pulls data from the API, cleans and merges it into CSV, then publishes records to MQTT |
| `live_dashboard.py` | Subscribes to the MQTT topic and renders a live map and data table |
| `data/consolidated_data.csv` | Primary output dataset with timestamps, facility info, power (MW), and CO₂ (t) |
| `data/cache/` | Optional cache for facility metadata (names, coordinates, fuel type). Regenerated automatically |

## Requirements

- Python 3.9+
- An [Open Electricity API key](https://platform.openelectricity.org.au) (register on the platform; API base URL is `https://api.openelectricity.org.au/v4`)
- Network access to the API and MQTT broker

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Edit `config.py` before running:

| Setting | Description |
|---------|-------------|
| `API_KEY` | Your Open Electricity API bearer token |
| `START_DATE` / `END_DATE` | Data window (default: 2025-10-01 to 2025-10-08) |
| `INTERVAL` | Sampling interval (`5m` = 5 minutes) |
| `MQTT_BROKER_HOST` | MQTT broker address (default: `test.mosquitto.org`) |
| `MQTT_TOPIC` | Topic used for publishing and subscribing |
| `PUBLISH_DELAY` | Seconds between each MQTT message |
| `RETRIEVAL_DELAY` | Seconds between each data-fetch cycle |

## Usage

Run the collector and dashboard in **two separate terminals**.

### 1. Start the data collector & publisher

```bash
python data_collector_publisher.py
```

This will:

- Fetch facility lists and generation/emissions data from the API
- Clean, deduplicate, and append records to `data/consolidated_data.csv`
- Publish new records to the configured MQTT topic

Press `Ctrl+C` to stop.

### 2. Start the live dashboard

```bash
python live_dashboard.py
```

Open [http://localhost:8050](http://localhost:8050) in your browser.

The dashboard lets you:

- Toggle between **Power (MW)** and **CO₂ (t)** on the map
- Filter by **region** and **fuel technology**
- Adjust the auto-refresh interval
- View the latest records in a sortable table

> **Note:** The dashboard only shows data while `data_collector_publisher.py` is running (or after MQTT messages have been received). Map markers require `data/cache/facilities_list.json` for facility coordinates.

## Data Schema

Each row in `consolidated_data.csv` contains:

| Column | Description |
|--------|-------------|
| `timestamp` | Observation time |
| `facility_id` | Facility code |
| `facility_name` | Human-readable facility name |
| `network` | Electricity network (`NEM`) |
| `power_generated` | Generation in megawatts (MW) |
| `co2_emissions` | CO₂ emissions in tonnes (t) |
| `interval` | Data resolution (e.g. `5m`) |

## MQTT Message Format

Each published message is a JSON object:

```json
{
  "timestamp": "2025-10-01T00:00:00",
  "facility_id": "CALL",
  "facility_name": "Callide",
  "network": "NEM",
  "power_generated": 557.6,
  "co2_emissions": 44.4,
  "publish_time": "2025-10-01T14:00:00",
  "sequence_number": 1
}
```

## Maintenance Notes

- **`data/cache/`** — Safe to delete. It will be recreated the next time the collector fetches facility metadata from the API.
- **`consolidated_data.csv`** — Your collected dataset. Delete only if you want to start fresh.

## Dependencies

| Package | Role |
|---------|------|
| `requests` | HTTP client for the Open Electricity API |
| `paho-mqtt` | MQTT publish/subscribe |
| `pandas` / `numpy` | Data cleaning and transformation |
| `dash` / `plotly` / `dash-leaflet` | Interactive web dashboard and map |


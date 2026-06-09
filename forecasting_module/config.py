"""Constants, paths, and configuration for the forecasting pipeline."""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Source data (BDG2 subset cloned into repo)
DATA_SOURCE = PROJECT_ROOT / "building-data-genome-project-2" / "data"
ELECTRICITY_PATH = DATA_SOURCE / "meters" / "cleaned" / "electricity_cleaned.csv"
METADATA_PATH = DATA_SOURCE / "metadata" / "metadata.csv"
WEATHER_PATH = DATA_SOURCE / "weather" / "weather.csv"

# Output layers (Bronze → Silver → Gold)
OUTPUT_BASE = PROJECT_ROOT / "data" / "processed" / "forecasting"
BRONZE_DIR = OUTPUT_BASE / "bronze"
SILVER_DIR = OUTPUT_BASE / "silver"
GOLD_DIR = OUTPUT_BASE / "gold"

# ---------------------------------------------------------------------------
# Column selections
# ---------------------------------------------------------------------------
METADATA_KEEP = [
    "building_id",
    "site_id",
    "primaryspaceusage",
    "sqm",
    "lat",
    "lng",
    "timezone",
]

WEATHER_KEEP = [
    "timestamp",
    "site_id",
    "airTemperature",
    "cloudCoverage",
    "dewTemperature",
    "precipDepth1HR",
    "seaLvlPressure",
    "windDirection",
    "windSpeed",
]

# ---------------------------------------------------------------------------
# Processing parameters
# ---------------------------------------------------------------------------
CHUNK_SIZE = 200                 # buildings per melt-batch (memory control)
INTERP_MAX_GAP_HOURS = 6        # only interpolate gaps ≤ this size
EXPECTED_START = "2016-01-01T00:00:00"
EXPECTED_END = "2017-12-31T23:00:00"

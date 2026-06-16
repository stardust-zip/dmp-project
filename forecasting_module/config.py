"""Constants, paths, and configuration for the forecasting pipeline."""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Source data (BDG2 subset cloned into repo)
DATA_SOURCE = PROJECT_ROOT / "building-data-genome-project-2"
ELECTRICITY_PATH = DATA_SOURCE / "electricity_cleaned.csv"
METADATA_PATH = DATA_SOURCE / "metadata.csv"
WEATHER_PATH = DATA_SOURCE / "weather.csv"

# Output layers (Bronze → Silver → Gold)
OUTPUT_BASE = PROJECT_ROOT / "data2" / "processed" / "forecasting"
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
    "timezone",
]

WEATHER_KEEP = [
    "timestamp",
    "site_id",
    "airTemperature",
    "dewTemperature",
    "windDirection",
    "windSpeed",
]

# ---------------------------------------------------------------------------
# Processing parameters
# ---------------------------------------------------------------------------
CHUNK_SIZE = 200                 # buildings per melt-batch (memory control)
INTERP_MAX_GAP_HOURS = 6        # only interpolate gaps ≤ this size
SEASONAL_MAX_GAP_HOURS = 24     # upper bound for seasonal imputation (t-24h)
MISSING_RATE_THRESHOLD = 0.30   # drop buildings exceeding this consumption null rate

# Outlier detection
IQR_MULTIPLIER = 3.0            # IQR fence multiplier (generous, not 1.5)
WEATHER_BOUNDS: dict = {        # rule-based physical bounds
    "airTemperature":  (-30.0, 60.0),
    "windSpeed":       (0.0, None),
    "seaLvlPressure":  (800.0, 1100.0),
}

EXPECTED_START = "2016-01-01T00:00:00"
EXPECTED_END = "2017-12-31T23:00:00"

# Feature engineering
FEATURE_STORE_DIR = OUTPUT_BASE / "feature_store"
HISTORY_WINDOW_DAYS = 30
FORECAST_HORIZON_HOURS = 24
WEATHER_MODE = "none"  # "none" | "historical" | "forecast"

# Dataset split
DATASET_DIR = OUTPUT_BASE / "dataset"
TRAIN_END = "2017-06-30T23:00:00"   # Train: 2016-01 → 2017-06
VAL_END = "2017-09-30T23:00:00"     # Val:   2017-07 → 2017-09
                                     # Test:  2017-10 → 2017-12

# Report output
REPORT_DIR = OUTPUT_BASE / "report"

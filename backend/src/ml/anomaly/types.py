from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

MISSING_READING = "missing_reading"
LONG_MISSING_RUN = "long_missing_run"
NO_DATA_BUILDING = "no_data_building"
FLATLINE = "flatline"
NEAR_ZERO_FLATLINE = "near_zero_flatline"
SPIKE_EXTREME = "spike_extreme_reading"

STAGE1_TYPE_LABELS = {
    MISSING_READING: "Missing meter data",
    LONG_MISSING_RUN: "Missing meter data",
    NO_DATA_BUILDING: "No usable meter data",
    FLATLINE: "Flatline reading",
    NEAR_ZERO_FLATLINE: "Near-zero flatline",
    SPIKE_EXTREME: "Extreme spike",
}
DIRECTION_TYPE_LABELS = {
    "under": "Unusual low consumption",
    "over": "Unusual high consumption",
}

SEVERITIES = ["Critical", "High", "Medium", "Low"]
SEVERITY_ORDER = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}

LOOKBACK_HOURS = 168
FLATLINE_MIN_RUN = 3
LONG_MISSING_RUN_MIN = 3
DEFAULT_METRIC_TYPE = "electricity"
WEATHER_COVERAGE_START_YEAR = 2016
WEATHER_COVERAGE_END_YEAR = 2017


@dataclass
class RuleFinding:
    building_id: str
    site_id: str
    timestamp: datetime
    metric_type_id: str
    primary_space_usage: str | None
    actual_value: float | None
    is_anomaly: bool
    direction: str | None
    severity: str
    source: str
    anomaly_type: str
    reason: str
    mlflow_run_id: str | None

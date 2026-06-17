from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from src.core.config import settings

logger = logging.getLogger(__name__)

WEATHER_CONTEXT_TYPES = {"airTemperature", "windSpeed", "dewTemperature"}
RAW_DATA_DIR = settings.DATA_DIR


def load_weather_for_range(
    db: Session,
    site_ids: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    """Load weather features from DB, falling back to the raw weather CSV."""
    from src.models import ContextData

    rows = (
        db.query(
            ContextData.timestamp,
            ContextData.location_id.label("site_id"),
            ContextData.context_type_id,
            ContextData.value,
        )
        .filter(
            ContextData.location_id.in_(site_ids),
            ContextData.context_type_id.in_(WEATHER_CONTEXT_TYPES),
            ContextData.timestamp >= start,
            ContextData.timestamp <= end,
        )
        .all()
    )

    if rows:
        raw = pd.DataFrame(rows, columns=["timestamp", "site_id", "context_type_id", "value"])
        weather = raw.pivot_table(
            index=["timestamp", "site_id"],
            columns="context_type_id",
            values="value",
        ).reset_index()
        weather.columns.name = None
    else:
        csv_path = Path(RAW_DATA_DIR) / "weather" / "weather.csv"
        if not csv_path.exists():
            logger.warning("No weather data in DB and no CSV fallback found.")
            return pd.DataFrame(), []
        weather = pd.read_csv(csv_path)
        weather["timestamp"] = pd.to_datetime(weather["timestamp"], utc=True)
        for col in ["airTemperature", "dewTemperature", "windSpeed"]:
            if col in weather.columns:
                weather[col] = pd.to_numeric(weather[col], errors="coerce")

    weather["timestamp"] = pd.to_datetime(weather["timestamp"], utc=True)
    if {"airTemperature", "dewTemperature"}.issubset(weather.columns):
        weather["temp_dew_spread"] = weather["airTemperature"] - weather["dewTemperature"]

    for col, window in [("airTemperature", 24), ("airTemperature", 168)]:
        if col not in weather.columns:
            continue
        out_col = f"{col}_roll{window}h"
        weather[out_col] = (
            weather.sort_values(["site_id", "timestamp"])
            .groupby("site_id")[col]
            .transform(lambda s: s.rolling(window, min_periods=1).mean())
        )

    feature_cols = [
        c for c in [
            "airTemperature",
            "windSpeed",
            "temp_dew_spread",
            "airTemperature_roll24h",
            "airTemperature_roll168h",
        ]
        if c in weather.columns
    ]
    return weather[["timestamp", "site_id"] + feature_cols], feature_cols

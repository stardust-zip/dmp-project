"""Feature engineering layer — transform Gold v2 into training-ready features."""

from __future__ import annotations

import sys
import os
import time
from pathlib import Path

import polars as pl

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from forecasting_module.config import (
    FEATURE_STORE_DIR,
    FORECAST_HORIZON_HOURS,
    GOLD_DIR,
    REPORT_DIR,
    WEATHER_MODE,
)

WEATHER_COLS = ["airTemperature", "dewTemperature"]


class FeatureEngineer:
    """Transform Gold v2 data into a feature store for model training."""

    def __init__(
        self,
        output_dir: Path = FEATURE_STORE_DIR,
        forecast_horizon_hours: int = FORECAST_HORIZON_HOURS,
        weather_mode: str = WEATHER_MODE,
    ) -> None:
        self.output_dir = output_dir
        self.forecast_horizon_hours = forecast_horizon_hours
        self.weather_mode = weather_mode

    # ==================================================================
    # Feature creation
    # ==================================================================
    @staticmethod
    def create_calendar_features(df: pl.DataFrame) -> pl.DataFrame:
        """Extract calendar columns from timestamp."""
        return df.with_columns([
            pl.col("timestamp").dt.hour().alias("hour"),
            pl.col("timestamp").dt.weekday().alias("day_of_week"),
            pl.col("timestamp").dt.month().alias("month"),
            (pl.col("timestamp").dt.weekday() >= 6).cast(pl.Int8).alias("is_weekend"),
        ])

    @staticmethod
    def create_consumption_features(df: pl.DataFrame) -> pl.DataFrame:
        """Create lag and rolling features per building_id.

        All features use only past data relative to the current row.
        rolling_mean/std(window_size=N) includes current row + N-1 past rows.
        """
        df = df.sort(["building_id", "timestamp"])
        return df.with_columns([
            # Lag features
            pl.col("consumption").shift(1).over("building_id").alias("lag_1h"),
            pl.col("consumption").shift(24).over("building_id").alias("lag_24h"),
            pl.col("consumption").shift(168).over("building_id").alias("lag_168h"),
            # Rolling features
            pl.col("consumption").rolling_mean(window_size=24, min_samples=1)
            .over("building_id").alias("rolling_mean_24h"),
            pl.col("consumption").rolling_std(window_size=24, min_samples=1)
            .over("building_id").alias("rolling_std_24h"),
            pl.col("consumption").rolling_mean(window_size=168, min_samples=1)
            .over("building_id").alias("rolling_mean_168h"),
            pl.col("consumption").rolling_std(window_size=168, min_samples=1)
            .over("building_id").alias("rolling_std_168h"),
        ])

    def create_weather_features(self, df: pl.DataFrame) -> pl.DataFrame:
        """Add weather columns depending on weather_mode.

        none        → drop all weather columns
        historical  → keep weather at time t
        forecast    → shift weather to time t+horizon, rename to future_*
        """
        if self.weather_mode == "none":
            return df.drop([c for c in WEATHER_COLS if c in df.columns])

        if self.weather_mode == "historical":
            return df

        if self.weather_mode == "forecast":
            df = df.sort(["building_id", "timestamp"])
            shift_exprs = [
                pl.col(c).shift(-self.forecast_horizon_hours)
                .over("building_id").alias(f"future_{c}")
                for c in WEATHER_COLS
                if c in df.columns
            ]
            return df.with_columns(shift_exprs).drop(
                [c for c in WEATHER_COLS if c in df.columns]
            )

        raise ValueError(f"Unknown weather_mode: {self.weather_mode}")

    def create_target(self, df: pl.DataFrame) -> pl.DataFrame:
        """Create target = consumption at t+horizon."""
        df = df.sort(["building_id", "timestamp"])
        return df.with_columns(
            pl.col("consumption")
            .shift(-self.forecast_horizon_hours)
            .over("building_id")
            .alias("target"),
        )

    def drop_nulls(self, df: pl.DataFrame) -> pl.DataFrame:
        """Drop rows where required features or target are null."""
        required = ["target", "lag_24h", "lag_168h", "rolling_mean_24h"]

        if self.weather_mode == "forecast":
            required += [
                f"future_{c}" for c in WEATHER_COLS
                if f"future_{c}" in df.columns
            ]

        return df.filter(
            pl.all_horizontal([pl.col(c).is_not_null() for c in required])
        )

    # ==================================================================
    # Runner
    # ==================================================================
    def run(self, df: pl.DataFrame) -> pl.DataFrame:
        """Execute feature engineering pipeline → Feature Store Parquet."""
        t0 = time.perf_counter()
        rows_in = df.shape[0]

        print(f"  Config: horizon={self.forecast_horizon_hours}h, "
              f"weather={self.weather_mode}")
        print(f"  Input: {rows_in:,} rows × {df.shape[1]} cols")

        print("  Creating calendar features ...")
        df = self.create_calendar_features(df)

        print("  Creating consumption features ...")
        df = self.create_consumption_features(df)

        print("  Creating weather features ...")
        df = self.create_weather_features(df)

        print("  Creating target ...")
        df = self.create_target(df)

        print("  Dropping rows with null features/target ...")
        rows_before = df.shape[0]
        df = self.drop_nulls(df)
        rows_after = df.shape[0]
        dropped = rows_before - rows_after
        print(f"    Dropped {dropped:,} rows ({dropped / rows_before:.1%})")

        # Save
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = self._build_filename()
        out_path = self.output_dir / filename
        df.write_parquet(out_path)
        print(f"    → Saved: {out_path}")
        print(f"    → {df.shape[0]:,} rows × {df.shape[1]} cols")

        # Reports
        self._save_reports(df, rows_in, rows_after, dropped)

        elapsed = time.perf_counter() - t0
        print(f"  Feature engineering done in {elapsed:.1f}s")
        return df

    # ==================================================================
    # Helpers
    # ==================================================================
    def _build_filename(self) -> str:
        mode_suffix = {
            "none": "energy",
            "historical": "historical_weather",
            "forecast": "forecast_weather",
        }[self.weather_mode]
        return f"features_h{self.forecast_horizon_hours}_{mode_suffix}.parquet"

    def _save_reports(
        self,
        df: pl.DataFrame,
        rows_in: int,
        rows_out: int,
        rows_dropped: int,
    ) -> None:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        tag = f"h{self.forecast_horizon_hours}_{self.weather_mode}"

        # Row count summary
        summary = pl.DataFrame({
            "metric": [
                "input_rows", "output_rows", "dropped_rows", "drop_rate",
                "n_buildings", "n_features", "horizon_hours", "weather_mode",
            ],
            "value": [
                str(rows_in), str(rows_out), str(rows_dropped),
                f"{rows_dropped / rows_in:.4%}",
                str(df["building_id"].n_unique()),
                str(df.shape[1]),
                str(self.forecast_horizon_hours),
                self.weather_mode,
            ],
        })
        summary.write_csv(REPORT_DIR / f"fe_{tag}_summary.csv")

        # Null summary per column
        null_summary = df.select(
            [pl.col(c).is_null().mean().alias(c) for c in df.columns]
        ).transpose(
            include_header=True,
            header_name="column",
            column_names=["null_rate"],
        )
        null_summary.write_csv(REPORT_DIR / f"fe_{tag}_null_summary.csv")

        # Per-building row counts
        building_counts = df.group_by("building_id").agg(
            pl.len().alias("n_rows"),
        ).sort("n_rows")
        building_counts.write_csv(
            REPORT_DIR / f"fe_{tag}_building_counts.csv"
        )


# -----------------------------------------------------------------------
# Standalone:  python -m forecasting_module.feature_engineering
# -----------------------------------------------------------------------
if __name__ == "__main__":
    gold_v2_path = GOLD_DIR / "validated_v2.parquet"
    if not gold_v2_path.exists():
        sys.exit(
            f"Gold v2 file not found: {gold_v2_path}\n"
            "Run the full pipeline first."
        )

    print(f"Loading Gold v2 from {gold_v2_path} ...")
    gold_v2 = pl.read_parquet(gold_v2_path)
    print(f"  {gold_v2.shape[0]:,} rows × {gold_v2.shape[1]} cols\n")

    FeatureEngineer(
        forecast_horizon_hours=168,
        weather_mode="historical",
    ).run(gold_v2)

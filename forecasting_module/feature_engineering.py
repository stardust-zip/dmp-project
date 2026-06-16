"""Feature engineering layer — transform Gold v2 into training-ready features.

Weather mode is already resolved upstream (at ingestion time), so this
layer only needs to know whether to shift weather columns for the
forecast mode or leave them as-is.

Supported modes
---------------
none     : no weather columns present in Gold v2 — energy-only features.
forecast : weather columns present; shift each by -horizon so the feature
           at row t carries the weather value at t+horizon (i.e. at the
           same moment as the target).
"""

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

# All possible weather columns — used to detect which ones are present.
ALL_WEATHER_COLS = [
    "airTemperature",
    "dewTemperature",
    "precipDepth1HR",
    "seaLvlPressure",
    "windDirection",
    "windSpeed",
]


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

    # ------------------------------------------------------------------
    # Feature creation
    # ------------------------------------------------------------------
    @staticmethod
    def create_calendar_features(df: pl.DataFrame) -> pl.DataFrame:
        """Extract calendar columns from timestamp."""
        return df.with_columns([
            pl.col("timestamp").dt.hour().alias("hour"),
            pl.col("timestamp").dt.weekday().alias("day_of_week"),
            pl.col("timestamp").dt.month().alias("month"),
            (pl.col("timestamp").dt.weekday() >= 5).cast(pl.Int8).alias("is_weekend"),
        ])

    @staticmethod
    def create_consumption_features(df: pl.DataFrame) -> pl.DataFrame:
        """Create lag and rolling features per building_id.

        Lag features use strictly past data (shift > 0).
        rolling_std uses min_samples=2 so the first row per group (which
        has only 1 observation) yields null — these rows are removed by
        drop_nulls() downstream rather than being silently filled with 0.
        """
        df = df.sort(["building_id", "timestamp"])
        return df.with_columns([
            # Lag features — all strictly past
            pl.col("consumption").shift(1).over("building_id").alias("lag_1h"),
            pl.col("consumption").shift(24).over("building_id").alias("lag_24h"),
            pl.col("consumption").shift(168).over("building_id").alias("lag_168h"),
            # Rolling mean — min_samples=1 is fine (mean of 1 = that value)
            pl.col("consumption")
            .rolling_mean(window_size=24, min_samples=1)
            .over("building_id").alias("rolling_mean_24h"),
            # Rolling std — needs min_samples=2; first row will be null → dropped
            pl.col("consumption")
            .rolling_std(window_size=24, min_samples=2)
            .over("building_id").alias("rolling_std_24h"),
            pl.col("consumption")
            .rolling_mean(window_size=168, min_samples=1)
            .over("building_id").alias("rolling_mean_168h"),
            pl.col("consumption")
            .rolling_std(window_size=168, min_samples=2)
            .over("building_id").alias("rolling_std_168h"),
        ])

    def create_weather_features(self, df: pl.DataFrame) -> pl.DataFrame:
        """Handle weather columns according to weather_mode.

        none     → no weather columns are present (dropped at ingestion);
                   nothing to do.
        forecast → shift each weather column by -horizon so that the
                   feature value at row t equals weather(t + horizon).
                   Rename to future_<col>.
        """
        present_weather = [c for c in ALL_WEATHER_COLS if c in df.columns]

        if self.weather_mode == "none":
            # Sanity check: ingestion should have removed all weather cols.
            if present_weather:
                raise RuntimeError(
                    f"weather_mode='none' but weather columns found in data: "
                    f"{present_weather}. Check ingestion._apply_weather_mode()."
                )
            return df

        if self.weather_mode == "forecast":
            if not present_weather:
                raise RuntimeError(
                    "weather_mode='forecast' but no weather columns found. "
                    "Check ingestion._apply_weather_mode()."
                )
            df = df.sort(["building_id", "timestamp"])
            shift_exprs = [
                pl.col(c)
                .shift(-self.forecast_horizon_hours)
                .over("building_id")
                .alias(f"future_{c}")
                for c in present_weather
            ]
            return df.with_columns(shift_exprs).drop(present_weather)

        raise ValueError(f"Unknown weather_mode: {self.weather_mode!r}")

    def create_target(self, df: pl.DataFrame) -> pl.DataFrame:
        """Create target = consumption at t + horizon."""
        df = df.sort(["building_id", "timestamp"])
        return df.with_columns(
            pl.col("consumption")
            .shift(-self.forecast_horizon_hours)
            .over("building_id")
            .alias("target"),
        )

    def drop_nulls(self, df: pl.DataFrame) -> pl.DataFrame:
        """Drop rows where ANY feature or the target is null.

        This covers:
        - target null  (last horizon rows per building)
        - lag_1h null  (first row per building)
        - lag_24h/168h null  (first 24/168 rows per building)
        - rolling_std null  (first row per building, min_samples=2)
        - future_weather null (last horizon rows per building, forecast mode)
        - consumption null that survived outlier re-handling (long gaps)
        """
        # Build the full list of columns to check
        feature_cols = [
            c for c in df.columns
            if c not in ("timestamp", "building_id", "target")
        ]
        required = ["target"] + feature_cols

        rows_before = df.shape[0]
        df = df.filter(
            pl.all_horizontal([pl.col(c).is_not_null() for c in required])
        )
        rows_dropped = rows_before - df.shape[0]
        if rows_dropped > 0:
            print(f"    drop_nulls: removed {rows_dropped:,} rows "
                  f"({rows_dropped / rows_before:.2%}) — "
                  "lags/rolling_std boundary + target tail + long-gap consumption")
        return df

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------
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
        df = self.drop_nulls(df)

        rows_out = df.shape[0]
        rows_dropped = rows_in - rows_out
        print(f"    → {rows_out:,} rows remain "
              f"(dropped {rows_dropped:,} / {rows_dropped/rows_in:.1%})")

        # ── Verify zero nulls before saving ────────────────────────
        null_counts = df.select(
            [pl.col(c).is_null().sum().alias(c) for c in df.columns]
        )
        total_nulls = sum(null_counts.row(0))
        if total_nulls > 0:
            bad = {c: null_counts[c][0] for c in df.columns if null_counts[c][0] > 0}
            raise RuntimeError(
                f"Feature store still contains nulls after drop_nulls(): {bad}"
            )
        print("    Null check passed — 0 nulls in feature store.")

        # Save
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = self._build_filename()
        out_path = self.output_dir / filename
        df.write_parquet(out_path)
        print(f"    → Saved: {out_path}")
        print(f"    → {df.shape[0]:,} rows × {df.shape[1]} cols")
        print(f"    → Columns: {df.columns}")

        self._save_reports(df, rows_in, rows_out, rows_dropped)

        elapsed = time.perf_counter() - t0
        print(f"  Feature engineering done in {elapsed:.1f}s")
        return df

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_filename(self) -> str:
        mode_suffix = {
            "none": "energy",
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

        summary = pl.DataFrame({
            "metric": [
                "input_rows", "output_rows", "dropped_rows", "drop_rate",
                "n_buildings", "n_features", "horizon_hours", "weather_mode",
                "null_count",
            ],
            "value": [
                str(rows_in), str(rows_out), str(rows_dropped),
                f"{rows_dropped / rows_in:.4%}",
                str(df["building_id"].n_unique()),
                str(df.shape[1]),
                str(self.forecast_horizon_hours),
                self.weather_mode,
                "0",
            ],
        })
        summary.write_csv(REPORT_DIR / f"fe_{tag}_summary.csv")

        null_summary = df.select(
            [pl.col(c).is_null().mean().alias(c) for c in df.columns]
        ).transpose(
            include_header=True,
            header_name="column",
            column_names=["null_rate"],
        )
        null_summary.write_csv(REPORT_DIR / f"fe_{tag}_null_summary.csv")

        building_counts = (
            df.group_by("building_id")
            .agg(pl.len().alias("n_rows"))
            .sort("n_rows")
        )
        building_counts.write_csv(REPORT_DIR / f"fe_{tag}_building_counts.csv")


# -----------------------------------------------------------------------
# Standalone:  python -m forecasting_module.feature_engineering
# -----------------------------------------------------------------------
if __name__ == "__main__":
    gold_v2_path = GOLD_DIR / "validated_v2_h24_none.parquet"
    if not gold_v2_path.exists():
        sys.exit(
            f"Gold v2 file not found: {gold_v2_path}\n"
            "Run the full pipeline first."
        )

    print(f"Loading Gold v2 from {gold_v2_path} ...")
    gold_v2 = pl.read_parquet(gold_v2_path)
    print(f"  {gold_v2.shape[0]:,} rows × {gold_v2.shape[1]} cols\n")

    FeatureEngineer(
        forecast_horizon_hours=24,
        weather_mode="none",
    ).run(gold_v2)

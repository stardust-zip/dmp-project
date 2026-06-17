"""Outlier detection layer — detect and replace anomalous values in Gold data."""

from __future__ import annotations

import sys
import os
import polars as pl
from pathlib import Path
import plotly.express as px

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))  )

from forecasting_module.config import (
    GOLD_DIR,
    IQR_MULTIPLIER,
    REPORT_DIR,
    WEATHER_BOUNDS,
)

# Whitelist of weather data columns (excludes join keys timestamp/site_id)
WEATHER_DATA_COLS = [
    "airTemperature",
    "dewTemperature",
    "precipDepth1HR",
    "seaLvlPressure",
    "windDirection",
    "windSpeed",
]

# Non-weather, non-consumption columns that must never be mistaken for weather
_NON_WEATHER_COLS = frozenset([
    "timestamp", "building_id", "consumption", "site_id",
    "primaryspaceusage", "sqm", "lat", "lng", "timezone",
])


class OutlierDetector:
    """Detect outliers in Gold data, replace with null, re-run missing handling."""

    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or GOLD_DIR
        self.report_dir = REPORT_DIR

    # ==================================================================
    # EDA
    # ==================================================================
    def eda_analysis(self, df: pl.DataFrame) -> pl.DataFrame:
        """Generate outlier summary statistics and Plotly charts."""
        self.report_dir.mkdir(parents=True, exist_ok=True)
        cons = df.filter(pl.col("consumption").is_not_null())

        building_stats = (
            cons.group_by("building_id")
            .agg(
                pl.len().alias("total_rows"),
                pl.col("consumption").mean().alias("mean"),
                pl.col("consumption").std().alias("std"),
                pl.col("consumption").min().alias("min"),
                pl.col("consumption").quantile(0.25).alias("Q1"),
                pl.col("consumption").quantile(0.50).alias("median"),
                pl.col("consumption").quantile(0.75).alias("Q3"),
                pl.col("consumption").max().alias("max"),
            )
            .with_columns((pl.col("Q3") - pl.col("Q1")).alias("IQR"))
            .sort("std", descending=True)
        )
        building_stats.write_csv(self.report_dir / "outlier_summary.csv")
        print(f"    Saved outlier_summary.csv ({building_stats.shape[0]} buildings)")

        type_stats = (
            cons.group_by("primaryspaceusage")
            .agg(
                pl.len().alias("total_rows"),
                pl.col("consumption").mean().alias("mean"),
                pl.col("consumption").std().alias("std"),
                pl.col("consumption").min().alias("min"),
                pl.col("consumption").quantile(0.25).alias("Q1"),
                pl.col("consumption").quantile(0.75).alias("Q3"),
                pl.col("consumption").max().alias("max"),
            )
            .sort("std", descending=True)
        )
        type_stats.write_csv(self.report_dir / "outlier_by_type.csv")

        self._plot_histogram(cons)
        self._plot_boxplot_by_type(cons)
        self._plot_top20_variance(building_stats)
        return df

    def _plot_histogram(self, df: pl.DataFrame) -> None:
        sample = df.select("consumption").sample(
            min(200_000, df.shape[0]), seed=42
        ).to_pandas()
        fig = px.histogram(
            sample, x="consumption",
            title="Consumption Distribution",
            labels={"consumption": "Consumption (kWh)"},
            nbins=200,
        )
        fig.update_layout(template="plotly_white")
        fig.write_html(str(self.report_dir / "outlier_consumption_histogram.html"))
        print("    Saved outlier_consumption_histogram.html")

    def _plot_boxplot_by_type(self, df: pl.DataFrame) -> None:
        sample = df.select("primaryspaceusage", "consumption").sample(
            min(200_000, df.shape[0]), seed=42
        ).to_pandas()
        fig = px.box(
            sample, x="primaryspaceusage", y="consumption",
            title="Consumption by Building Type",
            labels={"primaryspaceusage": "Building Type",
                    "consumption": "Consumption (kWh)"},
        )
        fig.update_layout(template="plotly_white", xaxis_tickangle=-45)
        fig.write_html(str(self.report_dir / "outlier_boxplot_by_type.html"))
        print("    Saved outlier_boxplot_by_type.html")

    def _plot_top20_variance(self, building_stats: pl.DataFrame) -> None:
        top20 = building_stats.head(20).select("building_id", "std").to_pandas()
        fig = px.bar(
            top20, x="building_id", y="std",
            title="Top 20 Buildings by Consumption Std Dev",
            labels={"building_id": "Building", "std": "Std Dev"},
        )
        fig.update_layout(template="plotly_white", xaxis_tickangle=-45)
        fig.write_html(str(self.report_dir / "outlier_top20_variance.html"))
        print("    Saved outlier_top20_variance.html")

    # ==================================================================
    # Electricity outlier detection
    # ==================================================================
    def detect_electricity_outliers(self, df: pl.DataFrame) -> pl.DataFrame:
        """IQR-based outlier detection per (building_id, hour_of_day).

        Flags values outside [Q1 - IQR_MULTIPLIER*IQR, Q3 + IQR_MULTIPLIER*IQR]
        and replaces them with null for re-imputation.
        """
        df = df.sort(["building_id", "timestamp"])
        df = df.with_columns(
            pl.col("timestamp").dt.hour().alias("_hour"),
        )

        iqr_stats = (
            df.filter(pl.col("consumption").is_not_null())
            .group_by(["building_id", "_hour"])
            .agg(
                pl.col("consumption").quantile(0.25).alias("Q1"),
                pl.col("consumption").quantile(0.75).alias("Q3"),
            )
            .with_columns((pl.col("Q3") - pl.col("Q1")).alias("IQR"))
        )

        df = df.join(iqr_stats, on=["building_id", "_hour"], how="left")

        lower = pl.col("Q1") - IQR_MULTIPLIER * pl.col("IQR")
        upper = pl.col("Q3") + IQR_MULTIPLIER * pl.col("IQR")

        is_outlier = (
            pl.col("consumption").is_not_null()
            & ((pl.col("consumption") < lower) | (pl.col("consumption") > upper))
        )
        df = df.with_columns(is_outlier.fill_null(False).alias("_is_outlier"))

        n_outliers = df.filter(pl.col("_is_outlier")).shape[0]
        total_non_null = df.filter(pl.col("consumption").is_not_null()).shape[0]
        rate = n_outliers / total_non_null if total_non_null > 0 else 0
        print(f"    Electricity outliers: {n_outliers:,} / "
              f"{total_non_null:,} ({rate:.2%})")

        outlier_report = (
            df.group_by("building_id")
            .agg(
                pl.len().alias("total_rows"),
                pl.col("consumption").is_null().sum().alias("null_before"),
                pl.col("consumption").is_not_null().sum().alias("non_null_before"),
                pl.col("_is_outlier").sum().alias("outlier_count"),
            )
            .with_columns(
                (pl.col("outlier_count") / pl.col("non_null_before"))
                .fill_nan(0.0)
                .alias("outlier_rate")
            )
            .sort("outlier_count", descending=True)
        )
        outlier_report.write_csv(
            self.report_dir / "electricity_outlier_report.csv"
        )

        df = (
            df.with_columns(
                pl.when(pl.col("_is_outlier"))
                .then(pl.lit(None).cast(pl.Float64))
                .otherwise(pl.col("consumption"))
                .alias("consumption"),
            )
            .drop(["Q1", "Q3", "IQR", "_hour", "_is_outlier"])
        )
        return df

    # ==================================================================
    # Weather outlier detection
    # ==================================================================
    def detect_weather_outliers(
        self, df: pl.DataFrame, weather_mode: str
    ) -> pl.DataFrame:
        """Replace weather values outside physical bounds with null.

        Only runs when weather_mode != 'none' (i.e. weather columns exist).
        Uses a whitelist (WEATHER_DATA_COLS) to avoid touching non-weather cols.
        """
        if weather_mode == "none":
            return df

        for col, (low, high) in WEATHER_BOUNDS.items():
            if col not in df.columns:
                continue

            checks = []
            if low is not None:
                checks.append(pl.col(col) < low)
            if high is not None:
                checks.append(pl.col(col) > high)
            if not checks:
                continue

            is_oob = pl.col(col).is_not_null() & pl.any_horizontal(checks)
            n = df.filter(is_oob).shape[0]
            if n > 0:
                df = df.with_columns(
                    pl.when(is_oob)
                    .then(pl.lit(None).cast(pl.Float64))
                    .otherwise(pl.col(col))
                    .alias(col),
                )
                print(f"    Weather '{col}': replaced {n:,} out-of-bounds values")
            else:
                print(f"    Weather '{col}': no out-of-bounds values")

        return df

    # ==================================================================
    # Re-handle missing after outlier replacement
    # ==================================================================
    def rehandle_missing(
        self,
        df: pl.DataFrame,
        preprocessor,
        run_tag: str,
        weather_mode: str,
    ) -> pl.DataFrame:
        """Re-apply missing-value handling after outlier → null replacement."""
        print("  Re-handling missing consumption ...")
        df = preprocessor.handle_missing_consumption(df)

        # Only re-clean weather if columns are present
        present_weather = [c for c in WEATHER_DATA_COLS if c in df.columns]
        if present_weather and weather_mode != "none":
            print("  Re-handling missing weather ...")
            weather = df.select(
                ["timestamp", "site_id"] + present_weather
            ).unique(subset=["timestamp", "site_id"])
            weather = preprocessor.clean_weather(weather)

            base = df.drop(present_weather)
            df = base.join(
                weather,
                on=["timestamp", "site_id"],
                how="left",
            ).sort(["building_id", "timestamp"])
        else:
            print("  No weather columns to re-handle (weather_mode='none').")

        # ── Verify remaining nulls in consumption ──────────────────
        remaining_consumption_nulls = (
            df.filter(pl.col("consumption").is_null()).shape[0]
        )
        print(f"    Remaining consumption nulls after re-handle: "
              f"{remaining_consumption_nulls:,} (long-gap rows — will be "
              "removed by drop_nulls in Feature Engineering)")

        # Save Gold v2 with run_tag in filename
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / f"validated_v2_{run_tag}.parquet"
        df.write_parquet(out_path)
        print(f"    → Saved Gold v2: {out_path}")
        print(f"    → {df.shape[0]:,} rows × {df.shape[1]} cols")

        null_summary = df.select(
            [pl.col(c).is_null().mean().alias(c) for c in df.columns]
        ).transpose(
            include_header=True,
            header_name="column",
            column_names=["null_rate"],
        )
        null_summary.write_csv(
            self.report_dir / f"gold_v2_{run_tag}_null_summary.csv"
        )
        return df

    # ==================================================================
    # Runner
    # ==================================================================
    def run(
        self,
        df: pl.DataFrame,
        preprocessor,
        run_tag: str = "h24_none",
        weather_mode: str = "none",
    ) -> pl.DataFrame:
        """Execute full outlier detection pipeline."""
        print("  EDA outlier analysis ...")
        df = self.eda_analysis(df)

        print("  Detecting electricity outliers ...")
        df = self.detect_electricity_outliers(df)

        print("  Detecting weather outliers ...")
        df = self.detect_weather_outliers(df, weather_mode=weather_mode)

        df = self.rehandle_missing(
            df, preprocessor, run_tag=run_tag, weather_mode=weather_mode
        )
        return df


# -----------------------------------------------------------------------
# Standalone
# -----------------------------------------------------------------------
if __name__ == "__main__":
    from forecasting_module.preprocessing import Preprocessor

    gold_path = GOLD_DIR / "validated_h24_none.parquet"
    if not gold_path.exists():
        sys.exit(f"Gold file not found: {gold_path}\nRun the full pipeline first.")

    print(f"Loading Gold from {gold_path} ...")
    gold = pl.read_parquet(gold_path)
    print(f"  {gold.shape[0]:,} rows × {gold.shape[1]} cols\n")

    OutlierDetector().run(
        gold, Preprocessor(), run_tag="h24_none", weather_mode="none"
    )

"""Outlier detection layer — detect and replace anomalous values in Gold data."""

from __future__ import annotations

import sys
import os
import polars as pl
from pathlib import Path
import plotly.express as px
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from forecasting_module.config import (
    GOLD_DIR,
    IQR_MULTIPLIER,
    REPORT_DIR,
    WEATHER_BOUNDS,
)


class OutlierDetector:
    """Detect outliers in Gold data, replace with NaN, re-run missing handling.

    Tasks 2.1–2.4 from nextphase.md.
    """

    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or GOLD_DIR
        self.report_dir = REPORT_DIR

    # ==================================================================
    # Task 2.1: EDA Outlier Analysis
    # ==================================================================
    def eda_analysis(self, df: pl.DataFrame) -> pl.DataFrame:
        """Generate outlier summary statistics and Plotly charts."""
        self.report_dir.mkdir(parents=True, exist_ok=True)

        cons = df.filter(pl.col("consumption").is_not_null())

        # --- Per-building stats ---
        building_stats = cons.group_by("building_id").agg(
            pl.len().alias("total_rows"),
            pl.col("consumption").mean().alias("mean"),
            pl.col("consumption").std().alias("std"),
            pl.col("consumption").min().alias("min"),
            pl.col("consumption").quantile(0.25).alias("Q1"),
            pl.col("consumption").quantile(0.50).alias("median"),
            pl.col("consumption").quantile(0.75).alias("Q3"),
            pl.col("consumption").max().alias("max"),
        ).with_columns(
            (pl.col("Q3") - pl.col("Q1")).alias("IQR"),
        ).sort("std", descending=True)

        building_stats.write_csv(self.report_dir / "outlier_summary.csv")
        print(f"    Saved outlier_summary.csv ({building_stats.shape[0]} buildings)")

        # --- Per-building-type stats ---
        type_stats = cons.group_by("primaryspaceusage").agg(
            pl.len().alias("total_rows"),
            pl.col("consumption").mean().alias("mean"),
            pl.col("consumption").std().alias("std"),
            pl.col("consumption").min().alias("min"),
            pl.col("consumption").quantile(0.25).alias("Q1"),
            pl.col("consumption").quantile(0.75).alias("Q3"),
            pl.col("consumption").max().alias("max"),
        ).sort("std", descending=True)
        type_stats.write_csv(self.report_dir / "outlier_by_type.csv")

        # --- Plotly charts ---
        self._plot_histogram(cons)
        self._plot_boxplot_by_type(cons)
        self._plot_top20_variance(building_stats)

        return df

    def _plot_histogram(self, df: pl.DataFrame) -> None:
        """Consumption histogram."""
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
        path = self.report_dir / "outlier_consumption_histogram.html"
        fig.write_html(str(path))
        print(f"    Saved outlier_consumption_histogram.html")

    def _plot_boxplot_by_type(self, df: pl.DataFrame) -> None:
        """Boxplot by primaryspaceusage."""
        sample = df.select("primaryspaceusage", "consumption").sample(
            min(200_000, df.shape[0]), seed=42
        ).to_pandas()
        fig = px.box(
            sample, x="primaryspaceusage", y="consumption",
            title="Consumption by Building Type",
            labels={"primaryspaceusage": "Building Type", "consumption": "Consumption (kWh)"},
        )
        fig.update_layout(template="plotly_white", xaxis_tickangle=-45)
        path = self.report_dir / "outlier_boxplot_by_type.html"
        fig.write_html(str(path))
        print(f"    Saved outlier_boxplot_by_type.html")

    def _plot_top20_variance(self, building_stats: pl.DataFrame) -> None:
        """Bar chart of top 20 highest-variance buildings."""
        top20 = building_stats.head(20).select("building_id", "std").to_pandas()
        fig = px.bar(
            top20, x="building_id", y="std",
            title="Top 20 Buildings by Consumption Std Dev",
            labels={"building_id": "Building", "std": "Std Dev"},
        )
        fig.update_layout(template="plotly_white", xaxis_tickangle=-45)
        path = self.report_dir / "outlier_top20_variance.html"
        fig.write_html(str(path))
        print(f"    Saved outlier_top20_variance.html")

    # ==================================================================
    # Task 2.2: Electricity Outlier Detection (IQR)
    # ==================================================================
    def detect_electricity_outliers(self, df: pl.DataFrame) -> pl.DataFrame:
        """Detect electricity outliers using IQR by (building_id, hour_of_day).

        Flags values outside [Q1 - 3*IQR, Q3 + 3*IQR] per group.
        Replaces flagged values with NaN.
        """
        df = df.sort(["building_id", "timestamp"])

        # Add hour column for grouping
        df = df.with_columns(
            pl.col("timestamp").dt.hour().alias("_hour"),
        )

        # Compute Q1, Q3, IQR per (building_id, hour)
        iqr_stats = (
            df.filter(pl.col("consumption").is_not_null())
            .group_by(["building_id", "_hour"])
            .agg([
                pl.col("consumption").quantile(0.25).alias("Q1"),
                pl.col("consumption").quantile(0.75).alias("Q3"),
            ])
            .with_columns(
                (pl.col("Q3") - pl.col("Q1")).alias("IQR"),
            )
        )

        # Join stats back and flag outliers
        df = df.join(iqr_stats, on=["building_id", "_hour"], how="left")

        lower = pl.col("Q1") - IQR_MULTIPLIER * pl.col("IQR")
        upper = pl.col("Q3") + IQR_MULTIPLIER * pl.col("IQR")

        is_outlier = (
            pl.col("consumption").is_not_null()
            & (
                (pl.col("consumption") < lower)
                | (pl.col("consumption") > upper)
            )
        )

        # Keep an explicit flag before replacing values. This makes the
        # report count true outliers only, not pre-existing null values.
        df = df.with_columns(is_outlier.fill_null(False).alias("_is_outlier"))

        n_outliers = df.filter(pl.col("_is_outlier")).shape[0]
        total_non_null_before = df.filter(pl.col("consumption").is_not_null()).shape[0]
        rate = n_outliers / total_non_null_before if total_non_null_before > 0 else 0
        print(
            f"    Electricity outliers: {n_outliers:,} / "
            f"{total_non_null_before:,} ({rate:.2%})"
        )

        # Per-building outlier report before replacement.
        outlier_report = (
            df.group_by("building_id")
            .agg([
                pl.len().alias("total_rows"),
                pl.col("consumption").is_null().sum().alias("null_before"),
                pl.col("consumption").is_not_null().sum().alias("non_null_before"),
                pl.col("_is_outlier").sum().alias("outlier_count"),
            ])
            .with_columns(
                (pl.col("outlier_count") / pl.col("non_null_before"))
                .fill_nan(0.0)
                .alias("outlier_rate")
            )
            .sort("outlier_count", descending=True)
        )
        outlier_report.write_csv(self.report_dir / "electricity_outlier_report.csv")

        # Replace true outliers with null so the missing-value pipeline can
        # impute them consistently.
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
    # Task 2.3: Weather Outlier Detection (rule-based)
    # ==================================================================
    def detect_weather_outliers(self, df: pl.DataFrame) -> pl.DataFrame:
        """Replace weather values outside physical bounds with NaN."""
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
    # Task 2.4: Re-run Missing Handling Pipeline
    # ==================================================================
    def rehandle_missing(
        self,
        df: pl.DataFrame,
        preprocessor,
    ) -> pl.DataFrame:
        """Re-apply missing handling after outlier → NaN replacement."""
        print("  Re-handling missing consumption ...")
        df = preprocessor.handle_missing_consumption(df)

        print("  Re-handling missing weather ...")
        # Extract weather subset, clean, merge back
        weather_cols = ["timestamp", "site_id"]
        weather_data_cols = [
            c for c in df.columns
            if c not in (
                "timestamp", "building_id", "consumption", "site_id",
                "primaryspaceusage", "sqm", "lat", "lng", "timezone",
            )
        ]
        if weather_data_cols:
            weather = df.select(weather_cols + weather_data_cols).unique(
                subset=["timestamp", "site_id"]
            )
            weather = preprocessor.clean_weather(weather)

            # Re-join cleaned weather
            base = df.drop(weather_data_cols)
            df = base.join(
                weather,
                on=["timestamp", "site_id"],
                how="left",
            ).sort(["building_id", "timestamp"])

        # Save Gold v2
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / "validated_v2.parquet"
        df.write_parquet(out_path)
        print(f"    → Saved Gold v2: {out_path}")
        print(f"    → {df.shape[0]:,} rows × {df.shape[1]} cols")

        # Null summary
        null_summary = df.select(
            [pl.col(c).is_null().mean().alias(c) for c in df.columns]
        ).transpose(include_header=True, header_name="column",
                    column_names=["null_rate"])
        null_summary.write_csv(self.report_dir / "gold_v2_null_summary.csv")

        return df

    # ==================================================================
    # Runner
    # ==================================================================
    def run(self, df: pl.DataFrame, preprocessor) -> pl.DataFrame:
        """Execute full outlier detection pipeline."""
        print("  EDA outlier analysis ...")
        df = self.eda_analysis(df)

        print("  Detecting electricity outliers ...")
        df = self.detect_electricity_outliers(df)

        print("  Detecting weather outliers ...")
        df = self.detect_weather_outliers(df)

        df = self.rehandle_missing(df, preprocessor)
        return df


# -----------------------------------------------------------------------
# Standalone:  python -m forecasting_module.outlier
# -----------------------------------------------------------------------
if __name__ == "__main__":
    from forecasting_module.preprocessing import Preprocessor

    gold_path = GOLD_DIR / "validated.parquet"
    if not gold_path.exists():
        sys.exit(f"Gold file not found: {gold_path}\nRun the full pipeline first.")

    print(f"Loading Gold from {gold_path} ...")
    gold = pl.read_parquet(gold_path)
    print(f"  {gold.shape[0]:,} rows × {gold.shape[1]} cols\n")

    OutlierDetector().run(gold, Preprocessor())

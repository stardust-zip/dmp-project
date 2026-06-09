"""Preprocessing layer — clean, align, and merge time-series data into Silver."""

from __future__ import annotations

from pathlib import Path
import os
import sys
import polars as pl
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from forecasting_module.config import INTERP_MAX_GAP_HOURS, SILVER_DIR


class Preprocessor:
    """Transform Bronze data into a clean, merged Silver-layer dataset."""

    def __init__(
        self,
        output_dir: Path = SILVER_DIR,
        interp_max_gap: int = INTERP_MAX_GAP_HOURS,
    ):
        self.output_dir = output_dir
        self.interp_max_gap = interp_max_gap

    # ------------------------------------------------------------------
    # 1. Time alignment
    # ------------------------------------------------------------------
    def align_timestamps(self, electricity: pl.DataFrame) -> pl.DataFrame:
        """Ensure a complete hourly grid for every building.

        Creates the Cartesian product (all hourly timestamps × all
        building_ids), then left-joins the actual consumption data.
        Missing rows become null consumption — to be interpolated later.
        """
        min_ts = electricity["timestamp"].min()
        max_ts = electricity["timestamp"].max()

        full_hours = pl.DataFrame(
            {"timestamp": pl.datetime_range(min_ts, max_ts, "1h", eager=True)}
        )
        buildings = electricity.select("building_id").unique()

        grid = full_hours.join(buildings, how="cross")

        aligned = grid.join(
            electricity,
            on=["timestamp", "building_id"],
            how="left",
        ).sort(["building_id", "timestamp"])

        n_filled = aligned.filter(pl.col("consumption").is_null()).shape[0]
        total = aligned.shape[0]
        print(f"    Grid: {total:,} rows, {n_filled:,} nulls "
              f"({n_filled / total:.1%})")
        return aligned

    # ------------------------------------------------------------------
    # 2. Missing value interpolation
    # ------------------------------------------------------------------
    def handle_missing_consumption(self, df: pl.DataFrame) -> pl.DataFrame:
        """Linear-interpolate consumption gaps ≤ *interp_max_gap* hours.

        Longer gaps (likely real outages) stay null and will be excluded
        from training later.
        """
        df = df.sort(["building_id", "timestamp"])
        col = "consumption"
        group = "building_id"
        limit = self.interp_max_gap

        is_null = pl.col(col).is_null()

        # Unique run-id per consecutive (building, null-status) segment
        boundary = (
            (is_null != is_null.shift(1).over(group)).fill_null(True)
            | (pl.col(group) != pl.col(group).shift(1)).fill_null(True)
        )
        run_id = boundary.cast(pl.Int32).cum_sum()

        # Length of each null run
        run_len = is_null.cast(pl.UInt32).sum().over(run_id)

        # Interpolate per building, then mask-out long gaps
        interpolated = pl.col(col).interpolate().over(group)

        before = df.filter(is_null).shape[0]
        df = df.with_columns(
            pl.when(is_null & (run_len > limit))
            .then(pl.lit(None).cast(pl.Float64))
            .otherwise(interpolated)
            .alias(col),
        )
        after = df.filter(pl.col(col).is_null()).shape[0]
        filled = before - after
        print(f"    Interpolated {filled:,} / {before:,} null values "
              f"(gap ≤ {limit}h)")
        return df

    # ------------------------------------------------------------------
    # 3. Weather cleaning
    # ------------------------------------------------------------------
    def clean_weather(self, weather: pl.DataFrame) -> pl.DataFrame:
        """Forward-fill missing weather values within each site.

        Weather data is already hourly per site. Short gaps are filled
        with the last valid observation.
        """
        weather = weather.sort(["site_id", "timestamp"])
        numeric_cols = [
            c for c in weather.columns
            if c not in ("timestamp", "site_id")
            and weather[c].dtype.is_numeric()
        ]

        before = weather.select(
            [pl.col(c).is_null().sum().alias(c) for c in numeric_cols]
        )
        weather = weather.with_columns(
            [pl.col(c).forward_fill().over("site_id") for c in numeric_cols]
        )
        after = weather.select(
            [pl.col(c).is_null().sum().alias(c) for c in numeric_cols]
        )
        for c in numeric_cols:
            diff = before[c][0] - after[c][0]
            if diff > 0:
                print(f"    Weather '{c}': forward-filled {diff:,} nulls")
        return weather

    # ------------------------------------------------------------------
    # 4. Merge
    # ------------------------------------------------------------------
    def merge(
        self,
        electricity: pl.DataFrame,
        metadata: pl.DataFrame,
        weather: pl.DataFrame,
    ) -> pl.DataFrame:
        """Join electricity + metadata + weather into one Silver table.

        - electricity ← metadata  on building_id
        - result      ← weather   on (timestamp, site_id)
        """
        merged = electricity.join(metadata, on="building_id", how="left")
        print(f"    After metadata join: {merged.shape[1]} cols")

        merged = merged.join(
            weather,
            on=["timestamp", "site_id"],
            how="left",
        )
        print(f"    After weather join:  {merged.shape[1]} cols")

        return merged.sort(["building_id", "timestamp"])

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------
    def run(self, bronze: dict[str, pl.DataFrame]) -> pl.DataFrame:
        """Execute full preprocessing pipeline → Silver Parquet."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        print("  Aligning timestamps ...")
        electricity = self.align_timestamps(bronze["electricity"])

        print("  Handling missing consumption ...")
        electricity = self.handle_missing_consumption(electricity)

        print("  Cleaning weather ...")
        weather = self.clean_weather(bronze["weather"])

        print("  Merging all sources ...")
        silver = self.merge(electricity, bronze["metadata"], weather)

        silver.write_parquet(self.output_dir / "merged.parquet")
        print(f"    → Saved Silver: {silver.shape[0]:,} rows × {silver.shape[1]} cols")
        return silver

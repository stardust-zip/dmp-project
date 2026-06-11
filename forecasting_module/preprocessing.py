"""Preprocessing layer — clean, align, and merge time-series data into Silver."""

from __future__ import annotations

from pathlib import Path
import os
import sys
import polars as pl
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from forecasting_module.config import (
    INTERP_MAX_GAP_HOURS,
    MISSING_RATE_THRESHOLD,
    REPORT_DIR,
    SEASONAL_MAX_GAP_HOURS,
    SILVER_DIR,
)


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
    @staticmethod
    def _compute_null_run_lengths(col: str, group: str):
        """Return (run_id, run_len) expressions for consecutive null runs."""
        is_null = pl.col(col).is_null()
        boundary = (
            (is_null != is_null.shift(1).over(group)).fill_null(True)
            | (pl.col(group) != pl.col(group).shift(1)).fill_null(True)
        )
        run_id = boundary.cast(pl.Int32).cum_sum()
        run_len = is_null.cast(pl.UInt32).sum().over(run_id)
        return run_id, run_len

    def handle_missing_consumption(self, df: pl.DataFrame) -> pl.DataFrame:
        """Handle missing consumption: drop high-missing buildings, interpolate
        short gaps, seasonal-fill medium gaps, keep null for long gaps.
        """
        df = df.sort(["building_id", "timestamp"])
        col = "consumption"
        group = "building_id"

        # --- Step 0: Drop buildings with missing rate > threshold ---
        missing_rate = (
            df.group_by(group)
            .agg((pl.col(col).is_null().sum() / pl.len()).alias("missing_rate"))
        )
        dropped = missing_rate.filter(
            pl.col("missing_rate") > MISSING_RATE_THRESHOLD
        )
        n_dropped = dropped.shape[0]
        if n_dropped > 0:
            valid_buildings = missing_rate.filter(
                pl.col("missing_rate") <= MISSING_RATE_THRESHOLD
            ).select(group)
            df = df.join(valid_buildings, on=group, how="inner")
            print(f"    Dropped {n_dropped} buildings "
                  f"(>{MISSING_RATE_THRESHOLD:.0%} missing rate)")

        # --- Step 1: Linear interpolation for gaps ≤ interp_max_gap ---
        is_null = pl.col(col).is_null()
        run_id, run_len = self._compute_null_run_lengths(col, group)

        interpolated = pl.col(col).interpolate().over(group)

        before_interp = df.filter(is_null).shape[0]
        df = df.with_columns(
            pl.when(is_null & (run_len > self.interp_max_gap))
            .then(pl.lit(None).cast(pl.Float64))
            .otherwise(interpolated)
            .alias(col),
        )
        after_interp = df.filter(pl.col(col).is_null()).shape[0]
        filled_interp = before_interp - after_interp
        print(f"    Interpolated {filled_interp:,} values (gap ≤ {self.interp_max_gap}h)")

        # --- Step 2: Seasonal imputation (t-24h) for 6h < gap ≤ 24h ---
        is_null = pl.col(col).is_null()
        run_id, run_len = self._compute_null_run_lengths(col, group)
        seasonal_val = pl.col(col).shift(24).over(group)

        before_seasonal = df.filter(is_null).shape[0]
        df = df.with_columns(
            pl.when(
                is_null
                & (run_len > self.interp_max_gap)
                & (run_len <= SEASONAL_MAX_GAP_HOURS)
                & seasonal_val.is_not_null()
            )
            .then(seasonal_val)
            .otherwise(pl.col(col))
            .alias(col),
        )
        after_seasonal = df.filter(pl.col(col).is_null()).shape[0]
        filled_seasonal = before_seasonal - after_seasonal
        if filled_seasonal > 0:
            print(f"    Seasonal-filled {filled_seasonal:,} values "
                  f"(gap {self.interp_max_gap}h–{SEASONAL_MAX_GAP_HOURS}h)")

        remaining = df.filter(pl.col(col).is_null()).shape[0]
        print(f"    Remaining nulls: {remaining:,} (gap > {SEASONAL_MAX_GAP_HOURS}h)")
        return df

    # ------------------------------------------------------------------
    # 3. Weather cleaning
    # ------------------------------------------------------------------
    def clean_weather(self, weather: pl.DataFrame) -> pl.DataFrame:
        """Gap-based weather cleaning: interpolate ≤6h, seasonal 6h-24h,
        median by (site_id, month, hour) for >24h.
        """
        weather = weather.sort(["site_id", "timestamp"])
        numeric_cols = [
            c for c in weather.columns
            if c not in ("timestamp", "site_id")
            and weather[c].dtype.is_numeric()
        ]

        total_before = weather.select(
            [pl.col(c).is_null().sum().alias(c) for c in numeric_cols]
        )

        # --- Tier 1: Linear interpolation for gaps ≤ 6h ---
        # Interpolate all, then mask back to null for gaps > 6h
        for c in numeric_cols:
            is_null = pl.col(c).is_null()
            run_id, run_len = self._compute_null_run_lengths(c, "site_id")
            interpolated = pl.col(c).interpolate().over("site_id")
            weather = weather.with_columns(
                pl.when(is_null & (run_len > INTERP_MAX_GAP_HOURS))
                .then(pl.lit(None).cast(pl.Float64))
                .otherwise(interpolated)
                .alias(c),
            )

        after_t1 = weather.select(
            [pl.col(c).is_null().sum().alias(c) for c in numeric_cols]
        )

        # --- Tier 2: Seasonal imputation (t-24h, then t+24h) for 6h < gap ≤ 24h ---
        for c in numeric_cols:
            is_null = pl.col(c).is_null()
            run_id, run_len = self._compute_null_run_lengths(c, "site_id")
            shifted_back = pl.col(c).shift(24).over("site_id")
            shifted_fwd = pl.col(c).shift(-24).over("site_id")
            in_medium_gap = (run_len > INTERP_MAX_GAP_HOURS) & (run_len <= SEASONAL_MAX_GAP_HOURS)

            weather = weather.with_columns(
                pl.when(is_null & in_medium_gap)
                .then(
                    pl.when(shifted_back.is_not_null()).then(shifted_back)
                    .otherwise(shifted_fwd)
                )
                .otherwise(pl.col(c))
                .alias(c),
            )

        after_t2 = weather.select(
            [pl.col(c).is_null().sum().alias(c) for c in numeric_cols]
        )

        # --- Tier 3: Median by (site_id, month, hour) for remaining nulls ---
        weather = weather.with_columns([
            pl.col("timestamp").dt.month().alias("_month"),
            pl.col("timestamp").dt.hour().alias("_hour"),
        ])

        for c in numeric_cols:
            remaining_nulls = weather.filter(pl.col(c).is_null()).shape[0]
            if remaining_nulls == 0:
                continue

            median_lookup = (
                weather.filter(pl.col(c).is_not_null())
                .group_by(["site_id", "_month", "_hour"])
                .agg(pl.col(c).median().alias(f"{c}_median"))
            )

            # Join median back for null positions only
            weather = weather.join(
                median_lookup,
                on=["site_id", "_month", "_hour"],
                how="left",
            ).with_columns(
                pl.when(pl.col(c).is_null())
                .then(pl.col(f"{c}_median"))
                .otherwise(pl.col(c))
                .alias(c),
            ).drop(f"{c}_median")

        weather = weather.drop(["_month", "_hour"])

        after_t3 = weather.select(
            [pl.col(c).is_null().sum().alias(c) for c in numeric_cols]
        )

        # Print per-column stats
        for c in numeric_cols:
            total = total_before[c][0]
            if total == 0:
                continue
            t1 = total - after_t1[c][0]
            t2 = after_t1[c][0] - after_t2[c][0]
            t3 = after_t2[c][0] - after_t3[c][0]
            print(f"    Weather '{c}': {t1:,} interp, {t2:,} seasonal, "
                  f"{t3:,} median  (was {total:,} nulls)")

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

        # Null summary
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        null_summary = silver.select(
            [pl.col(c).is_null().mean().alias(c) for c in silver.columns]
        ).transpose(include_header=True, header_name="column",
                    column_names=["null_rate"])
        null_summary.write_csv(REPORT_DIR / "silver_null_summary.csv")

        null_by_building = silver.group_by("building_id").agg(
            pl.col("consumption").is_null().mean().alias("consumption_null_rate")
        ).sort("consumption_null_rate", descending=True)
        null_by_building.write_csv(REPORT_DIR / "silver_null_by_building.csv")

        return silver

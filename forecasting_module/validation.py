"""Validation layer — quality checks on Silver data before Gold output."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from forecasting_module.config import GOLD_DIR


class DataValidator:
    """Run data-quality checks and produce Gold-layer output.

    Each check appends a result dict to ``self.report``:
    ``{"check": str, "passed": bool, "detail": str}``

    Auto-fixable issues (duplicates, negatives) are corrected before
    saving. Other issues are reported but not silently altered.
    """

    # Minimal schema every Gold output must satisfy
    REQUIRED_COLUMNS = {
        "timestamp":        pl.Datetime,
        "building_id":      pl.Utf8,
        "consumption":      pl.Float64,
        "site_id":          pl.Utf8,
        "primaryspaceusage": pl.Utf8,
        "sqm":              pl.Float64,
    }

    def __init__(self, output_dir: Path = GOLD_DIR):
        self.output_dir = output_dir
        self.report: list[dict] = []

    # ==================================================================
    # Public API
    # ==================================================================
    def run(self, df: pl.DataFrame) -> pl.DataFrame:
        """Validate, auto-fix, and save Gold Parquet.

        Returns the (possibly corrected) Gold DataFrame.
        """
        self.report = []

        print("  Running validation checks ...")
        self._check_required_columns(df)
        self._check_no_duplicates(df)
        self._check_no_negative_consumption(df)
        self._check_timestamp_range(df)
        self._report_missingness(df)

        # Auto-fixes
        df = self._fix_duplicates(df)
        df = self._fix_negative_consumption(df)

        # Print report
        all_passed = all(r["passed"] for r in self.report)
        for r in self.report:
            icon = "✅" if r["passed"] else "⚠️"
            print(f"    {icon} {r['check']}: {r['detail']}")

        # Persist Gold
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / "validated.parquet"
        df.write_parquet(out_path)
        print(f"\n  → Saved Gold: {out_path}")
        print(f"  → {df.shape[0]:,} rows × {df.shape[1]} cols")

        if not all_passed:
            print("\n  ⚠️  Some checks raised warnings — review above.")

        return df

    # ==================================================================
    # Checks
    # ==================================================================
    def _check_required_columns(self, df: pl.DataFrame) -> None:
        missing = set(self.REQUIRED_COLUMNS) - set(df.columns)
        self.report.append({
            "check": "required_columns",
            "passed": len(missing) == 0,
            "detail": f"Missing: {missing}" if missing else "All present",
        })

    def _check_no_duplicates(self, df: pl.DataFrame) -> None:
        n = df.filter(
            pl.struct("timestamp", "building_id").is_duplicated()
        ).shape[0]
        self.report.append({
            "check": "no_duplicates",
            "passed": n == 0,
            "detail": f"{n:,} duplicate (timestamp, building_id) pairs"
                      if n else "No duplicates",
        })

    def _check_no_negative_consumption(self, df: pl.DataFrame) -> None:
        n = df.filter(
            pl.col("consumption").is_not_null() & (pl.col("consumption") < 0)
        ).shape[0]
        self.report.append({
            "check": "no_negative_consumption",
            "passed": n == 0,
            "detail": f"{n:,} negative values" if n else "No negatives",
        })

    def _check_timestamp_range(self, df: pl.DataFrame) -> None:
        min_ts = df["timestamp"].min()
        max_ts = df["timestamp"].max()
        ok = (
            min_ts >= datetime(2016, 1, 1)
            and max_ts <= datetime(2017, 12, 31, 23, 0, 0)
        )
        self.report.append({
            "check": "timestamp_range",
            "passed": ok,
            "detail": f"{min_ts} → {max_ts}",
        })

    def _report_missingness(self, df: pl.DataFrame) -> None:
        rates = df.select(
            pl.all().is_null().mean()
        )
        high_missing = {
            c: f"{rates[c][0]:.1%}"
            for c in rates.columns
            if rates[c][0] > 0.50
        }
        self.report.append({
            "check": "missingness",
            "passed": len(high_missing) == 0,
            "detail": high_missing if high_missing else "No column >50% null",
        })

    # ==================================================================
    # Auto-fixes
    # ==================================================================
    def _fix_duplicates(self, df: pl.DataFrame) -> pl.DataFrame:
        before = df.shape[0]
        df = df.unique(subset=["timestamp", "building_id"], maintain_order=True)
        removed = before - df.shape[0]
        if removed:
            print(f"    Fixed: removed {removed:,} duplicate rows")
        return df

    @staticmethod
    def _fix_negative_consumption(df: pl.DataFrame) -> pl.DataFrame:
        n = df.filter(
            pl.col("consumption").is_not_null() & (pl.col("consumption") < 0)
        ).shape[0]
        if n:
            df = df.with_columns(
                pl.when(pl.col("consumption") < 0)
                .then(None)
                .otherwise(pl.col("consumption"))
                .alias("consumption"),
            )
            print(f"    Fixed: nullified {n:,} negative consumption values")
        return df


# -----------------------------------------------------------------------
# Standalone:  python -m forecasting_module.validation
# -----------------------------------------------------------------------
if __name__ == "__main__":
    from forecasting_module.config import SILVER_DIR

    silver_path = SILVER_DIR / "merged.parquet"
    if not silver_path.exists():
        sys.exit(f"Silver file not found: {silver_path}\nRun the full pipeline first.")

    print(f"Loading Silver from {silver_path} ...")
    silver = pl.read_parquet(silver_path)
    print(f"  {silver.shape[0]:,} rows × {silver.shape[1]} cols\n")

    DataValidator().run(silver)

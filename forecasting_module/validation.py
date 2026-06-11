"""Validation layer — quality checks on Silver data before Gold output."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from forecasting_module.config import GOLD_DIR, REPORT_DIR


class DataValidator:
    """Run data-quality checks and produce Gold-layer output.

    Each check appends a result dict to ``self.report``:
    ``{"check": str, "passed": bool, "severity": str, "detail": str}``

    Auto-fixable issues (duplicates, negatives, invalid metadata) are
    corrected before saving. Other issues are reported but not silently
    altered.
    """

    # Base schema every Gold output must satisfy
    REQUIRED_BASE_COLUMNS = {
        "timestamp":         pl.Datetime,
        "building_id":       pl.Utf8,
        "consumption":       pl.Float64,
        "site_id":           pl.Utf8,
        "primaryspaceusage": pl.Utf8,
        "sqm":               pl.Float64,
    }

    REQUIRED_WEATHER_COLUMNS = {
        "airTemperature":  pl.Float64,
        "dewTemperature":  pl.Float64,
        "precipDepth1HR":  pl.Float64,
        "seaLvlPressure":  pl.Float64,
        "windDirection":   pl.Float64,
        "windSpeed":       pl.Float64,
    }

    def __init__(self, output_dir: Path = GOLD_DIR):
        self.output_dir = output_dir
        self.report: list[dict] = []
        self._fix_log: list[str] = []

    # ==================================================================
    # Public API
    # ==================================================================
    def run(
        self,
        df: pl.DataFrame,
        electricity: pl.DataFrame | None = None,
        metadata: pl.DataFrame | None = None,
        weather: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """Validate, auto-fix, and save Gold Parquet.

        Returns the (possibly corrected) Gold DataFrame.
        """
        self.report = []
        self._fix_log = []

        print("  Running validation checks ...")
        self._check_required_columns(df)
        self._check_no_duplicates(df)
        self._check_no_negative_consumption(df)
        self._check_timestamp_range(df)
        self._check_metadata(df)
        self._report_missingness(df)

        if electricity is not None:
            self._check_merge_coverage(df, electricity, metadata, weather)

        # Auto-fixes
        df = self._fix_duplicates(df)
        df = self._fix_negative_consumption(df)
        df = self._fix_metadata(df)

        # Print report
        self._print_report()

        # Null summary
        self._save_null_summary(df)

        # Write structured report
        self._write_report(df.shape)

        # Persist Gold
        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / "validated.parquet"
        df.write_parquet(out_path)
        print(f"\n  → Saved Gold: {out_path}")
        print(f"  → {df.shape[0]:,} rows × {df.shape[1]} cols")

        return df

    # ==================================================================
    # Checks
    # ==================================================================
    def _check_required_columns(self, df: pl.DataFrame) -> None:
        # Base schema
        missing_base = set(self.REQUIRED_BASE_COLUMNS) - set(df.columns)
        self.report.append({
            "check": "required_base_columns",
            "passed": len(missing_base) == 0,
            "severity": "critical",
            "detail": f"Missing base columns: {missing_base}"
                      if missing_base else "All base columns present",
        })

        # Weather schema
        missing_weather = set(self.REQUIRED_WEATHER_COLUMNS) - set(df.columns)
        self.report.append({
            "check": "required_weather_columns",
            "passed": len(missing_weather) == 0,
            "severity": "critical",
            "detail": f"Missing weather columns: {missing_weather}"
                      if missing_weather else "All weather columns present",
        })

        # Dtype checks
        all_required = {**self.REQUIRED_BASE_COLUMNS,
                        **self.REQUIRED_WEATHER_COLUMNS}
        dtype_mismatches = {}
        for col_name, expected_dtype in all_required.items():
            if col_name in df.columns and df[col_name].dtype != expected_dtype:
                dtype_mismatches[col_name] = (
                    f"expected {expected_dtype}, got {df[col_name].dtype}"
                )
        self.report.append({
            "check": "column_dtypes",
            "passed": len(dtype_mismatches) == 0,
            "severity": "critical",
            "detail": f"Dtype mismatches: {dtype_mismatches}"
                      if dtype_mismatches else "All dtypes match",
        })

    def _check_no_duplicates(self, df: pl.DataFrame) -> None:
        n = df.filter(
            pl.struct("timestamp", "building_id").is_duplicated()
        ).shape[0]
        self.report.append({
            "check": "no_duplicates",
            "passed": n == 0,
            "severity": "auto-fixable",
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
            "severity": "auto-fixable",
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
            "severity": "critical",
            "detail": f"{min_ts} → {max_ts}",
        })

    def _check_metadata(self, df: pl.DataFrame) -> None:
        null_usage = df.filter(
            pl.col("primaryspaceusage").is_null()
        ).shape[0]
        self.report.append({
            "check": "metadata_primaryspaceusage",
            "passed": null_usage == 0,
            "severity": "warning",
            "detail": f"{null_usage:,} rows with null primaryspaceusage"
                      if null_usage else "No nulls",
        })

        invalid_sqm = df.filter(
            pl.col("sqm").is_null() | (pl.col("sqm") <= 0)
        ).shape[0]
        self.report.append({
            "check": "metadata_sqm",
            "passed": invalid_sqm == 0,
            "severity": "warning",
            "detail": f"{invalid_sqm:,} rows with null or non-positive sqm"
                      if invalid_sqm else "All valid",
        })

    def _report_missingness(self, df: pl.DataFrame) -> None:
        rates = df.select(
            pl.all().is_null().mean()
        )
        high_missing = {
            c: f"{rates[c][0]:.1%}"
            for c in rates.columns
            if rates[c][0] > 0.1
        }
        self.report.append({
            "check": "missingness",
            "passed": len(high_missing) == 0,
            "severity": "warning",
            "detail": high_missing if high_missing else "No column >50% null",
        })

    def _check_merge_coverage(
        self,
        df: pl.DataFrame,
        electricity: pl.DataFrame,
        metadata: pl.DataFrame | None,
        weather: pl.DataFrame | None,
    ) -> None:
        # Electricity → metadata match
        if metadata is not None:
            elec_buildings = electricity["building_id"].unique()
            meta_buildings = metadata["building_id"].unique()
            unmatched = elec_buildings.filter(
                ~elec_buildings.is_in(meta_buildings)
            )
            self.report.append({
                "check": "electricity_metadata_coverage",
                "passed": len(unmatched) == 0,
                "severity": "warning",
                "detail": f"{len(unmatched)} buildings in electricity "
                          f"not in metadata"
                          if len(unmatched) > 0 else "Full coverage",
            })

        # Missing site_id after join
        missing_site = df.filter(pl.col("site_id").is_null()).shape[0]
        self.report.append({
            "check": "site_id_presence",
            "passed": missing_site == 0,
            "severity": "warning",
            "detail": f"{missing_site:,} rows missing site_id after merge"
                      if missing_site else "All rows have site_id",
        })

        # Weather site coverage
        if weather is not None and "site_id" in df.columns:
            weather_sites = weather["site_id"].unique()
            df_sites = df["site_id"].unique().drop_nulls()
            missing_weather = df_sites.filter(
                ~df_sites.is_in(weather_sites)
            )
            self.report.append({
                "check": "weather_site_coverage",
                "passed": len(missing_weather) == 0,
                "severity": "warning",
                "detail": f"{len(missing_weather)} sites lack weather data"
                          if len(missing_weather) > 0
                          else "All sites covered",
            })

        # Weather null rate after merge
        weather_cols = list(self.REQUIRED_WEATHER_COLUMNS.keys())
        weather_nulls = {
            c: f"{df[c].is_null().mean():.1%}"
            for c in weather_cols
            if c in df.columns and df[c].is_null().mean() > 0.01
        }
        self.report.append({
            "check": "weather_null_rate_post_merge",
            "passed": len(weather_nulls) == 0,
            "severity": "warning",
            "detail": weather_nulls if weather_nulls
                      else "No weather column >1% null after merge",
        })

    # ==================================================================
    # Auto-fixes
    # ==================================================================
    def _fix_duplicates(self, df: pl.DataFrame) -> pl.DataFrame:
        before = df.shape[0]
        df = df.unique(subset=["timestamp", "building_id"], maintain_order=True)
        removed = before - df.shape[0]
        if removed:
            msg = f"Removed {removed:,} duplicate rows"
            print(f"    Fixed: {msg}")
            self._fix_log.append(msg)
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
            msg = f"Nullified {n:,} negative consumption values"
            print(f"    Fixed: {msg}")
        return df

    def _fix_metadata(self, df: pl.DataFrame) -> pl.DataFrame:
        before = df["building_id"].n_unique()
        df = df.filter(
            pl.col("primaryspaceusage").is_not_null()
            & pl.col("sqm").is_not_null()
            & (pl.col("sqm") > 0)
        )
        after = df["building_id"].n_unique()
        dropped = before - after
        if dropped > 0:
            msg = f"Dropped {dropped} buildings with invalid metadata"
            print(f"    Fixed: {msg}")
            self._fix_log.append(msg)
        return df

    # ==================================================================
    # Reporting
    # ==================================================================
    def _print_report(self) -> None:
        for r in self.report:
            icon = "✅" if r["passed"] else "⚠️"
            print(f"    {icon} {r['check']}: {r['detail']}")

        all_passed = all(r["passed"] for r in self.report)
        if not all_passed:
            print("\n  ⚠️  Some checks raised warnings — review above.")

    def _save_null_summary(self, df: pl.DataFrame) -> None:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        null_summary = df.select(
            [pl.col(c).is_null().mean().alias(c) for c in df.columns]
        ).transpose(include_header=True, header_name="column",
                    column_names=["null_rate"])
        null_summary.write_csv(REPORT_DIR / "gold_null_summary.csv")

    def _write_report(self, shape: tuple[int, int]) -> None:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORT_DIR / "validation_report.md"

        passed = sum(1 for r in self.report if r["passed"])
        failed = len(self.report) - passed
        critical = sum(
            1 for r in self.report
            if not r["passed"] and r.get("severity") == "critical"
        )

        lines = [
            "# Validation Report",
            f"Generated: {datetime.now().isoformat()}",
            f"Dataset: {shape[0]:,} rows × {shape[1]} columns",
            "",
            "## Summary",
            f"- Total checks: {len(self.report)}",
            f"- Passed: {passed}",
            f"- Failed: {failed}",
            f"- Critical failures: {critical}",
            "",
            "## Checks",
            "",
            "| Check | Status | Severity | Detail |",
            "|-------|--------|----------|--------|",
        ]
        for r in self.report:
            status = "PASS" if r["passed"] else "FAIL"
            severity = r.get("severity", "-")
            detail = r["detail"]
            lines.append(
                f"| {r['check']} | {status} | {severity} | {detail} |"
            )

        lines.extend(["", "## Auto-fixes Applied"])
        if self._fix_log:
            for entry in self._fix_log:
                lines.append(f"- {entry}")
        else:
            lines.append("- None")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  Validation report saved to {report_path}")


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

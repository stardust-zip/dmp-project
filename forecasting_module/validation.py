"""Validation layer — quality checks on Silver data before Gold output.

Memory-optimised for 25M+ row datasets:
- Duplicate check uses group_by(agg count) instead of struct.is_duplicated()
- _fix_duplicates uses unique(maintain_order=False) — avoids full sort
- _check_merge_coverage does NOT hold the full electricity DataFrame;
  only building_id Series are passed in
- All .shape[0] counts on filtered DataFrames use lazy .select(pl.len())
  where possible to avoid materialising large intermediate frames
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl
import sys, os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from forecasting_module.config import GOLD_DIR, REPORT_DIR

REQUIRED_WEATHER_COLUMNS: dict[str, type] = {
    "airTemperature":  pl.Float64,
    "dewTemperature":  pl.Float64,
    "precipDepth1HR":  pl.Float64,
    "seaLvlPressure":  pl.Float64,
    "windDirection":   pl.Float64,
    "windSpeed":       pl.Float64,
}


def _count_filter(df: pl.DataFrame, mask: pl.Expr) -> int:
    """Count rows matching mask without materialising a filtered copy."""
    return df.select(mask.sum()).item()


class DataValidator:
    """Run data-quality checks and produce Gold-layer output."""

    REQUIRED_BASE_COLUMNS: dict[str, type] = {
        "timestamp":         pl.Datetime,
        "building_id":       pl.Utf8,
        "consumption":       pl.Float64,
        "site_id":           pl.Utf8,
        "primaryspaceusage": pl.Utf8,
        "sqm":               pl.Float64,
    }

    def __init__(self, output_dir: Path = GOLD_DIR):
        self.output_dir = output_dir
        self.report: list[dict] = []
        self._fix_log: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(
        self,
        df: pl.DataFrame,
        # Accept lightweight Series instead of full DataFrames to avoid
        # keeping 27M-row electricity in RAM alongside silver.
        elec_building_ids: pl.Series | None = None,
        meta_building_ids: pl.Series | None = None,
        weather_site_ids: pl.Series | None = None,
        weather_mode: str = "none",
        run_tag: str = "default",
    ) -> pl.DataFrame:
        """Validate, auto-fix, and save Gold Parquet.

        Parameters
        ----------
        elec_building_ids / meta_building_ids / weather_site_ids:
            Unique ID Series extracted from the bronze tables *before*
            passing to the validator.  Passing full DataFrames is no longer
            supported — the caller should extract only what is needed.
        weather_mode:
            'none' skips all weather column checks.
        run_tag:
            Appended to output filenames, e.g. 'h24_none'.
        """
        self.report = []
        self._fix_log = []

        print("  Running validation checks ...")
        self._check_required_columns(df, weather_mode=weather_mode)
        self._check_no_duplicates(df)
        self._check_no_negative_consumption(df)
        self._check_timestamp_range(df)
        self._check_metadata(df)
        self._report_missingness(df)
        self._check_merge_coverage(
            df,
            elec_building_ids=elec_building_ids,
            meta_building_ids=meta_building_ids,
            weather_site_ids=weather_site_ids,
            weather_mode=weather_mode,
        )

        # Auto-fixes
        df = self._fix_duplicates(df)
        df = self._fix_negative_consumption(df)
        df = self._fix_metadata(df)

        self._print_report()
        self._save_null_summary(df, run_tag)
        self._write_report(df.shape, run_tag)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / f"validated_{run_tag}.parquet"
        df.write_parquet(out_path)
        print(f"\n  → Saved Gold: {out_path}")
        print(f"  → {df.shape[0]:,} rows × {df.shape[1]} cols")
        return df

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------
    def _check_required_columns(
        self, df: pl.DataFrame, weather_mode: str = "none"
    ) -> None:
        missing_base = set(self.REQUIRED_BASE_COLUMNS) - set(df.columns)
        self.report.append({
            "check": "required_base_columns",
            "passed": len(missing_base) == 0,
            "severity": "critical",
            "detail": (f"Missing: {missing_base}" if missing_base
                       else "All base columns present"),
        })

        if weather_mode != "none":
            missing_wx = set(REQUIRED_WEATHER_COLUMNS) - set(df.columns)
            self.report.append({
                "check": "required_weather_columns",
                "passed": len(missing_wx) == 0,
                "severity": "critical",
                "detail": (f"Missing: {missing_wx}" if missing_wx
                           else "All weather columns present"),
            })
        else:
            self.report.append({
                "check": "required_weather_columns",
                "passed": True,
                "severity": "info",
                "detail": "Skipped — weather_mode='none'",
            })

        all_required = dict(self.REQUIRED_BASE_COLUMNS)
        if weather_mode != "none":
            all_required.update(REQUIRED_WEATHER_COLUMNS)

        dtype_mismatches = {
            c: f"expected {exp}, got {df[c].dtype}"
            for c, exp in all_required.items()
            if c in df.columns and df[c].dtype != exp
        }
        self.report.append({
            "check": "column_dtypes",
            "passed": not dtype_mismatches,
            "severity": "critical",
            "detail": (f"Mismatches: {dtype_mismatches}" if dtype_mismatches
                       else "All dtypes match"),
        })

    def _check_no_duplicates(self, df: pl.DataFrame) -> None:
        """Count duplicate (timestamp, building_id) pairs.

        Uses group_by + filter instead of struct.is_duplicated() to avoid
        materialising a struct column over 25M rows (which triggers an
        internal sort and doubles peak RAM).
        """
        n_dup_groups = (
            df.lazy()
            .group_by(["timestamp", "building_id"])
            .agg(pl.len().alias("cnt"))
            .filter(pl.col("cnt") > 1)
            .select(pl.len())
            .collect()
            .item()
        )
        # n_dup_groups = number of (ts, bid) keys that have >1 row
        self.report.append({
            "check": "no_duplicates",
            "passed": n_dup_groups == 0,
            "severity": "auto-fixable",
            "detail": (f"{n_dup_groups:,} duplicate (timestamp, building_id) keys"
                       if n_dup_groups else "No duplicates"),
        })

    def _check_no_negative_consumption(self, df: pl.DataFrame) -> None:
        n = _count_filter(
            df,
            pl.col("consumption").is_not_null() & (pl.col("consumption") < 0),
        )
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
        null_usage = _count_filter(df, pl.col("primaryspaceusage").is_null())
        self.report.append({
            "check": "metadata_primaryspaceusage",
            "passed": null_usage == 0,
            "severity": "warning",
            "detail": (f"{null_usage:,} rows with null primaryspaceusage"
                       if null_usage else "No nulls"),
        })
        invalid_sqm = _count_filter(
            df, pl.col("sqm").is_null() | (pl.col("sqm") <= 0)
        )
        self.report.append({
            "check": "metadata_sqm",
            "passed": invalid_sqm == 0,
            "severity": "warning",
            "detail": (f"{invalid_sqm:,} rows with null/non-positive sqm"
                       if invalid_sqm else "All valid"),
        })

    def _report_missingness(self, df: pl.DataFrame) -> None:
        # Compute null rates in one pass over all columns
        null_rates = (
            df.select([pl.col(c).is_null().mean().alias(c) for c in df.columns])
            .row(0)
        )
        high_missing = {
            c: f"{r:.1%}"
            for c, r in zip(df.columns, null_rates)
            if r > 0.1
        }
        self.report.append({
            "check": "missingness",
            "passed": not high_missing,
            "severity": "warning",
            "detail": high_missing if high_missing else "No column >10% null",
        })

    def _check_merge_coverage(
        self,
        df: pl.DataFrame,
        elec_building_ids: pl.Series | None = None,
        meta_building_ids: pl.Series | None = None,
        weather_site_ids: pl.Series | None = None,
        weather_mode: str = "none",
    ) -> None:
        """Coverage checks using pre-extracted ID Series — no full DFs needed."""
        if elec_building_ids is not None and meta_building_ids is not None:
            unmatched = elec_building_ids.filter(
                ~elec_building_ids.is_in(meta_building_ids)
            )
            self.report.append({
                "check": "electricity_metadata_coverage",
                "passed": len(unmatched) == 0,
                "severity": "warning",
                "detail": (f"{len(unmatched)} buildings in electricity not in metadata"
                           if len(unmatched) > 0 else "Full coverage"),
            })

        missing_site = _count_filter(df, pl.col("site_id").is_null())
        self.report.append({
            "check": "site_id_presence",
            "passed": missing_site == 0,
            "severity": "warning",
            "detail": (f"{missing_site:,} rows missing site_id"
                       if missing_site else "All rows have site_id"),
        })

        if weather_mode != "none" and weather_site_ids is not None:
            df_sites = df["site_id"].drop_nulls().unique()
            missing_wx = df_sites.filter(~df_sites.is_in(weather_site_ids))
            self.report.append({
                "check": "weather_site_coverage",
                "passed": len(missing_wx) == 0,
                "severity": "warning",
                "detail": (f"{len(missing_wx)} sites lack weather data"
                           if len(missing_wx) > 0 else "All sites covered"),
            })

            wx_cols_present = [
                c for c in REQUIRED_WEATHER_COLUMNS if c in df.columns
            ]
            weather_nulls = {
                c: f"{df[c].is_null().mean():.1%}"
                for c in wx_cols_present
                if df[c].is_null().mean() > 0.01
            }
            self.report.append({
                "check": "weather_null_rate_post_merge",
                "passed": not weather_nulls,
                "severity": "warning",
                "detail": (weather_nulls if weather_nulls
                           else "No weather column >1% null after merge"),
            })

    # ------------------------------------------------------------------
    # Auto-fixes
    # ------------------------------------------------------------------
    def _fix_duplicates(self, df: pl.DataFrame) -> pl.DataFrame:
        before = df.shape[0]
        # maintain_order=False avoids a full stable sort on 25M rows
        df = df.unique(
            subset=["timestamp", "building_id"],
            maintain_order=False,
            keep="first",
        )
        removed = before - df.shape[0]
        if removed:
            msg = f"Removed {removed:,} duplicate rows"
            print(f"    Fixed: {msg}")
            self._fix_log.append(msg)
        return df

    @staticmethod
    def _fix_negative_consumption(df: pl.DataFrame) -> pl.DataFrame:
        n = _count_filter(
            df,
            pl.col("consumption").is_not_null() & (pl.col("consumption") < 0),
        )
        if n:
            df = df.with_columns(
                pl.when(pl.col("consumption") < 0)
                .then(None)
                .otherwise(pl.col("consumption"))
                .alias("consumption"),
            )
            print(f"    Fixed: Nullified {n:,} negative consumption values")
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

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def _print_report(self) -> None:
        for r in self.report:
            icon = "✅" if r["passed"] else "⚠️ "
            print(f"    {icon} {r['check']}: {r['detail']}")
        if not all(r["passed"] for r in self.report):
            print("\n  ⚠️  Some checks raised warnings — review above.")

    def _save_null_summary(self, df: pl.DataFrame, tag: str) -> None:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        null_summary = df.select(
            [pl.col(c).is_null().mean().alias(c) for c in df.columns]
        ).transpose(
            include_header=True,
            header_name="column",
            column_names=["null_rate"],
        )
        null_summary.write_csv(REPORT_DIR / f"gold_{tag}_null_summary.csv")

    def _write_report(self, shape: tuple[int, int], tag: str) -> None:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORT_DIR / f"validation_report_{tag}.md"

        passed = sum(1 for r in self.report if r["passed"])
        failed = len(self.report) - passed
        critical = sum(
            1 for r in self.report
            if not r["passed"] and r.get("severity") == "critical"
        )
        lines = [
            "# Validation Report",
            f"Generated: {datetime.now().isoformat()}",
            f"Run tag: {tag}",
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
            lines.append(
                f"| {r['check']} | {'PASS' if r['passed'] else 'FAIL'} "
                f"| {r.get('severity', '-')} | {r['detail']} |"
            )
        lines.extend(["", "## Auto-fixes Applied"])
        for entry in self._fix_log or ["None"]:
            lines.append(f"- {entry}")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  Validation report saved to {report_path}")


# -----------------------------------------------------------------------
# Standalone
# -----------------------------------------------------------------------
if __name__ == "__main__":
    from forecasting_module.config import SILVER_DIR

    silver_path = SILVER_DIR / "merged.parquet"
    if not silver_path.exists():
        sys.exit(f"Silver file not found: {silver_path}\nRun the full pipeline first.")

    print(f"Loading Silver from {silver_path} ...")
    silver = pl.read_parquet(silver_path)
    print(f"  {silver.shape[0]:,} rows × {silver.shape[1]} cols\n")

    DataValidator().run(silver, weather_mode="none", run_tag="default")
"""Dataset builder layer — split Feature Store into train / validation / test."""

from __future__ import annotations

import sys
import os
import time
from datetime import datetime
from pathlib import Path

import polars as pl

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from forecasting_module.config import (
    DATASET_DIR,
    FEATURE_STORE_DIR,
    REPORT_DIR,
    TRAIN_END,
    VAL_END,
)


class DatasetBuilder:
    """Time-based split of feature data into train / validation / test."""

    def __init__(
        self,
        output_dir: Path = DATASET_DIR,
        train_end: str = TRAIN_END,
        val_end: str = VAL_END,
        subfolder: str | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.train_end_dt = datetime.fromisoformat(train_end)
        self.val_end_dt = datetime.fromisoformat(val_end)
        self.subfolder = subfolder

    # ==================================================================
    # Split
    # ==================================================================
    def split(
        self, df: pl.DataFrame,
    ) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
        """Split df into train / validation / test by timestamp cutoffs."""
        train = df.filter(pl.col("timestamp") <= self.train_end_dt)
        val = df.filter(
            (pl.col("timestamp") > self.train_end_dt)
            & (pl.col("timestamp") <= self.val_end_dt),
        )
        test = df.filter(pl.col("timestamp") > self.val_end_dt)
        return train, val, test

    # ==================================================================
    # Leakage check
    # ==================================================================
    @staticmethod
    def check_leakage(
        train: pl.DataFrame,
        val: pl.DataFrame,
        test: pl.DataFrame,
    ) -> None:
        """Verify no temporal overlap between splits."""
        train_max = train["timestamp"].max()
        val_min = val["timestamp"].min()
        val_max = val["timestamp"].max()
        test_min = test["timestamp"].min()

        ok1 = train_max < val_min
        ok2 = val_max < test_min

        if ok1 and ok2:
            print("    ✅ No data leakage: train < val < test")
        else:
            if not ok1:
                print(f"    ⚠️  Leakage: train max ({train_max}) >= val min ({val_min})")
            if not ok2:
                print(f"    ⚠️  Leakage: val max ({val_max}) >= test min ({test_min})")

    # ==================================================================
    # Save
    # ==================================================================
    def save(
        self,
        train: pl.DataFrame,
        val: pl.DataFrame,
        test: pl.DataFrame,
    ) -> None:
        """Write train / validation / test parquets into subfolder."""
        if self.subfolder:
            out = self.output_dir / self.subfolder
        else:
            out = self.output_dir
        out.mkdir(parents=True, exist_ok=True)

        train.write_parquet(out / "train.parquet")
        val.write_parquet(out / "validation.parquet")
        test.write_parquet(out / "test.parquet")

        print(f"    → Saved train: {train.shape[0]:,} rows")
        print(f"    → Saved val:   {val.shape[0]:,} rows")
        print(f"    → Saved test:  {test.shape[0]:,} rows")
        print(f"    → Location: {out}")

    # ==================================================================
    # Report
    # ==================================================================
    def _save_report(
        self,
        train: pl.DataFrame,
        val: pl.DataFrame,
        test: pl.DataFrame,
    ) -> None:
        """Write dataset_summary.md."""
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

        total = train.shape[0] + val.shape[0] + test.shape[0]

        lines = [
            "# Dataset Summary",
            f"Generated: {datetime.now().isoformat()}",
            "",
            "## Split Configuration",
            f"- Train cutoff: ≤ {self.train_end_dt}",
            f"- Val cutoff:   ≤ {self.val_end_dt}",
            f"- Test:          > {self.val_end_dt}",
            "",
            "## Row Counts",
            f"| Split      | Rows          | Ratio  |",
            f"|------------|---------------|--------|",
            f"| Train      | {train.shape[0]:>13,} | {train.shape[0] / total:.1%} |",
            f"| Validation | {val.shape[0]:>13,} | {val.shape[0] / total:.1%} |",
            f"| Test       | {test.shape[0]:>13,} | {test.shape[0] / total:.1%} |",
            f"| **Total**  | {total:>13,} | 100.0% |",
            "",
            "## Timestamp Ranges",
            f"| Split      | Min                    | Max                    |",
            f"|------------|------------------------|------------------------|",
            f"| Train      | {train['timestamp'].min()} | {train['timestamp'].max()} |",
            f"| Validation | {val['timestamp'].min()} | {val['timestamp'].max()} |",
            f"| Test       | {test['timestamp'].min()} | {test['timestamp'].max()} |",
            "",
            "## Buildings",
            f"| Split      | Unique Buildings |",
            f"|------------|------------------|",
            f"| Train      | {train['building_id'].n_unique():>16,} |",
            f"| Validation | {val['building_id'].n_unique():>16,} |",
            f"| Test       | {test['building_id'].n_unique():>16,} |",
        ]

        report_path = REPORT_DIR / "dataset_summary.md"
        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"    → Saved report: {report_path}")

    # ==================================================================
    # Runner
    # ==================================================================
    def run(self, df: pl.DataFrame) -> None:
        """Execute dataset split → save parquets + report."""
        t0 = time.perf_counter()
        print(f"  Input: {df.shape[0]:,} rows × {df.shape[1]} cols")

        print("  Splitting data ...")
        train, val, test = self.split(df)

        print("  Checking data leakage ...")
        self.check_leakage(train, val, test)

        print("  Saving datasets ...")
        self.save(train, val, test)

        self._save_report(train, val, test)

        elapsed = time.perf_counter() - t0
        print(f"  Dataset builder done in {elapsed:.1f}s")


# -----------------------------------------------------------------------
# Standalone:  python -m forecasting_module.dataset_builder
# -----------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build train/val/test datasets.")
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Path to feature parquet (default: auto-detect in feature_store/).",
    )
    args = parser.parse_args()

    if args.input:
        feature_path = Path(args.input)
    else:
        # Auto-detect first parquet in feature_store
        parquets = sorted(FEATURE_STORE_DIR.glob("features_*.parquet"))
        if not parquets:
            sys.exit(
                f"No feature parquets found in {FEATURE_STORE_DIR}\n"
                "Run feature_engineering first."
            )
        feature_path = parquets[0]

    print(f"Loading features from {feature_path} ...")
    features = pl.read_parquet(feature_path)
    print(f"  {features.shape[0]:,} rows × {features.shape[1]} cols\n")

    # Derive subfolder from filename: features_h24_energy.parquet → h24_energy
    stem = feature_path.stem  # e.g. "features_h24_energy"
    subfolder = stem.replace("features_", "") if stem.startswith("features_") else None

    DatasetBuilder(subfolder=subfolder).run(features)

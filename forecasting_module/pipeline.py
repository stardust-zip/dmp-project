"""Pipeline orchestrator — ties Ingestion → Preprocessing → Validation → Outlier."""

from __future__ import annotations

import argparse
import gc
import os
import sys
import time

import polars as pl

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from forecasting_module.config import GOLD_DIR, REPORT_DIR
from forecasting_module.ingestion import DataIngestion
from forecasting_module.outlier import OutlierDetector
from forecasting_module.preprocessing import Preprocessor
from forecasting_module.validation import DataValidator


class ForecastingPipeline:
    """End-to-end data processing pipeline for the forecasting module.

    Bronze (raw Parquet) → Silver (cleaned + merged) → Gold (validated)
    → Gold v2 (outlier handled + missing re-handled).
    """

    def __init__(self) -> None:
        self.ingestion = DataIngestion()
        self.preprocessor = Preprocessor()
        self.validator = DataValidator()
        self.outlier_detector = OutlierDetector()

    @staticmethod
    def _force_gc(stage_name: str) -> None:
        """Release Python references and ask Polars/Python to return memory."""
        gc.collect()
        print(f"  Memory cleanup after {stage_name} done.")

    def run(self, skip_outlier: bool = False, reload_gold_before_outlier: bool = True) -> pl.DataFrame:
        """Run the full forecasting data pipeline.

        Parameters
        ----------
        skip_outlier:
            If True, stop after Stage 3 and return Gold.
        reload_gold_before_outlier:
            If True, release Bronze/Silver/Gold objects after validation, then
            re-read Gold from disk before Stage 4. This is safer for large data
            because it avoids keeping Bronze + Silver + Gold in RAM while the
            outlier stage performs group_by/join operations.
        """
        t0 = time.perf_counter()

        print("=" * 60)
        print("FORECASTING DATA PIPELINE")
        print("=" * 60)

        # ── Bronze ──────────────────────────────────────────────────
        print("\nStage 1 — Ingestion (Bronze)")
        bronze = self.ingestion.run()

        # Bronze null summary
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        for name, df in bronze.items():
            null_summary = df.select(
                [pl.col(c).is_null().mean().alias(c) for c in df.columns]
            ).transpose(
                include_header=True,
                header_name="column",
                column_names=["null_rate"],
            )
            null_summary.write_csv(REPORT_DIR / f"bronze_{name}_null_summary.csv")

        print("\nIngestion done.")

        # ── Silver ──────────────────────────────────────────────────
        print("\nStage 2 — Preprocessing (Silver)")
        silver = self.preprocessor.run(bronze)
        print("\nPreprocessing done.")

        # ── Gold ────────────────────────────────────────────────────
        print("\nStage 3 — Validation (Gold)")
        gold = self.validator.run(
            silver,
            electricity=bronze["electricity"],
            metadata=bronze["metadata"],
            weather=bronze["weather"],
        )
        print("\nValidation done.")

        if skip_outlier:
            final = gold
        else:
            # Critical for large datasets: do not keep Bronze + Silver in RAM
            # while Stage 4 performs expensive IQR group_by/join operations.
            del silver
            del bronze
            self._force_gc("Stage 3")

            if reload_gold_before_outlier:
                # The validator already writes validated.parquet. Re-reading it
                # creates a compact DataFrame and lets the previous in-memory
                # Gold object be released before Stage 4.
                gold_path = GOLD_DIR / "validated.parquet"
                if not gold_path.exists():
                    raise FileNotFoundError(
                        f"Gold file not found: {gold_path}. Validation did not save Gold."
                    )
                del gold
                self._force_gc("Gold release")
                print(f"  Reloading Gold from disk before Stage 4: {gold_path}")
                gold = pl.read_parquet(gold_path)
                print(f"  Reloaded Gold: {gold.shape[0]:,} rows × {gold.shape[1]} cols")

            # ── Outlier ─────────────────────────────────────────────
            print("\nStage 4 — Outlier Detection (Gold v2)")
            final = self.outlier_detector.run(gold, self.preprocessor)
            print("\nOutlier detection done.")

        elapsed = time.perf_counter() - t0
        print("\n" + "=" * 60)
        print(f"DONE in {elapsed:.1f}s  —  {final.shape[0]:,} rows × {final.shape[1]} cols")
        print("=" * 60)
        return final


# -----------------------------------------------------------------------
# CLI entry-point:
#   uv run forecasting_module/pipeline.py
#   uv run forecasting_module/pipeline.py --skip-outlier
# -----------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run forecasting data pipeline.")
    parser.add_argument(
        "--skip-outlier",
        action="store_true",
        help="Stop after Stage 3 Gold validation.",
    )
    parser.add_argument(
        "--no-reload-gold",
        action="store_true",
        help="Do not reload Gold from disk before Stage 4. Uses more RAM.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    ForecastingPipeline().run(
        skip_outlier=args.skip_outlier,
        reload_gold_before_outlier=not args.no_reload_gold,
    )

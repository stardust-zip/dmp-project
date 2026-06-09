"""Pipeline orchestrator — ties Ingestion → Preprocessing → Validation."""

from __future__ import annotations

import time
import sys
import os
import polars as pl
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from forecasting_module.ingestion import DataIngestion
from forecasting_module.preprocessing import Preprocessor
from forecasting_module.validation import DataValidator


class ForecastingPipeline:
    """End-to-end data processing pipeline for the forecasting module.

    Bronze (raw Parquet) → Silver (cleaned + merged) → Gold (validated).
    """

    def __init__(self) -> None:
        self.ingestion = DataIngestion()
        self.preprocessor = Preprocessor()
        self.validator = DataValidator()

    def run(self) -> pl.DataFrame:
        t0 = time.perf_counter()

        print("=" * 60)
        print("FORECASTING DATA PIPELINE")
        print("=" * 60)

        # ── Bronze ──────────────────────────────────────────────────
        print("\nStage 1 — Ingestion (Bronze)")
        bronze = self.ingestion.run()
        print("\nIngestion done.")
        # ── Silver ──────────────────────────────────────────────────
        print("\nStage 2 — Preprocessing (Silver)")
        silver = self.preprocessor.run(bronze)
        print("\nPreprocessing done.")
        # ── Gold ────────────────────────────────────────────────────
        print("\nStage 3 — Validation (Gold)")
        gold = self.validator.run(silver)
        print("\nValidation done.")
        elapsed = time.perf_counter() - t0
        print("\n" + "=" * 60)
        print(f"DONE in {elapsed:.1f}s  —  {gold.shape[0]:,} rows × {gold.shape[1]} cols")
        print("=" * 60)
        return gold


# -----------------------------------------------------------------------
# CLI entry-point:  python -m forecasting_module.pipeline
# -----------------------------------------------------------------------
if __name__ == "__main__":
    ForecastingPipeline().run()

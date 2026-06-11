"""Pipeline orchestrator — ties Ingestion → Preprocessing → Validation → Outlier → Feature Engineering → Dataset Builder."""

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
from forecasting_module.feature_engineering import FeatureEngineer
from forecasting_module.dataset_builder import DatasetBuilder


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

    def run(
        self,
        skip_outlier: bool = False,
        reload_gold_before_outlier: bool = True,
        skip_feature_engineering: bool = False,
        skip_dataset_builder: bool = False,
        forecast_horizon_hours: int = 24,
        weather_mode: str = "none",
    ) -> pl.DataFrame:
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
        skip_feature_engineering:
            If True, stop after Stage 4 and return Gold v2.
        skip_dataset_builder:
            If True, stop after Stage 5 and return None.
        forecast_horizon_hours:
            Forecast horizon for feature engineering (24 or 168).
        weather_mode:
            Weather feature mode: "none", "historical", or "forecast".
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

        if skip_feature_engineering:
            elapsed = time.perf_counter() - t0
            print("\n" + "=" * 60)
            print(f"DONE in {elapsed:.1f}s  —  {final.shape[0]:,} rows × {final.shape[1]} cols")
            print("=" * 60)
            return final

        # ── Feature Engineering ────────────────────────────────────────
        del final
        self._force_gc("Stage 4")

        gold_v2_path = GOLD_DIR / "validated_v2.parquet"
        if not gold_v2_path.exists():
            raise FileNotFoundError(
                f"Gold v2 file not found: {gold_v2_path}. "
                "Run Stage 4 (Outlier) first."
            )
        print(f"\n  Reloading Gold v2 from disk: {gold_v2_path}")
        gold_v2 = pl.read_parquet(gold_v2_path)
        print(f"  Loaded Gold v2: {gold_v2.shape[0]:,} rows × {gold_v2.shape[1]} cols")

        print("\nStage 5 — Feature Engineering (Feature Store)")
        fe = FeatureEngineer(
            forecast_horizon_hours=forecast_horizon_hours,
            weather_mode=weather_mode,
        )
        fe.run(gold_v2)
        feature_path = fe.output_dir / fe._build_filename()

        if skip_dataset_builder:
            elapsed = time.perf_counter() - t0
            print("\n" + "=" * 60)
            print(f"DONE in {elapsed:.1f}s")
            print("=" * 60)
            return None

        # ── Dataset Builder ─────────────────────────────────────────────
        del gold_v2
        self._force_gc("Stage 5")

        print(f"\n  Reloading features from disk: {feature_path}")
        features = pl.read_parquet(feature_path)
        print(f"  Loaded features: {features.shape[0]:,} rows × {features.shape[1]} cols")

        print("\nStage 6 — Dataset Builder (Train / Val / Test)")
        # Derive subfolder from feature filename: features_h24_energy → h24_energy
        subfolder = feature_path.stem.replace("features_", "")
        DatasetBuilder(subfolder=subfolder).run(features)

        elapsed = time.perf_counter() - t0
        print("\n" + "=" * 60)
        print(f"DONE in {elapsed:.1f}s")
        print("=" * 60)
        return None


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
    parser.add_argument(
        "--skip-feature-engineering",
        action="store_true",
        help="Stop after Stage 4 (Outlier) and skip Feature Engineering.",
    )
    parser.add_argument(
        "--skip-dataset-builder",
        action="store_true",
        help="Stop after Stage 5 (Feature Engineering) and skip Dataset Builder.",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=24,
        help="Forecast horizon in hours for feature engineering (default: 24).",
    )
    parser.add_argument(
        "--weather-mode",
        type=str,
        default="none",
        choices=["none", "historical", "forecast"],
        help="Weather feature mode (default: none).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    ForecastingPipeline().run(
        skip_outlier=args.skip_outlier,
        reload_gold_before_outlier=not args.no_reload_gold,
        skip_feature_engineering=args.skip_feature_engineering,
        skip_dataset_builder=args.skip_dataset_builder,
        forecast_horizon_hours=args.horizon,
        weather_mode=args.weather_mode,
    )

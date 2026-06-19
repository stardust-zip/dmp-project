"""Pipeline orchestrator — Ingestion → Preprocessing → Validation → Outlier
→ Feature Engineering → Dataset Builder.

Memory strategy
---------------
25M-row Silver is the largest object in RAM. The pipeline is structured to
hold at most ONE large DataFrame at a time:

  Stage 1 (Ingestion)   : bronze dict built; ID Series extracted immediately
                          for the validator so full bronze can be freed early.
  Stage 2 (Preprocessing): silver built from bronze; bronze freed right after.
  Stage 3 (Validation)  : validator receives silver + tiny ID Series only.
                          silver freed after Gold is written to disk.
  Stage 4 (Outlier)     : Gold reloaded from disk (compact parquet).
  Stage 5 (Feature Eng) : Gold v2 reloaded; features written to disk.
  Stage 6 (Dataset Bld) : features reloaded; splits written to disk.

CLI:
  uv run pipeline.py --horizon 24  --weather-mode none
  uv run pipeline.py --horizon 24  --weather-mode forecast
  uv run pipeline.py --horizon 168 --weather-mode none
  uv run pipeline.py --horizon 168 --weather-mode forecast
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
import time

import polars as pl

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from forecasting_module.config import GOLD_DIR, REPORT_DIR
from forecasting_module.dataset_builder import DatasetBuilder
from forecasting_module.feature_engineering import FeatureEngineer
from forecasting_module.ingestion import DataIngestion
from forecasting_module.outlier import OutlierDetector
from forecasting_module.preprocessing import Preprocessor
from forecasting_module.validation import DataValidator


class ForecastingPipeline:
    """End-to-end data processing pipeline for the forecasting module."""

    def __init__(self) -> None:
        self.ingestion = DataIngestion()
        self.preprocessor = Preprocessor()
        self.validator = DataValidator()
        self.outlier_detector = OutlierDetector()

    @staticmethod
    def _force_gc(stage_name: str) -> None:
        gc.collect()
        print(f"  Memory freed after {stage_name}.")

    # ------------------------------------------------------------------
    # Weather gating — applied immediately after ingestion
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_weather_mode(
        bronze: dict[str, pl.DataFrame],
        weather_mode: str,
    ) -> dict[str, pl.DataFrame]:
        """Replace weather table at ingestion time based on weather_mode.

        none     → weather replaced with timestamp/site_id stub so that
                   Preprocessor.merge() joins nothing useful and no weather
                   columns enter Silver/Gold.
        forecast → weather kept; Feature Engineering shifts columns later.
        """
        if weather_mode == "none":
            stub = bronze["weather"].select(["timestamp", "site_id"])
            return {**bronze, "weather": stub}
        if weather_mode == "forecast":
            return bronze
        raise ValueError(
            f"Unsupported weather_mode '{weather_mode}'. Choose 'none' or 'forecast'."
        )

    # ------------------------------------------------------------------
    # Pipeline runner
    # ------------------------------------------------------------------
    def run(
        self,
        forecast_horizon_hours: int = 24,
        weather_mode: str = "none",
        skip_outlier: bool = False,
        reload_gold_before_outlier: bool = True,
        skip_feature_engineering: bool = False,
        skip_dataset_builder: bool = False,
        building_id: str | None = None,
    ) -> pl.DataFrame | None:
        t0 = time.perf_counter()
        run_tag = f"h{forecast_horizon_hours}_{weather_mode}"

        print("=" * 60)
        print(f"FORECASTING DATA PIPELINE  [{run_tag}]")
        print("=" * 60)
        print(f"  horizon={forecast_horizon_hours}h  |  weather_mode={weather_mode}")

        # ── Stage 1: Ingestion ──────────────────────────────────────
        print("\nStage 1 — Ingestion (Bronze)")
        bronze = self.ingestion.run()

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

        # Apply weather mode at ingestion
        print(f"\n  Applying weather_mode='{weather_mode}' at ingestion ...")
        bronze = self._apply_weather_mode(bronze, weather_mode)
        if weather_mode == "none":
            print(
                "  Weather table replaced with stub — "
                "no weather columns will enter Silver."
            )
        else:
            print(f"  Weather table kept ({bronze['weather'].shape[0]:,} rows).")

        # ── Building filter (for per-building training) ───────────
        if building_id:
            print(f"\n  Filtering to single building: {building_id}")
            before_elec = bronze["electricity"].shape[0]
            bronze["electricity"] = bronze["electricity"].filter(
                pl.col("building_id") == building_id
            )
            after_elec = bronze["electricity"].shape[0]
            print(f"    Electricity: {before_elec:,} → {after_elec:,} rows")

            before_meta = bronze["metadata"].shape[0]
            bronze["metadata"] = bronze["metadata"].filter(
                pl.col("building_id") == building_id
            )
            after_meta = bronze["metadata"].shape[0]
            print(f"    Metadata:    {before_meta:,} → {after_meta:,} rows")

            if after_elec == 0:
                raise ValueError(
                    f"No electricity data for building '{building_id}'. "
                    f"Check the building_id or data availability."
                )
            if after_meta == 0:
                print(
                    f"    WARNING: No metadata for building '{building_id}'. "
                    f"Merged data will have null metadata columns."
                )

            # Update run_tag to include building for output file naming
            safe_building = building_id.replace("/", "_").replace("\\", "_")
            run_tag = f"{run_tag}_{safe_building}"

        # Extract lightweight ID Series for the validator NOW,
        # before bronze is freed — avoids keeping 27M-row electricity
        # DataFrame alive through Stages 2 and 3.
        elec_building_ids = bronze["electricity"]["building_id"].unique()
        meta_building_ids = bronze["metadata"]["building_id"].unique()
        weather_site_ids = (
            bronze["weather"]["site_id"].unique() if weather_mode != "none" else None
        )
        print(
            f"  Extracted validator ID Series "
            f"({len(elec_building_ids)} elec buildings, "
            f"{len(meta_building_ids)} meta buildings)."
        )

        print("\nIngestion done.")

        # ── Stage 2: Preprocessing ─────────────────────────────────
        print("\nStage 2 — Preprocessing (Silver)")
        silver = self.preprocessor.run(bronze)

        # Free bronze immediately — electricity (27M rows) no longer needed
        del bronze
        self._force_gc("Stage 2 (bronze freed)")

        print("\nPreprocessing done.")

        # ── Stage 3: Validation ────────────────────────────────────
        print("\nStage 3 — Validation (Gold)")
        gold = self.validator.run(
            silver,
            elec_building_ids=elec_building_ids,
            meta_building_ids=meta_building_ids,
            weather_site_ids=weather_site_ids,
            weather_mode=weather_mode,
            run_tag=run_tag,
        )

        # Free silver and ID Series — Gold has been written to disk
        del silver, elec_building_ids, meta_building_ids, weather_site_ids
        self._force_gc("Stage 3 (silver + IDs freed)")

        print("\nValidation done.")

        if skip_outlier:
            elapsed = time.perf_counter() - t0
            print(f"\n{'=' * 60}")
            print(f"DONE (stopped after Stage 3) in {elapsed:.1f}s")
            print(f"{'=' * 60}")
            return gold

        del gold
        self._force_gc("Gold in-memory (reloading from disk)")

        gold_path = GOLD_DIR / f"validated_{run_tag}.parquet"
        if not gold_path.exists():
            raise FileNotFoundError(
                f"Gold file not found: {gold_path}. Validation did not save Gold."
            )
        print(f"  Reloading Gold from disk: {gold_path}")
        gold = pl.read_parquet(gold_path)
        print(f"  Reloaded: {gold.shape[0]:,} rows × {gold.shape[1]} cols")

        # ── Stage 4: Outlier ───────────────────────────────────────
        print("\nStage 4 — Outlier Detection (Gold v2)")
        final = self.outlier_detector.run(
            gold,
            self.preprocessor,
            run_tag=run_tag,
            weather_mode=weather_mode,
        )
        del gold
        self._force_gc("Stage 4 (gold freed)")

        print("\nOutlier detection done.")

        if skip_feature_engineering:
            elapsed = time.perf_counter() - t0
            print(f"\n{'=' * 60}")
            print(
                f"DONE (stopped after Stage 4) in {elapsed:.1f}s  "
                f"— {final.shape[0]:,} rows × {final.shape[1]} cols"
            )
            print(f"{'=' * 60}")
            return final

        # ── Stage 5: Feature Engineering ──────────────────────────
        del final
        self._force_gc("Stage 5 prep (final freed)")

        gold_v2_path = GOLD_DIR / f"validated_v2_{run_tag}.parquet"
        if not gold_v2_path.exists():
            raise FileNotFoundError(
                f"Gold v2 file not found: {gold_v2_path}. Run Stage 4 (Outlier) first."
            )
        print(f"\n  Reloading Gold v2 from disk: {gold_v2_path}")
        gold_v2 = pl.read_parquet(gold_v2_path)
        print(f"  Loaded: {gold_v2.shape[0]:,} rows × {gold_v2.shape[1]} cols")

        print("\nStage 5 — Feature Engineering (Feature Store)")
        fe = FeatureEngineer(
            forecast_horizon_hours=forecast_horizon_hours,
            weather_mode=weather_mode,
        )
        fe.run(gold_v2)
        feature_path = fe.output_dir / fe._build_filename()

        if skip_dataset_builder:
            elapsed = time.perf_counter() - t0
            print(f"\n{'=' * 60}")
            print(f"DONE (stopped after Stage 5) in {elapsed:.1f}s")
            print(f"{'=' * 60}")
            return None

        # ── Stage 6: Dataset Builder ───────────────────────────────
        del gold_v2
        self._force_gc("Stage 5 (gold_v2 freed)")

        print(f"\n  Reloading features from disk: {feature_path}")
        features = pl.read_parquet(feature_path)
        print(f"  Loaded: {features.shape[0]:,} rows × {features.shape[1]} cols")

        print("\nStage 6 — Dataset Builder (Train / Val / Test)")
        subfolder = feature_path.stem.replace("features_", "")
        DatasetBuilder(subfolder=subfolder).run(features)

        elapsed = time.perf_counter() - t0
        print(f"\n{'=' * 60}")
        print(f"DONE [{run_tag}] in {elapsed:.1f}s")
        print(f"{'=' * 60}")
        return None


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run forecasting data pipeline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=24,
        choices=[24, 168],
        help="Forecast horizon in hours.",
    )
    parser.add_argument(
        "--weather-mode",
        type=str,
        default="none",
        choices=["none", "forecast"],
        help="Weather feature mode — resolved at ingestion time.",
    )
    parser.add_argument(
        "--skip-outlier",
        action="store_true",
        help="Stop after Stage 3 Gold validation.",
    )
    parser.add_argument(
        "--skip-feature-engineering",
        action="store_true",
        help="Stop after Stage 4 (Outlier).",
    )
    parser.add_argument(
        "--skip-dataset-builder",
        action="store_true",
        help="Stop after Stage 5 (Feature Engineering).",
    )
    parser.add_argument(
        "--building-id",
        type=str,
        default=None,
        help="Process a single building only (for per-building model training).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    ForecastingPipeline().run(
        forecast_horizon_hours=args.horizon,
        weather_mode=args.weather_mode,
        skip_outlier=args.skip_outlier,
        skip_feature_engineering=args.skip_feature_engineering,
        skip_dataset_builder=args.skip_dataset_builder,
        building_id=args.building_id,
    )

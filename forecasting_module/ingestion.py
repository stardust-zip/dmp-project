"""Ingestion layer — load raw BDG2 CSVs into Bronze Parquet files."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from forecasting_module.config import (
    BRONZE_DIR,
    CHUNK_SIZE,
    ELECTRICITY_PATH,
    METADATA_KEEP,
    METADATA_PATH,
    WEATHER_KEEP,
    WEATHER_PATH,
)


class DataIngestion:
    """Load raw BDG2 data and persist as Bronze-layer Parquet."""

    def __init__(
        self,
        electricity_path: Path = ELECTRICITY_PATH,
        metadata_path: Path = METADATA_PATH,
        weather_path: Path = WEATHER_PATH,
        output_dir: Path = BRONZE_DIR,
        chunk_size: int = CHUNK_SIZE,
    ):
        self.electricity_path = electricity_path
        self.metadata_path = metadata_path
        self.weather_path = weather_path
        self.output_dir = output_dir
        self.chunk_size = chunk_size

    # ------------------------------------------------------------------
    # Electricity
    # ------------------------------------------------------------------
    def load_electricity(self) -> pl.DataFrame:
        """Load electricity CSV (wide) and melt to long format.

        Processes building columns in configurable batches to limit
        peak memory during the melt step.
        """
        wide = pl.read_csv(
            self.electricity_path,
            try_parse_dates=True,
            null_values="NaN",
        )
        building_cols = [c for c in wide.columns if c != "timestamp"]

        # Small enough to melt in one pass
        if len(building_cols) <= self.chunk_size:
            return self._melt(wide)

        # Melt in batches, then concat
        parts: list[pl.DataFrame] = []
        for i in range(0, len(building_cols), self.chunk_size):
            batch = building_cols[i : i + self.chunk_size]
            subset = wide.select(["timestamp", *batch])
            parts.append(self._melt(subset))
            print(f"    melted batch {i // self.chunk_size + 1} "
                  f"({len(batch)} buildings)")

        return pl.concat(parts)

    @staticmethod
    def _melt(wide: pl.DataFrame) -> pl.DataFrame:
        return wide.melt(
            id_vars=["timestamp"],
            variable_name="building_id",
            value_name="consumption",
        ).with_columns(
            pl.col("consumption").cast(pl.Float64)
        ).sort(["building_id", "timestamp"])

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
    def load_metadata(self) -> pl.DataFrame:
        keep = [c for c in METADATA_KEEP]
        return pl.read_csv(self.metadata_path).select(keep)

    # ------------------------------------------------------------------
    # Weather
    # ------------------------------------------------------------------
    def load_weather(self) -> pl.DataFrame:
        return (
            pl.read_csv(self.weather_path, try_parse_dates=True)
            .select(WEATHER_KEEP)
        )

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------
    def run(self) -> dict[str, pl.DataFrame]:
        """Ingest all sources and save Bronze Parquet files."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        print("  Electricity ...")
        electricity = self.load_electricity()
        electricity.write_parquet(self.output_dir / "electricity.parquet")
        print(f"    → {electricity.shape[0]:,} rows × {electricity.shape[1]} cols")

        print("  Metadata ...")
        metadata = self.load_metadata()
        metadata.write_parquet(self.output_dir / "metadata.parquet")
        print(f"    → {metadata.shape[0]:,} rows × {metadata.shape[1]} cols")

        print("  Weather ...")
        weather = self.load_weather()
        weather.write_parquet(self.output_dir / "weather.parquet")
        print(f"    → {weather.shape[0]:,} rows × {weather.shape[1]} cols")

        return {
            "electricity": electricity,
            "metadata": metadata,
            "weather": weather,
        }

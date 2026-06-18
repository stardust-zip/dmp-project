"""Persistence for forecasting results.

Mirrors :class:`src.ml.anomaly.store.AnomalyEventStore` but writes
:class:`src.models.ForecastResult` rows. Forecast results are upserted on the
composite primary key ``(timestamp, device_id, metric_type_id)`` so that a
re-forecast over the same future window overwrites the previous prediction.

Each forecast row references a *virtual meter* device (the same convention the
telemetry seeder uses, ``meter_{metric}_{building_id}``). ``_ensure_meter_device``
get-or-creates that device so the FK on ``ForecastResult.device_id`` is valid.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.models import Device, ForecastResult


def _chunks(records: list[dict], size: int) -> Iterable[list[dict]]:
    for offset in range(0, len(records), size):
        yield records[offset : offset + size]


def _ensure_meter_device(db: Session, building_id: str, metric: str) -> Device:
    """Get-or-create the virtual-meter device holding forecasts for a building/metric.

    Mirrors the seeder convention (``seeder.py:190``):
    ``device_id = f"meter_{metric}_{building_id}"`` with
    ``device_type_id="virtual_meter"``.
    """
    device_id = f"meter_{metric}_{building_id}"
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        device = Device(
            id=device_id,
            location_id=building_id,
            device_type_id="virtual_meter",
            status="Active",
        )
        db.add(device)
        db.flush()  # make the FK valid within the current transaction
    return device


class ForecastResultStore:
    """Upsert future forecast points into ``forecast_result``."""

    INDEX_ELEMENTS = ["timestamp", "device_id", "metric_type_id"]
    CHUNK_SIZE = 500

    def __init__(self, db: Session) -> None:
        self._db = db

    def upsert(self, records: list[dict], *, commit: bool = True) -> int:
        """Upsert forecast records.

        Each record must carry ``timestamp``, ``device_id``, ``metric_type_id``,
        ``predicted_value`` and ``mlflow_run_id``. On conflict (same
        timestamp/device/metric) ``predicted_value``, ``mlflow_run_id`` and
        ``generated_at`` are refreshed.
        """
        if not records:
            return 0

        now = datetime.now(timezone.utc)
        for chunk in _chunks(records, self.CHUNK_SIZE):
            stmt = pg_insert(ForecastResult.__table__).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=self.INDEX_ELEMENTS,
                set_={
                    "predicted_value": stmt.excluded.predicted_value,
                    "mlflow_run_id": stmt.excluded.mlflow_run_id,
                    "generated_at": now,
                },
            )
            self._db.execute(stmt)
        if commit:
            self._db.commit()
        return len(records)

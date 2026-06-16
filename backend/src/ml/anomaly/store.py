from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.models import AnomalyDetectedEvent

if TYPE_CHECKING:
    from src.ml.anomaly.types import RuleFinding


_DEFAULT_COLUMNS = {"id", "created_at"}


def _chunks(records: list[dict], size: int) -> Iterable[list[dict]]:
    for offset in range(0, len(records), size):
        yield records[offset: offset + size]


class AnomalyEventStore:
    CONSTRAINT = "uq_anomaly_detected_event"
    CHUNK_SIZE = 500

    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def event_records(events: Iterable[AnomalyDetectedEvent]) -> list[dict[str, object]]:
        return [
            {
                c.key: getattr(event, c.key)
                for c in AnomalyDetectedEvent.__table__.columns
                if c.key not in _DEFAULT_COLUMNS
            }
            for event in events
        ]

    @staticmethod
    def finding_records(findings: Iterable[RuleFinding]) -> list[dict[str, object]]:
        return [
            {
                "building_id": finding.building_id,
                "site_id": finding.site_id,
                "timestamp": finding.timestamp,
                "metric_type_id": finding.metric_type_id,
                "primary_space_usage": finding.primary_space_usage,
                "actual_value": finding.actual_value,
                "predicted_value": None,
                "residual": None,
                "residual_z": None,
                "anomaly_score": None,
                "is_anomaly": finding.is_anomaly,
                "direction": finding.direction,
                "severity": finding.severity,
                "source": finding.source,
                "anomaly_type": finding.anomaly_type,
                "reason": finding.reason,
                "mlflow_run_id": finding.mlflow_run_id,
            }
            for finding in findings
        ]

    def insert_ignore(self, records: list[dict], *, commit: bool = True) -> int:
        if not records:
            return 0

        for chunk in _chunks(records, self.CHUNK_SIZE):
            stmt = pg_insert(AnomalyDetectedEvent.__table__).values(chunk)
            stmt = stmt.on_conflict_do_nothing(constraint=self.CONSTRAINT)
            self._db.execute(stmt)
        if commit:
            self._db.commit()
        return len(records)

    def upsert(self, records: list[dict], *, commit: bool = True) -> int:
        if not records:
            return 0

        for chunk in _chunks(records, self.CHUNK_SIZE):
            stmt = pg_insert(AnomalyDetectedEvent.__table__).values(chunk)
            stmt = stmt.on_conflict_do_update(
                constraint=self.CONSTRAINT,
                set_={
                    "predicted_value": stmt.excluded.predicted_value,
                    "residual": stmt.excluded.residual,
                    "residual_z": stmt.excluded.residual_z,
                    "anomaly_score": stmt.excluded.anomaly_score,
                    "is_anomaly": stmt.excluded.is_anomaly,
                    "direction": stmt.excluded.direction,
                    "severity": stmt.excluded.severity,
                },
            )
            self._db.execute(stmt)
        if commit:
            self._db.commit()
        return len(records)

    def insert_findings(self, findings: list[RuleFinding], *, commit: bool = True) -> int:
        return self.insert_ignore(self.finding_records(findings), commit=commit)

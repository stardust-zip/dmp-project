import csv
import io
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_operator
from src.database import get_db
from src.models import TelemetryData
from src.schemas import UserResponse

router = APIRouter()


@router.get("/")
async def export_telemetry_csv(
    device_id: str | None = Query(None, description="Filter by a specific device ID"),
    metric_type_id: str | None = Query(
        None, description="Filter by metric (e.g., electricity, water)"
    ),
    start_time: datetime | None = Query(None, description="Start timestamp (ISO 8601)"),
    end_time: datetime | None = Query(None, description="End timestamp (ISO 8601)"),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_operator),
) -> Any:
    """
    Export time-series telemetry data as a streamed, downloadable CSV file.
    """
    query = db.query(TelemetryData)

    if device_id:
        query = query.filter(TelemetryData.device_id == device_id)
    if metric_type_id:
        query = query.filter(TelemetryData.metric_type_id == metric_type_id)
    if start_time:
        query = query.filter(TelemetryData.timestamp >= start_time)
    if end_time:
        query = query.filter(TelemetryData.timestamp <= end_time)

    query = query.order_by(TelemetryData.timestamp.desc())

    def iter_csv():
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(
            ["timestamp", "device_id", "metric_type_id", "value", "ingestion_status"]
        )
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for row in query.yield_per(1000):
            status_str = (
                row.ingestion_status.name
                if hasattr(row.ingestion_status, "name")
                else row.ingestion_status
            )
            writer.writerow(
                [
                    row.timestamp.isoformat(),
                    row.device_id,
                    row.metric_type_id,
                    row.value,
                    status_str,
                ]
            )
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"dmp_telemetry_export_{timestamp_str}.csv"

    return StreamingResponse(
        iter_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

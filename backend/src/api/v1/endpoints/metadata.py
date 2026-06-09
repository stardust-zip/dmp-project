from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from src.api.v1.deps import get_current_admin, get_current_user
from src.database import get_db
from src.models import (
    Device,
    DeviceMetricCapability,
    DeviceType,
    Location,
    LocationType,
    MetricType,
)
from src.schemas import (
    BuildingCreate,
    DeviceRegisterRequest,
    DeviceResponse,
    DeviceUpdate,
    LocationResponse,
    LocationUpdate,
    MetricTypeCreate,
    MetricTypeResponse,
    MetricTypeUpdate,
    SiteCreate,
    UserResponse,
)

router = APIRouter()


@router.get("/locations")
async def list_locations(
    q: str | None = Query(
        None,
        description="Search by location ID or display name.",
    ),
    location_type: str | None = Query(
        None,
        description="Filter by location type ID.",
    ),
    parent_id: str | None = Query(
        None,
        description="Filter buildings by parent site ID.",
    ),
    include_archived: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
) -> dict[str, list[LocationResponse]]:
    """
    Retrieve searchable locations for UI dropdowns.
    """
    query = db.query(Location)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(or_(Location.id.ilike(term), Location.name.ilike(term)))
    if location_type:
        query = query.filter(Location.location_type_id == location_type)
    if parent_id:
        query = query.filter(Location.parent_id == parent_id)

    locations = query.order_by(Location.id).limit(limit).all()
    return {
        "locations": [
            _location_response(loc)
            for loc in locations
            if include_archived or not _is_archived(loc)
        ]
    }


@router.post("/sites", response_model=LocationResponse, status_code=status.HTTP_201_CREATED)
async def create_site(
    payload: SiteCreate,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_admin),
):
    """
    Create a top-level site location.
    """
    _ensure_location_type(db, "site", "Top-level site")
    site = _create_location(
        db=db,
        location_id=payload.id,
        name=payload.name,
        location_type_id="site",
        parent_id=None,
        metadata=payload.metadata,
    )
    return _location_response(site)


@router.post(
    "/buildings", response_model=LocationResponse, status_code=status.HTTP_201_CREATED
)
async def create_building(
    payload: BuildingCreate,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_admin),
):
    """
    Create a building under an existing site.
    """
    site = db.query(Location).filter(Location.id == payload.site_id).one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found.")
    if _is_archived(site):
        raise HTTPException(status_code=422, detail="Cannot add a building to an archived site.")

    _ensure_location_type(db, payload.location_type_id, "Building")
    building = _create_location(
        db=db,
        location_id=payload.id,
        name=payload.name,
        location_type_id=payload.location_type_id,
        parent_id=site.id,
        metadata=payload.metadata,
    )
    return _location_response(building)


@router.patch("/locations/{location_id}", response_model=LocationResponse)
async def update_location(
    location_id: str,
    payload: LocationUpdate,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_admin),
):
    """
    Update location metadata or archive/unarchive a location.
    """
    location = _get_location_or_404(db, location_id)

    if payload.parent_id:
        parent = _get_location_or_404(db, payload.parent_id)
        if parent.id == location.id:
            raise HTTPException(status_code=422, detail="A location cannot be its own parent.")
        location.parent_id = parent.id
    if payload.location_type_id:
        _ensure_location_type(db, payload.location_type_id)
        location.location_type_id = payload.location_type_id
    if payload.name is not None:
        location.name = payload.name
    if payload.metadata is not None:
        location.metadata_ = {**(location.metadata_ or {}), **payload.metadata}
    if payload.archived is not None:
        metadata = dict(location.metadata_ or {})
        metadata["archived"] = payload.archived
        location.metadata_ = metadata

    db.commit()
    db.refresh(location)
    return _location_response(location)


@router.get("/metrics")
async def list_metrics(
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
) -> dict[str, list[MetricTypeResponse]]:
    """
    Retrieve all available metric types (utilities) for UI dropdowns.
    """
    metrics = db.query(MetricType).all()
    return {
        "metrics": [_metric_response(metric) for metric in metrics]
    }


@router.post("/metrics", response_model=MetricTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_metric(
    payload: MetricTypeCreate,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_admin),
):
    """
    Create a metric type such as electricity, gas, or temperature.
    """
    existing = db.query(MetricType).filter(MetricType.id == payload.id).one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Metric already exists.")

    metric = MetricType(id=payload.id, unit=payload.unit, description=payload.description)
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return _metric_response(metric)


@router.patch("/metrics/{metric_id}", response_model=MetricTypeResponse)
async def update_metric(
    metric_id: str,
    payload: MetricTypeUpdate,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_admin),
):
    """
    Update a metric type unit or description.
    """
    metric = _get_metric_or_404(db, metric_id)
    if payload.unit is not None:
        metric.unit = payload.unit
    if payload.description is not None:
        metric.description = payload.description

    db.commit()
    db.refresh(metric)
    return _metric_response(metric)


@router.post("/devices", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    payload: DeviceRegisterRequest,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_admin),
):
    """
    Register a meter/device under a building and declare supported metrics.
    """
    existing = db.query(Device).filter(Device.id == payload.id).one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Device already exists.")

    _get_location_or_404(db, payload.building_id)
    _ensure_device_type(db, payload.device_type_id)
    _ensure_metrics_exist(db, payload.metric_type_ids)

    device = Device(
        id=payload.id,
        location_id=payload.building_id,
        device_type_id=payload.device_type_id,
        status=payload.status,
    )
    db.add(device)
    db.flush()
    _replace_device_capabilities(db, device.id, payload.metric_type_ids)
    db.commit()
    db.refresh(device)
    return _device_response(device)


@router.get("/devices", response_model=dict[str, list[DeviceResponse]])
async def list_devices(
    building_id: str | None = Query(None),
    metric_type_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """
    List registered devices/meters, optionally filtered by building, metric, or status.
    """
    query = db.query(Device)
    if building_id:
        query = query.filter(Device.location_id == building_id)
    if status_filter:
        query = query.filter(Device.status == status_filter)
    if metric_type_id:
        query = query.join(DeviceMetricCapability).filter(
            DeviceMetricCapability.metric_type_id == metric_type_id
        )

    devices = query.order_by(Device.id).limit(limit).all()
    return {"devices": [_device_response(device) for device in devices]}


@router.patch("/devices/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: str,
    payload: DeviceUpdate,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_admin),
):
    """
    Update a device location, type, status, or metric capabilities.
    """
    device = _get_device_or_404(db, device_id)
    if payload.building_id is not None:
        _get_location_or_404(db, payload.building_id)
        device.location_id = payload.building_id
    if payload.device_type_id is not None:
        _ensure_device_type(db, payload.device_type_id)
        device.device_type_id = payload.device_type_id
    if payload.status is not None:
        device.status = payload.status
    if payload.metric_type_ids is not None:
        _ensure_metrics_exist(db, payload.metric_type_ids)
        _replace_device_capabilities(db, device.id, payload.metric_type_ids)

    db.commit()
    db.refresh(device)
    return _device_response(device)


@router.post("/devices/{device_id}/deactivate", response_model=DeviceResponse)
async def deactivate_device(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: UserResponse = Depends(get_current_admin),
):
    """
    Deactivate a device without deleting its history.
    """
    device = _get_device_or_404(db, device_id)
    device.status = "Inactive"
    db.commit()
    db.refresh(device)
    return _device_response(device)


def _create_location(
    *,
    db: Session,
    location_id: str,
    name: str,
    location_type_id: str,
    parent_id: str | None,
    metadata: dict[str, Any] | None,
) -> Location:
    existing = db.query(Location).filter(Location.id == location_id).one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Location already exists.")

    location = Location(
        id=location_id,
        parent_id=parent_id,
        location_type_id=location_type_id,
        name=name,
        metadata_=metadata or {},
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


def _location_response(location: Location) -> LocationResponse:
    metadata = dict(location.metadata_ or {})
    return LocationResponse(
        id=location.id,
        parent_id=location.parent_id,
        name=location.name,
        location_type=location.location_type_id,
        metadata=metadata,
        archived=bool(metadata.get("archived", False)),
    )


def _metric_response(metric: MetricType) -> MetricTypeResponse:
    return MetricTypeResponse(
        id=metric.id,
        unit=metric.unit,
        description=metric.description,
    )


def _device_response(device: Device) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        building_id=device.location_id,
        device_type_id=device.device_type_id,
        status=device.status,
        metric_type_ids=[
            capability.metric_type_id
            for capability in sorted(
                device.metric_capabilities,
                key=lambda item: item.metric_type_id,
            )
        ],
    )


def _is_archived(location: Location) -> bool:
    return bool((location.metadata_ or {}).get("archived", False))


def _get_location_or_404(db: Session, location_id: str) -> Location:
    location = db.query(Location).filter(Location.id == location_id).one_or_none()
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found.")
    return location


def _get_metric_or_404(db: Session, metric_id: str) -> MetricType:
    metric = db.query(MetricType).filter(MetricType.id == metric_id).one_or_none()
    if metric is None:
        raise HTTPException(status_code=404, detail="Metric not found.")
    return metric


def _get_device_or_404(db: Session, device_id: str) -> Device:
    device = db.query(Device).filter(Device.id == device_id).one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found.")
    return device


def _ensure_location_type(
    db: Session, location_type_id: str, description: str | None = None
) -> None:
    location_type = (
        db.query(LocationType).filter(LocationType.id == location_type_id).one_or_none()
    )
    if location_type is None:
        db.add(LocationType(id=location_type_id, description=description))
        db.flush()


def _ensure_device_type(db: Session, device_type_id: str) -> None:
    device_type = db.query(DeviceType).filter(DeviceType.id == device_type_id).one_or_none()
    if device_type is None:
        db.add(DeviceType(id=device_type_id, description="Registered device"))
        db.flush()


def _ensure_metrics_exist(db: Session, metric_type_ids: list[str]) -> None:
    if not metric_type_ids:
        return
    known = {
        row[0]
        for row in db.query(MetricType.id)
        .filter(MetricType.id.in_(metric_type_ids))
        .all()
    }
    missing = sorted(set(metric_type_ids).difference(known))
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown metric(s): {', '.join(missing)}",
        )


def _replace_device_capabilities(
    db: Session, device_id: str, metric_type_ids: list[str]
) -> None:
    db.query(DeviceMetricCapability).filter(
        DeviceMetricCapability.device_id == device_id
    ).delete(synchronize_session=False)
    for metric_type_id in sorted(set(metric_type_ids)):
        db.add(
            DeviceMetricCapability(
                device_id=device_id,
                metric_type_id=metric_type_id,
            )
        )

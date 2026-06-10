import re
from dataclasses import dataclass
from datetime import datetime, time, timezone

import mlflow
import mlflow.pyfunc
import pandas as pd
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from sqlalchemy.orm import Session
from src.core.config import settings
from src.models import Device, Location, MetricType, TelemetryData
from src.schemas import (
    ExpectedActualPoint,
    ExpectedActualReportRequest,
    ExpectedActualReportResponse,
    PredictionHourlyPoint,
    PredictionScenarioRequest,
    PredictionScenarioResponse,
)


PREDICTION_FEATURE_COLUMNS = [
    "sqm",
    "hour",
    "day_of_week",
    "month",
    "closing_hour",
    "is_open",
    "primaryspaceusage",
    "metric_type",
]

DEFAULT_METRIC_UNITS = {
    "electricity": "kWh",
    "solar": "kWh",
    "steam": "kg",
    "hotwater": "m3",
    "chilledwater": "m3",
    "gas": "m3",
    "water": "m3",
    "irrigation": "m3",
}


@dataclass(frozen=True)
class BuildingProfile:
    building_id: str
    site_id: str
    primaryspaceusage: str
    sqm: float


@dataclass(frozen=True)
class LoadedPredictionModel:
    name: str
    version: str
    model: object


class PredictionModelRepository:
    def __init__(self, client: MlflowClient | None = None):
        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        self.client = client or MlflowClient()

    def load(self, model_name: str) -> LoadedPredictionModel:
        errors = []
        for version in self._candidate_versions(model_name):
            try:
                model = mlflow.pyfunc.load_model(f"models:/{model_name}/{version}")
                return LoadedPredictionModel(name=model_name, version=version, model=model)
            except MlflowException as exc:
                errors.append(f"{model_name}/{version}: {exc}")
                continue

        if errors:
            raise ValueError(
                "No loadable prediction model artifact found. " + " | ".join(errors)
            )
        raise ValueError(f"No registered prediction model found: {model_name}")

    def load_first_available(self, model_names: list[str]) -> LoadedPredictionModel:
        errors = []
        for model_name in dict.fromkeys(model_names):
            try:
                return self.load(model_name)
            except ValueError as exc:
                errors.append(str(exc))
                continue

        raise ValueError(
            "No loadable registered prediction model found. Tried: "
            + ", ".join(model_names)
            + (". " + " | ".join(errors) if errors else "")
        )

    def _candidate_versions(self, model_name: str) -> list[str]:
        candidates = []
        try:
            production = self.client.get_model_version_by_alias(model_name, "production")
            candidates.append(str(production.version))
        except Exception:
            pass

        versions = list(self.client.search_model_versions(f"name = '{model_name}'"))
        if not versions:
            return candidates

        active_versions = [
            version
            for version in versions
            if (getattr(version, "tags", {}) or {}).get("active") == "true"
            or (getattr(version, "tags", {}) or {}).get("stage") == "production"
            or getattr(version, "current_stage", None) == "Production"
        ]
        ordered_versions = sorted(
            [*active_versions, *versions],
            key=lambda version: int(version.version),
            reverse=True,
        )
        candidates.extend(str(version.version) for version in ordered_versions)
        return list(dict.fromkeys(candidates))


class PredictionFeatureBuilder:
    def building_profile(self, db: Session, site_id: str, building_id: str) -> BuildingProfile:
        location = db.query(Location).filter(Location.id == building_id).one_or_none()
        if location is None:
            raise ValueError(f"Unknown building: {building_id}")

        metadata = location.metadata_ or {}
        sqm = metadata.get("sqm")
        if sqm is None:
            raise ValueError(f"Building '{building_id}' has no sqm metadata")

        return BuildingProfile(
            building_id=building_id,
            site_id=location.parent_id or site_id,
            primaryspaceusage=str(location.location_type_id or "Unknown"),
            sqm=float(sqm),
        )

    def scenario_features(
        self,
        request: PredictionScenarioRequest,
        profile: BuildingProfile,
    ) -> pd.DataFrame:
        opening = _parse_clock_hour(request.opening_time)
        closing = _parse_clock_hour(request.closing_time)
        if closing <= opening:
            raise ValueError("closing_time must be after opening_time")

        scenario_day = _to_utc(request.scenario_date)
        timestamps = [
            scenario_day.replace(hour=hour, minute=0, second=0, microsecond=0)
            for hour in range(opening, closing)
        ]
        return self._feature_frame(
            timestamps=timestamps,
            profile=profile,
            metric_type=request.metric_type,
            closing_hour=closing,
        )

    def report_features(
        self,
        actual_df: pd.DataFrame,
        request: ExpectedActualReportRequest,
        profile: BuildingProfile,
    ) -> pd.DataFrame:
        closing = _parse_clock_hour(request.closing_time)
        return self._feature_frame(
            timestamps=actual_df["timestamp"].tolist(),
            profile=profile,
            metric_type=request.metric_type,
            closing_hour=closing,
        )

    def _feature_frame(
        self,
        *,
        timestamps: list[datetime],
        profile: BuildingProfile,
        metric_type: str,
        closing_hour: int,
    ) -> pd.DataFrame:
        rows = []
        for timestamp in timestamps:
            ts = _to_utc(timestamp)
            rows.append(
                {
                    "timestamp": ts,
                    "sqm": profile.sqm,
                    "hour": ts.hour,
                    "day_of_week": ts.weekday(),
                    "month": ts.month,
                    "closing_hour": closing_hour,
                    "is_open": int(ts.hour < closing_hour),
                    "primaryspaceusage": profile.primaryspaceusage,
                    "metric_type": metric_type.strip().lower(),
                }
            )
        return pd.DataFrame(rows)


class PredictionService:
    def __init__(
        self,
        model_repository: PredictionModelRepository | None = None,
        feature_builder: PredictionFeatureBuilder | None = None,
    ):
        self.model_repository = model_repository or PredictionModelRepository()
        self.feature_builder = feature_builder or PredictionFeatureBuilder()

    def predict_scenario(
        self,
        db: Session,
        request: PredictionScenarioRequest,
    ) -> PredictionScenarioResponse:
        profile = self.feature_builder.building_profile(
            db, request.site_id, request.building_id
        )
        model_names = _prediction_model_candidates(
            request.site_id,
            request.building_id,
            request.metric_type,
            request.model_name,
        )
        loaded = self.model_repository.load_first_available(model_names)
        features = self.feature_builder.scenario_features(request, profile)
        predictions = _predict(loaded.model, features)
        unit = _metric_unit(db, request.metric_type)

        points = [
            PredictionHourlyPoint(timestamp=row.timestamp, expected_value=float(value))
            for row, value in zip(features.itertuples(index=False), predictions)
        ]
        estimated_value = float(sum(point.expected_value for point in points))
        estimated_cost = (
            estimated_value * request.unit_rate
            if request.unit_rate is not None
            else None
        )
        return PredictionScenarioResponse(
            site_id=request.site_id,
            building_id=request.building_id,
            metric_type=request.metric_type,
            model_name=loaded.name,
            model_version=loaded.version,
            estimated_value=estimated_value,
            estimated_cost=estimated_cost,
            unit=unit,
            points=points,
        )

    def expected_vs_actual(
        self,
        db: Session,
        request: ExpectedActualReportRequest,
    ) -> ExpectedActualReportResponse:
        profile = self.feature_builder.building_profile(
            db, request.site_id, request.building_id
        )
        actual_df = _load_actual_usage(db, request)
        if actual_df.empty:
            raise ValueError("No actual telemetry found for the selected report range")

        model_names = _prediction_model_candidates(
            request.site_id,
            request.building_id,
            request.metric_type,
            request.model_name,
        )
        loaded = self.model_repository.load_first_available(model_names)
        features = self.feature_builder.report_features(actual_df, request, profile)
        predictions = _predict(loaded.model, features)
        unit = _metric_unit(db, request.metric_type)

        points: list[ExpectedActualPoint] = []
        for row, expected in zip(actual_df.itertuples(index=False), predictions):
            actual = float(row.actual_value)
            expected_value = float(expected)
            variance = actual - expected_value
            variance_percent = (
                (variance / expected_value) * 100 if expected_value != 0 else None
            )
            points.append(
                ExpectedActualPoint(
                    timestamp=row.timestamp,
                    expected_value=expected_value,
                    actual_value=actual,
                    variance=variance,
                    variance_percent=variance_percent,
                )
            )

        expected_total = float(sum(point.expected_value for point in points))
        actual_total = float(sum(point.actual_value or 0 for point in points))
        variance_total = actual_total - expected_total
        variance_percent = (
            (variance_total / expected_total) * 100 if expected_total != 0 else None
        )
        return ExpectedActualReportResponse(
            site_id=request.site_id,
            building_id=request.building_id,
            metric_type=request.metric_type,
            model_name=loaded.name,
            model_version=loaded.version,
            expected_total=expected_total,
            actual_total=actual_total,
            variance_total=variance_total,
            variance_percent=variance_percent,
            unit=unit,
            points=points,
        )


def _predict(model: object, features: pd.DataFrame) -> list[float]:
    predictions = model.predict(features[PREDICTION_FEATURE_COLUMNS])  # type: ignore[attr-defined]
    return [float(value) for value in predictions]


def _load_actual_usage(
    db: Session,
    request: ExpectedActualReportRequest,
) -> pd.DataFrame:
    start = _to_utc(request.start_time)
    end = _to_utc(request.end_time)
    rows = (
        db.query(
            TelemetryData.timestamp,
            TelemetryData.value.label("actual_value"),
        )
        .join(Device, Device.id == TelemetryData.device_id)
        .filter(Device.location_id == request.building_id)
        .filter(TelemetryData.metric_type_id == request.metric_type.strip().lower())
        .filter(TelemetryData.timestamp >= start)
        .filter(TelemetryData.timestamp <= end)
        .order_by(TelemetryData.timestamp)
        .all()
    )
    return pd.DataFrame(
        [
            {"timestamp": _to_utc(row.timestamp), "actual_value": float(row.actual_value)}
            for row in rows
        ]
    )


def _metric_unit(db: Session, metric_type: str) -> str:
    metric_id = metric_type.strip().lower()
    metric = db.query(MetricType).filter(MetricType.id == metric_id).one_or_none()
    if metric is not None and metric.unit:
        return str(metric.unit)
    return DEFAULT_METRIC_UNITS.get(metric_id, "units")


def _registered_prediction_model_name(site_id: str, metric_type: str) -> str:
    return _safe_model_name(f"dmp_energy_prediction_{site_id}_{metric_type.strip().lower()}")


def _prediction_model_candidates(
    site_id: str,
    building_id: str,
    metric_type: str,
    explicit_model_name: str | None,
) -> list[str]:
    if explicit_model_name:
        return [explicit_model_name]

    metric = metric_type.strip().lower()
    return [
        _registered_prediction_model_name(site_id, metric),
        _registered_prediction_model_name(building_id, metric),
    ]


def _safe_model_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return normalized.strip("._-") or "dmp_energy_model"


def _parse_clock_hour(value: str) -> int:
    parsed = time.fromisoformat(value)
    if parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError("opening_time and closing_time must be whole-hour values")
    return parsed.hour


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

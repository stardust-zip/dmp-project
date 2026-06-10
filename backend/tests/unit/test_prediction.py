from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import mlflow.pyfunc
import pandas as pd
from mlflow.exceptions import MlflowException
from src.ml.prediction import (
    LoadedPredictionModel,
    PredictionModelRepository,
    PredictionService,
)
from src.schemas import ExpectedActualReportRequest, PredictionScenarioRequest


class FakePredictionModel:
    def predict(self, features: pd.DataFrame):
        return [100.0 + float(row.hour) + (20.0 if row.is_open else 0.0) for row in features.itertuples()]


class FakeModelRepository:
    def load(self, model_name: str) -> LoadedPredictionModel:
        if model_name == "dmp_energy_prediction_SiteA_electricity":
            raise ValueError("No registered prediction model found")
        return LoadedPredictionModel(
            name=model_name,
            version="7",
            model=FakePredictionModel(),
        )

    def load_first_available(self, model_names: list[str]) -> LoadedPredictionModel:
        for model_name in model_names:
            try:
                return self.load(model_name)
            except ValueError:
                continue
        raise ValueError("No registered prediction model found")


class FakeQuery:
    def __init__(self, *, one=None, rows=None):
        self._one = one
        self._rows = rows or []

    def filter(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self._one

    def all(self):
        return self._rows


def _fake_db(actual_rows=None):
    location = SimpleNamespace(
        id="BuildingA",
        parent_id="SiteA",
        location_type_id="Education",
        metadata_={"sqm": 1200.0},
    )
    db = Mock()
    db.query.side_effect = [
        FakeQuery(one=location),
        FakeQuery(rows=actual_rows or []),
    ]
    return db


def test_prediction_scenario_uses_closing_time_to_build_operating_window():
    service = PredictionService(model_repository=FakeModelRepository())
    request = PredictionScenarioRequest(
        site_id="SiteA",
        building_id="BuildingA",
        metric_type="electricity",
        scenario_date="2026-06-10T00:00:00Z",
        opening_time="18:00",
        closing_time="22:00",
        energy_rate_per_kwh=0.2,
    )

    response = service.predict_scenario(_fake_db(), request)

    assert response.model_name == "dmp_energy_prediction_BuildingA_electricity"
    assert response.model_version == "7"
    assert len(response.points) == 4
    assert response.points[0].timestamp.hour == 18
    assert response.points[-1].timestamp.hour == 21
    assert response.estimated_value == sum(point.expected_value for point in response.points)
    assert response.estimated_cost == response.estimated_value * 0.2


def test_expected_vs_actual_returns_variance_points_and_totals():
    service = PredictionService(model_repository=FakeModelRepository())
    actual_rows = [
        SimpleNamespace(
            timestamp=datetime(2026, 6, 1, 8, tzinfo=timezone.utc),
            actual_value=140.0,
        ),
        SimpleNamespace(
            timestamp=datetime(2026, 6, 1, 19, tzinfo=timezone.utc),
            actual_value=150.0,
        ),
    ]
    request = ExpectedActualReportRequest(
        site_id="SiteA",
        building_id="BuildingA",
        metric_type="electricity",
        start_time="2026-06-01T00:00:00Z",
        end_time="2026-06-30T23:59:59Z",
        closing_time="18:00",
    )

    response = service.expected_vs_actual(_fake_db(actual_rows), request)

    assert len(response.points) == 2
    assert response.points[0].actual_value == 140.0
    assert response.points[0].expected_value == 128.0
    assert response.points[0].variance == 12.0
    assert response.points[1].expected_value == 119.0
    assert response.expected_total == 247.0
    assert response.actual_total == 290.0
    assert response.variance_total == 43.0


def test_model_repository_skips_broken_artifact_versions(monkeypatch):
    client = Mock()
    client.get_model_version_by_alias.side_effect = Exception("no alias")
    client.search_model_versions.return_value = [
        SimpleNamespace(version="1", tags={}),
        SimpleNamespace(version="2", tags={"active": "true"}),
    ]
    loads = []

    def load_model(uri: str):
        loads.append(uri)
        if uri.endswith("/2"):
            raise MlflowException("No such artifact")
        return FakePredictionModel()

    monkeypatch.setattr(mlflow.pyfunc, "load_model", load_model)

    repository = PredictionModelRepository(client=client)
    loaded = repository.load("dmp_energy_prediction_BuildingA_electricity")

    assert loaded.version == "1"
    assert loads == [
        "models:/dmp_energy_prediction_BuildingA_electricity/2",
        "models:/dmp_energy_prediction_BuildingA_electricity/1",
    ]

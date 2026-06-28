from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import mlflow.pyfunc
import pandas as pd
from mlflow.exceptions import MlflowException
from src.ml.prediction import (
    LoadedPredictionModel,
    PredictionModelRepository,
    PredictionService,
)
from src.models import Location, MetricType
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


def _fake_db(actual_rows=None, metric_unit="kWh"):
    location = SimpleNamespace(
        id="BuildingA",
        parent_id="SiteA",
        location_type_id="Education",
        metadata_={"sqm": 1200.0},
    )
    metric = SimpleNamespace(id="electricity", unit=metric_unit)
    db = Mock()

    def query(*entities):
        if entities and entities[0] is Location:
            return FakeQuery(one=location)
        if entities and entities[0] is MetricType:
            return FakeQuery(one=metric)
        return FakeQuery(rows=actual_rows or [])

    db.query.side_effect = query
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
        unit_rate=0.2,
    )

    response = service.predict_scenario(_fake_db(), request)

    assert response.model_name == "dmp_energy_prediction_BuildingA_electricity"
    assert response.model_version == "7"
    assert len(response.points) == 4
    assert response.points[0].timestamp.hour == 18
    assert response.points[-1].timestamp.hour == 21
    assert response.estimated_value == sum(point.expected_value for point in response.points)
    assert response.estimated_cost == response.estimated_value * 0.2
    assert response.unit == "kWh"


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
    assert response.unit == "kWh"


def test_prediction_uses_metric_unit_from_metadata():
    service = PredictionService(model_repository=FakeModelRepository())
    request = PredictionScenarioRequest(
        site_id="SiteA",
        building_id="BuildingA",
        metric_type="water",
        scenario_date="2026-06-10T00:00:00Z",
        opening_time="08:00",
        closing_time="10:00",
        unit_rate=1.5,
    )

    response = service.predict_scenario(_fake_db(metric_unit="m3"), request)

    assert response.model_name == "dmp_energy_prediction_SiteA_water"
    assert response.unit == "m3"
    assert response.estimated_cost == response.estimated_value * 1.5


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


# ---------------------------------------------------------------------------
# PredictionLogger injection and _log_prediction_batch
# ---------------------------------------------------------------------------


class CapturingLogger:
    """Test double for PredictionLogger that records calls without touching a DB."""

    def __init__(self):
        self.batches: list[list[dict]] = []
        self.fill_calls: list[tuple] = []

    def log_batch(self, db, predictions: list[dict]) -> list:
        self.batches.append(list(predictions))
        return []

    def fill_actuals(self, db, building_id: str, metric_type_id: str, actuals: dict) -> int:
        self.fill_calls.append((building_id, metric_type_id, actuals))
        return len(actuals)


class TestPredictionLoggingIntegration:
    """Verify that predict_scenario and expected_vs_actual route through PredictionLogger."""

    def test_injected_logger_is_used_instead_of_default(self):
        logger = CapturingLogger()
        service = PredictionService(
            model_repository=FakeModelRepository(),
            prediction_logger=logger,
        )
        request = PredictionScenarioRequest(
            site_id="SiteA",
            building_id="BuildingA",
            metric_type="electricity",
            scenario_date="2026-06-10T00:00:00Z",
            opening_time="09:00",
            closing_time="11:00",
            unit_rate=0.2,
        )

        service.predict_scenario(_fake_db(), request)

        assert len(logger.batches) == 1

    def test_log_batch_receives_one_entry_per_prediction_hour(self):
        logger = CapturingLogger()
        service = PredictionService(
            model_repository=FakeModelRepository(),
            prediction_logger=logger,
        )
        request = PredictionScenarioRequest(
            site_id="SiteA",
            building_id="BuildingA",
            metric_type="electricity",
            scenario_date="2026-06-10T00:00:00Z",
            opening_time="08:00",
            closing_time="11:00",  # 3 hours → 3 points
            unit_rate=0.1,
        )

        service.predict_scenario(_fake_db(), request)

        assert len(logger.batches[0]) == 3

    def test_logged_entries_contain_required_monitoring_fields(self):
        logger = CapturingLogger()
        service = PredictionService(
            model_repository=FakeModelRepository(),
            prediction_logger=logger,
        )
        request = PredictionScenarioRequest(
            site_id="SiteA",
            building_id="BuildingA",
            metric_type="electricity",
            scenario_date="2026-06-10T00:00:00Z",
            opening_time="10:00",
            closing_time="11:00",
            unit_rate=None,
        )

        service.predict_scenario(_fake_db(), request)

        entry = logger.batches[0][0]
        assert entry["building_id"] == "BuildingA"
        assert entry["metric_type_id"] == "electricity"
        assert isinstance(entry["predicted_value"], float)
        assert "model_name" in entry
        assert "model_version" in entry

    def test_logger_failure_does_not_propagate_to_caller(self):
        """A broken logger must not prevent the prediction response from being returned."""
        broken_logger = MagicMock()
        broken_logger.log_batch.side_effect = RuntimeError("DB connection lost")

        service = PredictionService(
            model_repository=FakeModelRepository(),
            prediction_logger=broken_logger,
        )
        request = PredictionScenarioRequest(
            site_id="SiteA",
            building_id="BuildingA",
            metric_type="electricity",
            scenario_date="2026-06-10T00:00:00Z",
            opening_time="08:00",
            closing_time="09:00",
            unit_rate=0.2,
        )

        # Must not raise; the prediction result is returned even when logging fails
        response = service.predict_scenario(_fake_db(), request)
        assert response is not None


# ---------------------------------------------------------------------------
# _log_expected_actual_batch
# ---------------------------------------------------------------------------


class TestExpectedActualLogging:
    def test_fill_actuals_is_called_when_actual_values_are_present(self):
        logger = CapturingLogger()
        service = PredictionService(
            model_repository=FakeModelRepository(),
            prediction_logger=logger,
        )
        actual_rows = [
            SimpleNamespace(
                timestamp=datetime(2026, 6, 1, 8, tzinfo=timezone.utc),
                actual_value=140.0,
            ),
            SimpleNamespace(
                timestamp=datetime(2026, 6, 1, 9, tzinfo=timezone.utc),
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

        service.expected_vs_actual(_fake_db(actual_rows), request)

        assert len(logger.batches) == 1
        assert len(logger.fill_calls) == 1

    def test_fill_actuals_receives_correct_building_and_metric_type(self):
        logger = CapturingLogger()
        service = PredictionService(
            model_repository=FakeModelRepository(),
            prediction_logger=logger,
        )
        actual_rows = [
            SimpleNamespace(
                timestamp=datetime(2026, 6, 1, 10, tzinfo=timezone.utc),
                actual_value=200.0,
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

        service.expected_vs_actual(_fake_db(actual_rows), request)

        building_id, metric_type_id, _ = logger.fill_calls[0]
        assert building_id == "BuildingA"
        assert metric_type_id == "electricity"

    def test_expected_actual_logger_failure_does_not_propagate(self):
        broken_logger = MagicMock()
        broken_logger.log_batch.side_effect = RuntimeError("network error")

        service = PredictionService(
            model_repository=FakeModelRepository(),
            prediction_logger=broken_logger,
        )
        actual_rows = [
            SimpleNamespace(
                timestamp=datetime(2026, 6, 1, 8, tzinfo=timezone.utc),
                actual_value=140.0,
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
        assert response is not None

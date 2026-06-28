"""Unit tests for the experiments comparison endpoint.

Covers:
  - Pure helpers (no I/O):
      _parse_and_validate_versions, _resolve_evaluation_window,
      _infer_training_data_attrs, _strip_system_tags,
      _compute_common_keys, _build_version_detail
  - API endpoint: GET /api/v1/models/{name}/experiments/compare
      (TestClient + mocked MlflowClient + mocked DB dependencies)
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.v1.deps import get_current_ai_engineer_or_admin
from src.api.v1.endpoints.experiments import (
    _compute_common_keys,
    _infer_training_data_attrs,
    _parse_and_validate_versions,
    _resolve_evaluation_window,
    _strip_system_tags,
    _build_version_detail,
)
from src.database import get_db
from src.main import app
from src.schemas import ExperimentVersionDetail, UserResponse


# ---------------------------------------------------------------------------
# _parse_and_validate_versions
# ---------------------------------------------------------------------------


class TestParseAndValidateVersions:
    def test_two_versions_is_valid(self):
        assert _parse_and_validate_versions("1,2") == ["1", "2"]

    def test_ten_versions_is_the_valid_maximum(self):
        csv = ",".join(str(i) for i in range(1, 11))
        assert _parse_and_validate_versions(csv) == [str(i) for i in range(1, 11)]

    def test_whitespace_around_versions_is_stripped(self):
        assert _parse_and_validate_versions(" 1 , 2 , 3 ") == ["1", "2", "3"]

    def test_single_version_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _parse_and_validate_versions("1")
        assert exc.value.status_code == 400

    def test_empty_string_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _parse_and_validate_versions("")
        assert exc.value.status_code == 400

    def test_eleven_versions_raises_400(self):
        csv = ",".join(str(i) for i in range(1, 12))
        with pytest.raises(HTTPException) as exc:
            _parse_and_validate_versions(csv)
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# _resolve_evaluation_window
# ---------------------------------------------------------------------------


class TestResolveEvaluationWindow:
    def test_explicit_start_and_end_are_returned_unchanged(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, tzinfo=timezone.utc)
        result_start, result_end = _resolve_evaluation_window(start, end)
        assert result_start == start
        assert result_end == end

    def test_none_end_defaults_to_approximately_now(self):
        before = datetime.now(timezone.utc)
        _, result_end = _resolve_evaluation_window(None, None)
        after = datetime.now(timezone.utc)
        assert before <= result_end <= after

    def test_none_start_defaults_to_30_days_before_end(self):
        fixed_end = datetime(2026, 6, 1, tzinfo=timezone.utc)
        result_start, _ = _resolve_evaluation_window(None, fixed_end)
        assert result_start == fixed_end - timedelta(days=30)

    def test_explicit_start_with_none_end_uses_now(self):
        start = datetime(2026, 5, 1, tzinfo=timezone.utc)
        result_start, result_end = _resolve_evaluation_window(start, None)
        assert result_start == start
        assert result_end >= start


# ---------------------------------------------------------------------------
# _infer_training_data_attrs
# ---------------------------------------------------------------------------


class TestInferTrainingDataAttrs:
    def test_feature_count_from_params_is_coerced_to_int(self):
        attrs = _infer_training_data_attrs(run_tags={}, run_params={"feature_count": "12"})
        assert attrs["feature_count"] == 12

    def test_feature_count_from_tags_is_used_as_fallback(self):
        attrs = _infer_training_data_attrs(run_tags={"feature_count": "7"}, run_params={})
        assert attrs["feature_count"] == 7

    def test_float_string_feature_count_is_truncated_to_int(self):
        attrs = _infer_training_data_attrs(run_tags={}, run_params={"feature_count": "12.9"})
        assert attrs["feature_count"] == 12

    def test_invalid_feature_count_yields_none(self):
        attrs = _infer_training_data_attrs(run_tags={}, run_params={"feature_count": "nan"})
        assert attrs["feature_count"] is None

    def test_data_source_is_read_from_data_source_tag(self):
        attrs = _infer_training_data_attrs(run_tags={"data_source": "csv"}, run_params={})
        assert attrs["data_source"] == "csv"

    def test_datasource_used_tag_is_the_fallback_for_data_source(self):
        attrs = _infer_training_data_attrs(run_tags={"datasource_used": "database"}, run_params={})
        assert attrs["data_source"] == "database"

    def test_training_date_range_is_extracted_from_tags(self):
        attrs = _infer_training_data_attrs(
            run_tags={"training_start": "2025-01-01", "training_end": "2026-01-01"},
            run_params={},
        )
        assert attrs["training_start"] == "2025-01-01"
        assert attrs["training_end"] == "2026-01-01"

    def test_all_values_are_none_when_tags_and_params_are_empty(self):
        attrs = _infer_training_data_attrs(run_tags={}, run_params={})
        assert attrs == {
            "data_source": None,
            "training_start": None,
            "training_end": None,
            "feature_count": None,
        }


# ---------------------------------------------------------------------------
# _strip_system_tags
# ---------------------------------------------------------------------------


class TestStripSystemTags:
    def test_mlflow_prefixed_keys_are_removed(self):
        tags = {"mlflow.runName": "run-1", "mlflow.source.type": "LOCAL", "algorithm": "xgb"}
        result = _strip_system_tags(tags)
        assert "mlflow.runName" not in result
        assert "mlflow.source.type" not in result

    def test_non_mlflow_keys_are_preserved(self):
        tags = {"algorithm": "xgboost", "model_task": "forecasting"}
        assert _strip_system_tags(tags) == tags

    def test_empty_input_returns_empty_dict(self):
        assert _strip_system_tags({}) == {}

    def test_all_mlflow_keys_returns_empty_dict(self):
        assert _strip_system_tags({"mlflow.foo": "a", "mlflow.bar": "b"}) == {}


# ---------------------------------------------------------------------------
# _compute_common_keys
# ---------------------------------------------------------------------------


class TestComputeCommonKeys:
    def _version_detail(self, hyperparameters: dict, evaluation_metrics: dict) -> ExperimentVersionDetail:
        return ExperimentVersionDetail(
            version="1",
            run_id="run-abc",
            hyperparameters=hyperparameters,
            evaluation_metrics=evaluation_metrics,
        )

    def test_returns_sorted_intersection_of_hyperparameter_keys(self):
        details = [
            self._version_detail({"lr": "0.01", "depth": "5"}, {}),
            self._version_detail({"lr": "0.1", "n_est": "100"}, {}),
        ]
        assert _compute_common_keys(details, "hyperparameters") == ["lr"]

    def test_all_keys_shared_by_all_versions_are_returned(self):
        details = [
            self._version_detail({"a": "1", "b": "2"}, {}),
            self._version_detail({"a": "3", "b": "4"}, {}),
        ]
        assert sorted(_compute_common_keys(details, "hyperparameters")) == ["a", "b"]

    def test_disjoint_keys_returns_empty_list(self):
        details = [
            self._version_detail({"x": "1"}, {}),
            self._version_detail({"y": "2"}, {}),
        ]
        assert _compute_common_keys(details, "hyperparameters") == []

    def test_empty_version_list_returns_empty_list(self):
        assert _compute_common_keys([], "hyperparameters") == []

    def test_works_for_evaluation_metrics_field(self):
        details = [
            self._version_detail({}, {"mae": 1.0, "rmse": 2.0}),
            self._version_detail({}, {"mae": 1.5, "mape": 3.0}),
        ]
        assert _compute_common_keys(details, "evaluation_metrics") == ["mae"]

    def test_result_is_always_sorted_alphabetically(self):
        details = [
            self._version_detail({"z": "1", "a": "2", "m": "3"}, {}),
            self._version_detail({"z": "4", "a": "5", "m": "6"}, {}),
        ]
        result = _compute_common_keys(details, "hyperparameters")
        assert result == sorted(result)


# ---------------------------------------------------------------------------
# _build_version_detail
# ---------------------------------------------------------------------------


class TestBuildVersionDetail:
    def _run_detail(self, **overrides) -> dict:
        base = {
            "run_id": "run-001",
            "params": {"n_estimators": "100", "max_depth": "5"},
            "metrics": {"train_mae": 1.5},
            "tags": {"algorithm": "XGBoost", "model_task": "forecasting"},
            "start_time": 1700000000000,
            "end_time": 1700003600000,
            "status": "FINISHED",
        }
        base.update(overrides)
        return base

    def test_version_and_run_id_are_passed_through(self):
        detail = _build_version_detail(
            version="5",
            run_detail=self._run_detail(run_id="run-xyz"),
            eval_metrics={},
            training_stats={"building_count": None, "metric_count": None, "row_count": None},
            current_stage="Production",
        )
        assert detail.version == "5"
        assert detail.run_id == "run-xyz"

    def test_algorithm_is_extracted_from_tags(self):
        detail = _build_version_detail(
            version="1",
            run_detail=self._run_detail(tags={"algorithm": "LightGBM", "model_task": "forecasting"}),
            eval_metrics={},
            training_stats={"building_count": None, "metric_count": None, "row_count": None},
            current_stage=None,
        )
        assert detail.algorithm == "LightGBM"

    def test_mlflow_system_tags_are_stripped(self):
        detail = _build_version_detail(
            version="1",
            run_detail=self._run_detail(
                tags={"algorithm": "XGBoost", "mlflow.runName": "my-run", "model_task": "forecasting"}
            ),
            eval_metrics={},
            training_stats={"building_count": None, "metric_count": None, "row_count": None},
            current_stage=None,
        )
        assert "mlflow.runName" not in detail.tags
        assert "algorithm" in detail.tags

    def test_training_metrics_are_cast_to_float(self):
        detail = _build_version_detail(
            version="1",
            run_detail=self._run_detail(metrics={"train_mae": 1, "val_rmse": 2}),
            eval_metrics={},
            training_stats={"building_count": None, "metric_count": None, "row_count": None},
            current_stage=None,
        )
        assert all(isinstance(v, float) for v in detail.training_metrics.values())

    def test_evaluation_metrics_are_forwarded(self):
        eval_m = {"mae": 1.2, "rmse": 2.3}
        detail = _build_version_detail(
            version="1",
            run_detail=self._run_detail(),
            eval_metrics=eval_m,
            training_stats={"building_count": None, "metric_count": None, "row_count": None},
            current_stage="Staging",
        )
        assert detail.evaluation_metrics == eval_m
        assert detail.current_stage == "Staging"

    def test_training_stats_are_mapped_to_correct_fields(self):
        detail = _build_version_detail(
            version="1",
            run_detail=self._run_detail(),
            eval_metrics={},
            training_stats={"building_count": 5, "metric_count": 2, "row_count": 1000},
            current_stage=None,
        )
        assert detail.training_building_count == 5
        assert detail.training_metric_count == 2
        assert detail.training_row_count == 1000


# ---------------------------------------------------------------------------
# API endpoint: GET /api/v1/models/{name}/experiments/compare
# ---------------------------------------------------------------------------


@pytest.fixture()
def _mock_user() -> UserResponse:
    return UserResponse(
        id=str(uuid.uuid4()),
        email="engineer@example.com",
        full_name="Test Engineer",
        role="AI_Engineer",
        status="active",
        contact_number=None,
        assigned_site_ids=[],
        is_global_admin=False,
    )


@pytest.fixture()
def _mock_db() -> MagicMock:
    db = MagicMock()
    # Make filter/order_by/first chain return None so _fetch_evaluation_metrics → {}
    chainable = MagicMock()
    chainable.filter.return_value = chainable
    chainable.order_by.return_value = chainable
    chainable.first.return_value = None
    # _fetch_training_data_stats calls .one_or_none() → row with row_count=0
    empty_stats = MagicMock()
    empty_stats.row_count = 0
    chainable.one_or_none.return_value = empty_stats
    db.query.return_value = chainable
    return db


@pytest.fixture()
def _mock_mlflow_client() -> MagicMock:
    client = MagicMock()

    mv = MagicMock()
    mv.run_id = "run-test-001"
    mv.current_stage = "Production"
    client.get_model_version.return_value = mv

    run = MagicMock()
    run.data.params = {"n_estimators": "100", "max_depth": "5"}
    run.data.metrics = {"train_mae": 1.5, "val_mae": 2.0}
    run.data.tags = {"algorithm": "XGBoost", "model_task": "forecasting"}
    run.info.run_id = "run-test-001"
    run.info.start_time = 1700000000000
    run.info.end_time = 1700003600000
    run.info.status = "FINISHED"
    client.get_run.return_value = run

    return client


@pytest.fixture()
def api_client(_mock_db, _mock_user, _mock_mlflow_client):
    app.dependency_overrides[get_db] = lambda: (yield _mock_db)
    app.dependency_overrides[get_current_ai_engineer_or_admin] = lambda: _mock_user

    with patch("mlflow.tracking.MlflowClient", return_value=_mock_mlflow_client):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


class TestCompareExperimentsEndpoint:
    _URL = "/api/v1/models/dmp_model/experiments/compare"

    def test_returns_200_for_two_valid_versions(self, api_client):
        response = api_client.get(f"{self._URL}?versions=1,2")
        assert response.status_code == 200

    def test_response_body_includes_model_name(self, api_client):
        data = api_client.get(f"{self._URL}?versions=1,2").json()
        assert data["model_name"] == "dmp_model"

    def test_response_versions_list_has_one_entry_per_requested_version(self, api_client):
        data = api_client.get(f"{self._URL}?versions=1,2").json()
        assert len(data["versions"]) == 2

    def test_version_detail_includes_hyperparameters_from_mlflow(self, api_client):
        data = api_client.get(f"{self._URL}?versions=1,2").json()
        assert "n_estimators" in data["versions"][0]["hyperparameters"]

    def test_common_hyperparameters_lists_keys_shared_across_all_versions(self, api_client):
        data = api_client.get(f"{self._URL}?versions=1,2").json()
        # Both versions share identical mock data → all param keys should be common
        assert "n_estimators" in data["common_hyperparameters"]

    def test_comparison_period_boundaries_are_present_in_response(self, api_client):
        data = api_client.get(f"{self._URL}?versions=1,2").json()
        assert "comparison_period_start" in data
        assert "comparison_period_end" in data

    def test_returns_400_for_fewer_than_two_versions(self, api_client):
        assert api_client.get(f"{self._URL}?versions=1").status_code == 400

    def test_returns_400_for_eleven_versions(self, api_client):
        versions = ",".join(str(i) for i in range(1, 12))
        assert api_client.get(f"{self._URL}?versions={versions}").status_code == 400

    def test_explicit_period_params_are_forwarded_to_response(self, api_client):
        data = api_client.get(
            f"{self._URL}?versions=1,2"
            "&period_start=2025-01-01T00:00:00Z"
            "&period_end=2026-01-01T00:00:00Z"
        ).json()
        assert "2025" in data["comparison_period_start"]
        assert "2026" in data["comparison_period_end"]

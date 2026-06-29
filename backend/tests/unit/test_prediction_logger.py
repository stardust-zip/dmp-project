"""Unit tests for PredictionLogger.

Covers:
  - log_prediction: tz-naïve guard, field mapping, DB lifecycle (add/commit/refresh)
  - log_batch:      empty-list short-circuit, actuals pre-fill, error computation,
                    single-commit guarantee
  - fill_actuals:   empty-dict short-circuit, timestamp normalisation (tz-naïve logs),
                    non-matching timestamps, correct updated count
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, call

import pytest

from src.ml.monitoring.prediction_logger import PredictionLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _naive(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour)


def _base_kwargs(**overrides) -> dict:
    """Minimal valid keyword-argument set for log_prediction."""
    return {
        "timestamp": _utc(2026, 6, 1, 8),
        "building_id": "BuildingA",
        "metric_type_id": "electricity",
        "predicted_value": 100.0,
        "mlflow_run_id": "run-001",
        "model_name": "dmp_model",
        "model_version": "1",
        "model_task": "forecasting",
        **overrides,
    }


def _base_batch_entry(**overrides) -> dict:
    """Minimal valid dict for log_batch entries."""
    return {
        "timestamp": _utc(2026, 6, 1, 8),
        "building_id": "BuildingA",
        "metric_type_id": "electricity",
        "predicted_value": 100.0,
        "mlflow_run_id": "run-001",
        "model_name": "dmp_model",
        "model_version": "1",
        "model_task": "forecasting",
        **overrides,
    }


# ---------------------------------------------------------------------------
# log_prediction
# ---------------------------------------------------------------------------


class TestLogPrediction:
    def test_db_lifecycle_is_add_then_commit_then_refresh(self):
        db = MagicMock()
        PredictionLogger().log_prediction(db, **_base_kwargs())
        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()

    def test_tz_naive_timestamp_is_tagged_utc(self):
        """A timestamp without tzinfo must be pinned to UTC before persisting."""
        db = MagicMock()
        PredictionLogger().log_prediction(db, **_base_kwargs(timestamp=_naive(2026, 6, 1, 8)))
        added_log = db.add.call_args[0][0]
        assert added_log.timestamp.tzinfo is not None
        assert added_log.timestamp.utcoffset().seconds == 0

    def test_tz_aware_timestamp_is_preserved_unchanged(self):
        db = MagicMock()
        aware_ts = _utc(2026, 6, 1, 12)
        PredictionLogger().log_prediction(db, **_base_kwargs(timestamp=aware_ts))
        added_log = db.add.call_args[0][0]
        assert added_log.timestamp == aware_ts

    def test_core_fields_are_mapped_to_the_orm_object(self):
        db = MagicMock()
        PredictionLogger().log_prediction(
            db,
            **_base_kwargs(
                building_id="B-99",
                metric_type_id="water",
                predicted_value=42.5,
                model_name="water_model",
                model_version="3",
                model_task="anomaly_detection",
            ),
        )
        log = db.add.call_args[0][0]
        assert log.building_id == "B-99"
        assert log.metric_type_id == "water"
        assert log.predicted_value == 42.5
        assert log.model_name == "water_model"
        assert log.model_version == "3"
        assert log.model_task == "anomaly_detection"

    def test_optional_feature_and_context_dicts_are_forwarded(self):
        db = MagicMock()
        features = {"sqm": 500.0, "hour": 8}
        context = {"site_id": "SiteX"}
        PredictionLogger().log_prediction(
            db, **_base_kwargs(feature_values=features, prediction_context=context)
        )
        log = db.add.call_args[0][0]
        assert log.feature_values == features
        assert log.prediction_context == context


# ---------------------------------------------------------------------------
# log_batch
# ---------------------------------------------------------------------------


class TestLogBatch:
    def test_empty_list_returns_empty_without_touching_db(self):
        db = MagicMock()
        result = PredictionLogger().log_batch(db, [])
        assert result == []
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_all_entries_are_added_to_db(self):
        db = MagicMock()
        entries = [_base_batch_entry(timestamp=_utc(2026, 6, 1, h)) for h in range(3)]
        PredictionLogger().log_batch(db, entries)
        assert db.add.call_count == 3

    def test_single_commit_covers_entire_batch(self):
        """Only one commit should be issued regardless of batch size."""
        db = MagicMock()
        entries = [_base_batch_entry() for _ in range(5)]
        PredictionLogger().log_batch(db, entries)
        db.commit.assert_called_once()

    def test_refresh_is_called_for_every_log(self):
        db = MagicMock()
        entries = [_base_batch_entry(), _base_batch_entry()]
        PredictionLogger().log_batch(db, entries)
        assert db.refresh.call_count == 2

    def test_entry_without_actual_value_leaves_error_as_none(self):
        db = MagicMock()
        PredictionLogger().log_batch(db, [_base_batch_entry()])
        log = db.add.call_args[0][0]
        assert log.actual_value is None
        assert log.error is None

    def test_entry_with_actual_value_populates_actual_and_error(self):
        db = MagicMock()
        PredictionLogger().log_batch(
            db,
            [_base_batch_entry(predicted_value=100.0, actual_value=110.0, error=10.0)],
        )
        log = db.add.call_args[0][0]
        assert log.actual_value == 110.0

    def test_returns_list_of_created_log_objects(self):
        db = MagicMock()
        entries = [_base_batch_entry(), _base_batch_entry()]
        result = PredictionLogger().log_batch(db, entries)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# fill_actuals
# ---------------------------------------------------------------------------


class TestFillActuals:
    def test_empty_actuals_dict_returns_zero_without_querying_db(self):
        db = MagicMock()
        count = PredictionLogger().fill_actuals(db, "BuildingA", "electricity", {})
        assert count == 0
        db.query.assert_not_called()

    def test_matching_log_is_updated_with_actual_and_error(self):
        db = MagicMock()
        ts = _utc(2026, 6, 1, 8)

        log = MagicMock()
        log.timestamp = ts
        log.predicted_value = 100.0
        db.query.return_value.filter.return_value.all.return_value = [log]

        count = PredictionLogger().fill_actuals(db, "BuildingA", "electricity", {ts: 110.0})

        assert count == 1
        assert log.actual_value == 110.0
        assert log.error == pytest.approx(10.0)
        db.commit.assert_called_once()

    def test_tz_naive_log_timestamp_is_normalised_to_utc_key(self):
        """Logs stored without tzinfo must be treated as UTC when matching actuals."""
        db = MagicMock()
        ts_utc = _utc(2026, 6, 1, 8)

        log = MagicMock()
        log.timestamp = _naive(2026, 6, 1, 8)  # no tzinfo, as stored by some DB drivers
        log.predicted_value = 50.0
        db.query.return_value.filter.return_value.all.return_value = [log]

        count = PredictionLogger().fill_actuals(db, "BuildingA", "electricity", {ts_utc: 60.0})

        assert count == 1
        assert log.actual_value == 60.0

    def test_log_at_different_hour_is_not_matched(self):
        db = MagicMock()
        ts_actual = _utc(2026, 6, 1, 8)
        ts_log = _utc(2026, 6, 1, 9)  # one hour later → no match

        log = MagicMock()
        log.timestamp = ts_log
        log.predicted_value = 100.0
        db.query.return_value.filter.return_value.all.return_value = [log]

        count = PredictionLogger().fill_actuals(db, "BuildingA", "electricity", {ts_actual: 110.0})

        assert count == 0
        db.commit.assert_not_called()

    def test_only_matched_logs_are_counted(self):
        """fill_actuals must return count of updated logs, not total logs checked."""
        db = MagicMock()
        ts1 = _utc(2026, 6, 1, 8)
        ts2 = _utc(2026, 6, 1, 9)
        ts3 = _utc(2026, 6, 1, 10)

        logs = []
        for ts, pred in [(ts1, 10.0), (ts2, 20.0), (ts3, 30.0)]:
            entry = MagicMock()
            entry.timestamp = ts
            entry.predicted_value = pred
            logs.append(entry)

        db.query.return_value.filter.return_value.all.return_value = logs

        # Only two of three timestamps have actuals
        count = PredictionLogger().fill_actuals(
            db, "BuildingA", "electricity", {ts1: 11.0, ts2: 22.0}
        )

        assert count == 2

    def test_commit_is_skipped_when_no_logs_were_updated(self):
        db = MagicMock()
        ts_actual = _utc(2026, 6, 1, 8)
        ts_log = _utc(2026, 6, 1, 9)

        log = MagicMock()
        log.timestamp = ts_log
        log.predicted_value = 100.0
        db.query.return_value.filter.return_value.all.return_value = [log]

        PredictionLogger().fill_actuals(db, "BuildingA", "electricity", {ts_actual: 110.0})

        db.commit.assert_not_called()

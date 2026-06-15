from src.ml.anomaly_events import (
    event_records,
    filter_events,
    filter_series,
    load_anomaly_events,
    load_anomaly_series,
    sort_events,
)
from src.ml.anomaly_detection import _anomaly_event_insert_records
from src.ml.anomaly_detection import _filter_events_with_existing_locations
from src.models import AnomalyDetectedEvent


class _FakeQuery:
    """Minimal stand-in for a SQLAlchemy query that ignores filters and returns rows."""

    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *args, **kwargs):
        return _FakeQuery(self._rows)


class _FakeLocationSession:
    def __init__(self, location_ids):
        self._location_ids = location_ids

    def query(self, *args, **kwargs):
        return _FakeQuery([(location_id,) for location_id in self._location_ids])


def _sample_rows():
    import datetime as dt

    return [
        AnomalyDetectedEvent(
            building_id="B1",
            site_id="S1",
            timestamp=dt.datetime(2017, 1, 1, 3, 0, 0),
            metric_type_id="electricity",
            primary_space_usage="Office",
            actual_value=None,
            predicted_value=None,
            residual=None,
            residual_z=None,
            anomaly_score=None,
            is_anomaly=True,
            direction=None,
            severity="Medium",
            source="rule_based",
            anomaly_type="long_missing_run",
            reason="Missing for 3h",
            mlflow_run_id="run-1",
        ),
        AnomalyDetectedEvent(
            building_id="B2",
            site_id="S2",
            timestamp=dt.datetime(2017, 1, 2, 4, 0, 0),
            metric_type_id="electricity",
            primary_space_usage="Education",
            actual_value=200.0,
            predicted_value=100.0,
            residual=100.0,
            residual_z=5.0,
            anomaly_score=5.0,
            is_anomaly=True,
            direction="over",
            severity="Critical",
            source="lgbm",
            anomaly_type=None,
            reason=None,
            mlflow_run_id="run-2",
        ),
    ]


def _series_rows():
    import datetime as dt

    return [
        AnomalyDetectedEvent(
            building_id="B2",
            site_id="S2",
            timestamp=dt.datetime(2017, 1, 2, 4, 0, 0),
            metric_type_id="electricity",
            primary_space_usage="Education",
            actual_value=200.0,
            predicted_value=100.0,
            anomaly_score=5.0,
            is_anomaly=True,
            direction="over",
            severity="Critical",
            source="lgbm",
        ),
        AnomalyDetectedEvent(
            building_id="B2",
            site_id="S2",
            timestamp=dt.datetime(2017, 1, 2, 5, 0, 0),
            metric_type_id="electricity",
            primary_space_usage="Education",
            actual_value=99.0,
            predicted_value=100.0,
            anomaly_score=0.2,
            is_anomaly=False,
            direction="normal",
            severity="normal",
            source="lgbm",
        ),
    ]


def test_load_anomaly_events_normalizes_user_facing_types():
    db = _FakeSession(_sample_rows())

    events = load_anomaly_events(db)

    assert len(events) == 2
    assert set(events["type"]) == {"Missing meter data", "Unusual high consumption"}
    assert "residual_z" not in events.columns
    assert "anomaly_score" not in events.columns


def test_filter_sort_and_serialize_anomaly_events():
    # The fake ignores filters, so pre-select only the rows that would match.
    db = _FakeSession([_sample_rows()[1]])

    events = filter_events(db, site_id="S2", severity="Critical")
    records = event_records(sort_events(events, "severity"))

    assert len(records) == 1
    assert records[0]["site_id"] == "S2"
    assert records[0]["type"] == "Unusual high consumption"
    assert records[0]["actual_value"] == 200.0
    assert records[0]["expected_value"] == 100.0
    assert records[0]["deviation_percent"] == 100.0


def test_filter_series_keeps_non_anomaly_points():
    db = _FakeSession(_series_rows())

    series = filter_series(db, site_id="S2", building_id="B2")

    assert len(series) == 2
    assert series["is_anomaly"].tolist() == [True, False]
    assert series["actual_value"].tolist() == [200.0, 99.0]
    assert series["expected_value"].tolist() == [100.0, 100.0]


def test_load_anomaly_series_filters_to_lgbm_source():
    db = _FakeSession(_series_rows())

    series = load_anomaly_series(db)

    assert len(series) == 2
    assert set(series["building_id"]) == {"B2"}


def test_anomaly_event_insert_records_omits_default_managed_columns():
    event = _sample_rows()[0]

    records = _anomaly_event_insert_records([event])

    assert len(records) == 1
    assert "id" not in records[0]
    assert "created_at" not in records[0]
    assert records[0]["building_id"] == "B1"
    assert records[0]["source"] == "rule_based"


def test_filter_events_with_existing_locations_skips_orphan_events():
    events = _sample_rows()
    logs = []

    filtered = _filter_events_with_existing_locations(
        events,
        _FakeLocationSession({"B1"}),
        logs.append,
    )

    assert len(filtered) == 1
    assert filtered[0].building_id == "B1"
    assert logs == [
        "Skipped 1 rule-based events for 1 buildings missing from location metadata."
    ]

import pandas as pd

from src.core.config import settings
from src.ml.anomaly_events import (
    event_records,
    filter_events,
    load_anomaly_events,
    sort_events,
)


def _write_fixture_exports(path):
    stage1 = pd.DataFrame(
        [
            {
                "anomaly_id": "A1",
                "building_id": "B1",
                "site_id": "S1",
                "primaryspaceusage": "Office",
                "timestamp": pd.Timestamp("2017-01-01 03:00:00"),
                "start_time": pd.Timestamp("2017-01-01 03:00:00"),
                "end_time": pd.Timestamp("2017-01-01 08:00:00"),
                "duration_hours": 6.0,
                "anomaly_type": "long_missing_run",
                "actual_value": None,
                "repeated_value": None,
                "threshold_value": None,
                "missing_rate": None,
                "exclude_downstream": False,
                "severity": "Medium",
                "reason": "Missing for 6h",
            }
        ]
    )
    stage3 = pd.DataFrame(
        [
            {
                "building_id": "B2",
                "timestamp": pd.Timestamp("2017-01-02 04:00:00"),
                "consumption": 200.0,
                "predicted": 100.0,
                "pred_lgbm": 100.0,
                "residual": 100.0,
                "residual_z": 5.0,
                "anomaly_score": 5.0,
                "severity": "Critical",
                "direction": "over",
                "is_anomaly": True,
                "site_id": "S2",
                "primaryspaceusage": "Education",
                "sqm": 1000.0,
            },
            {
                "building_id": "B2",
                "timestamp": pd.Timestamp("2017-01-02 05:00:00"),
                "consumption": 99.0,
                "predicted": 100.0,
                "pred_lgbm": 100.0,
                "residual": -1.0,
                "residual_z": 0.2,
                "anomaly_score": 0.2,
                "severity": "normal",
                "direction": "normal",
                "is_anomaly": False,
                "site_id": "S2",
                "primaryspaceusage": "Education",
                "sqm": 1000.0,
            },
        ]
    )
    stage1.to_parquet(path / "stage1_anomalies.parquet", index=False)
    stage3.to_parquet(path / "stage3_residual_anomalies.parquet", index=False)


def test_load_anomaly_events_normalizes_user_facing_types(tmp_path, monkeypatch):
    _write_fixture_exports(tmp_path)
    monkeypatch.setattr(settings, "ANOMALY_DATA_DIR", str(tmp_path))
    load_anomaly_events.cache_clear()

    events = load_anomaly_events()

    assert len(events) == 2
    assert set(events["type"]) == {"Missing meter data", "Unusual high consumption"}
    assert "residual_z" not in events.columns
    assert "anomaly_score" not in events.columns

    load_anomaly_events.cache_clear()


def test_filter_sort_and_serialize_anomaly_events(tmp_path, monkeypatch):
    _write_fixture_exports(tmp_path)
    monkeypatch.setattr(settings, "ANOMALY_DATA_DIR", str(tmp_path))
    load_anomaly_events.cache_clear()

    events = filter_events(site_id="S2", severity="Critical")
    records = event_records(sort_events(events, "severity"))

    assert len(records) == 1
    assert records[0]["site_id"] == "S2"
    assert records[0]["type"] == "Unusual high consumption"
    assert records[0]["actual_value"] == 200.0
    assert records[0]["expected_value"] == 100.0
    assert records[0]["deviation_percent"] == 100.0

    load_anomaly_events.cache_clear()

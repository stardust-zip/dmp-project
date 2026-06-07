import os
import tempfile

import pandas as pd
import pytest
from src.ml.data import DataLoader


@pytest.fixture
def mock_csv_file():
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                start="2026-06-01", periods=5, freq="h", tz="UTC"
            ),
            "Panther_parking_Lorriane": [
                10.5,
                12.0,
                11.1,
                None,
                15.0,
            ],
        }
    )

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    df.to_csv(temp_file.name, index=False)
    yield temp_file.name

    os.remove(temp_file.name)


def test_data_loader_extracts_features_and_interpolates_missing_values(mock_csv_file):
    loader = DataLoader(mock_csv_file)

    X, y = loader.load_timeseries_target("Panther_parking_Lorriane")

    assert len(X) == 5
    assert len(y) == 5
    assert y.isna().sum() == 0
    assert y.iloc[3] == pytest.approx(13.05)
    assert "hour" in X.columns
    assert "dayofweek" in X.columns


def test_data_loader_removes_duplicate_rows_and_collapses_duplicate_timestamps():
    df = pd.DataFrame(
        {
            "timestamp": [
                "2026-06-01T00:00:00Z",
                "2026-06-01T00:00:00Z",
                "2026-06-01T01:00:00Z",
                "2026-06-01T01:00:00Z",
                "2026-06-01T02:00:00Z",
            ],
            "Panther_parking_Lorriane": [10.0, 10.0, 20.0, 40.0, 50.0],
        }
    )

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    df.to_csv(temp_file.name, index=False)

    try:
        loader = DataLoader(temp_file.name)
        X, y = loader.load_timeseries_target("Panther_parking_Lorriane")
    finally:
        os.remove(temp_file.name)

    assert len(X) == 3
    assert y.tolist() == [10.0, 30.0, 50.0]


def test_data_loader_filters_outliers_with_iqr_bounds():
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                start="2026-06-01", periods=6, freq="h", tz="UTC"
            ),
            "Panther_parking_Lorriane": [10.0, 11.0, 12.0, 13.0, 14.0, 1000.0],
        }
    )

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    df.to_csv(temp_file.name, index=False)

    try:
        loader = DataLoader(temp_file.name)
        X, y = loader.load_timeseries_target("Panther_parking_Lorriane")
    finally:
        os.remove(temp_file.name)

    assert len(X) == 5
    assert 1000.0 not in y.tolist()


def test_data_loader_normalizes_naive_timestamps_to_timezone_aware_utc():
    df = pd.DataFrame(
        {
            "timestamp": ["2026-06-01 00:00:00", "2026-06-01 01:00:00"],
            "Panther_parking_Lorriane": [10.0, 11.0],
        }
    )

    normalized_df = DataLoader("unused")._validate_and_normalize_timestamps(df)

    assert str(normalized_df["timestamp"].dt.tz) == "UTC"


def test_data_loader_rejects_invalid_timestamps():
    df = pd.DataFrame(
        {
            "timestamp": ["2026-06-01T00:00:00Z", "not-a-timestamp"],
            "Panther_parking_Lorriane": [10.0, 11.0],
        }
    )

    with pytest.raises(ValueError, match="invalid or missing timestamp"):
        DataLoader("unused")._validate_and_normalize_timestamps(df)

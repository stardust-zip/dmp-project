import pandas as pd

from src.ml.anomaly_pipeline import build_feature_matrix


def test_build_feature_matrix_normalizes_weather_timestamp_timezone_before_merge():
    telemetry = pd.DataFrame(
        {
            "timestamp": pd.date_range("2016-01-01T00:00:00Z", periods=3, freq="h"),
            "building_id": ["B1", "B1", "B1"],
            "site_id": ["S1", "S1", "S1"],
            "primaryspaceusage": ["Office", "Office", "Office"],
            "sqm": [100.0, 100.0, 100.0],
            "timezone": ["UTC", "UTC", "UTC"],
            "consumption": [10.0, 11.0, 12.0],
        }
    )
    weather = pd.DataFrame(
        {
            "timestamp": pd.date_range("2016-01-01 00:00:00", periods=3, freq="h"),
            "site_id": ["S1", "S1", "S1"],
            "airTemperature": [20.0, 21.0, 22.0],
        }
    )

    feature_df, feature_cols, _ = build_feature_matrix(
        telemetry,
        use_weather=True,
        weather_df=weather,
        weather_feature_cols=["airTemperature"],
    )

    assert str(feature_df["timestamp"].dt.tz) == "UTC"
    assert "airTemperature" in feature_cols
    assert feature_df["airTemperature"].tolist() == [20.0, 21.0, 22.0]

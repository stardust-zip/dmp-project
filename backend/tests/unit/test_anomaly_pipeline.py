import lightgbm as lgb
import pandas as pd
import pytest

from src.ml.anomaly_pipeline import build_feature_matrix, score_anomalies


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


def test_score_anomalies_restores_missing_categorical_feature_dtype():
    feature_cols = ["hour", "building_id", "site_id", "primaryspaceusage"]
    train_df = pd.DataFrame(
        {
            "hour": [0, 1, 2, 3, 4, 5],
            "building_id": pd.Categorical(["B1", "B1", "B2", "B2", "B3", "B3"]),
            "site_id": pd.Categorical(["S1", "S1", "S1", "S1", "S2", "S2"]),
            "primaryspaceusage": pd.Categorical(
                ["Office", "Office", "Lab", "Lab", "Office", "Office"]
            ),
            "consumption": [10.0, 11.0, 20.0, 21.0, 30.0, 31.0],
        }
    )
    model = lgb.LGBMRegressor(
        n_estimators=2,
        min_data_in_leaf=1,
        min_data_in_bin=1,
        verbose=-1,
        random_state=42,
    )
    model.fit(
        train_df[feature_cols],
        train_df["consumption"],
        categorical_feature=["building_id", "site_id", "primaryspaceusage"],
    )

    inference_df = pd.DataFrame(
        {
            "hour": [6],
            "building_id": pd.Categorical(["B1"]),
            "site_id": pd.Categorical(["S1"]),
            "consumption": [12.0],
        }
    )
    resid_stats = pd.DataFrame(
        {
            "building_id": ["B1"],
            "resid_median": [0.0],
            "resid_mad": [1.0],
        }
    )
    raw_lgbm_input = inference_df.copy()
    raw_lgbm_input["primaryspaceusage"] = pd.NA

    with pytest.raises(ValueError, match="categorical_feature do not match"):
        model.predict(raw_lgbm_input[feature_cols])

    scored = score_anomalies(model, resid_stats, inference_df, feature_cols)

    assert len(scored) == 1
    assert pd.notna(scored.loc[0, "predicted_value"])

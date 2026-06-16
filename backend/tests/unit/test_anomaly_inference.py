import tempfile
from types import SimpleNamespace

import pandas as pd

from src.ml.anomaly import inference as anomaly_inference
from src.ml.anomaly import model_registry


class _Client:
    def __init__(self, version_tags: dict[str, str], run_tags: dict[str, str]):
        self._version = SimpleNamespace(
            run_id="run-1",
            version="7",
            tags=version_tags,
        )
        self._run = SimpleNamespace(data=SimpleNamespace(tags=run_tags))

    def get_model_version_by_alias(self, model_name: str, alias: str):
        return self._version

    def download_artifacts(self, run_id: str, artifact_path: str, dst_path: str):
        return "resid_stats.parquet"

    def get_run(self, run_id: str):
        return self._run


class _Model:
    def __init__(self, feature_names: list[str] | None = None):
        self.feature_name_ = feature_names or []


class _TempDir:
    def __enter__(self):
        return "."

    def __exit__(self, exc_type, exc, tb):
        return False


def test_load_production_anomaly_model_reads_model_version_feature_tags(monkeypatch):
    model = _Model()
    monkeypatch.setattr(model_registry.mlflow.lightgbm, "load_model", lambda uri: model)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", lambda: _TempDir())
    monkeypatch.setattr(
        anomaly_inference.pd,
        "read_parquet",
        lambda path: pd.DataFrame({"building_id": ["B1"]}),
    )
    client = _Client(
        version_tags={
            "feature_set": "hour,building_id,site_id,primaryspaceusage",
            "metrics": "electricity",
            "weather_features": "true",
        },
        run_tags={},
    )

    _, _, feature_cols, cat_features, use_weather, metrics = (
        anomaly_inference.load_production_anomaly_model(client)
    )

    assert feature_cols == ["hour", "building_id", "site_id", "primaryspaceusage"]
    assert cat_features == ["building_id", "site_id", "primaryspaceusage"]
    assert use_weather is True
    assert metrics == ["electricity"]


def test_load_production_anomaly_model_falls_back_to_model_feature_names(monkeypatch):
    model = _Model(["hour", "building_id", "airTemperature"])
    monkeypatch.setattr(model_registry.mlflow.lightgbm, "load_model", lambda uri: model)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", lambda: _TempDir())
    monkeypatch.setattr(
        anomaly_inference.pd,
        "read_parquet",
        lambda path: pd.DataFrame({"building_id": ["B1"]}),
    )
    client = _Client(version_tags={}, run_tags={})

    _, _, feature_cols, cat_features, use_weather, metrics = (
        anomaly_inference.load_production_anomaly_model(client)
    )

    assert feature_cols == ["hour", "building_id", "airTemperature"]
    assert cat_features == ["building_id"]
    assert use_weather is True
    assert metrics == ["electricity"]

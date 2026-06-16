from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Protocol

import mlflow
import mlflow.lightgbm
import pandas as pd
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from src.ml.anomaly.feature_engineering import CAT_FEATURES
from src.ml.anomaly.types import DEFAULT_METRIC_TYPE

MODEL_NAME = "dmp_energy_anomaly_detection"
WEATHER_FEATURE_NAMES = {
    "airTemperature",
    "windSpeed",
    "temp_dew_spread",
    "airTemperature_roll24h",
    "airTemperature_roll168h",
}


class ModelRegistry(Protocol):
    def log_model(
        self,
        model,
        feature_cols: list[str],
        metrics: dict,
        request,
        *,
        use_weather: bool,
    ) -> str | None: ...

    def tag_version(self, version_id: str, tags: dict[str, str]) -> None: ...
    def log_artifact(self, name: str, df: pd.DataFrame) -> None: ...
    def find_production_version(self, model_name: str): ...
    def load_production_model(self, model_name: str = MODEL_NAME): ...


def _model_feature_names(model) -> list[str]:
    feature_names = getattr(model, "feature_name_", None)
    if feature_names:
        return [str(feature) for feature in feature_names]

    booster = getattr(model, "booster_", None) or getattr(model, "_Booster", None)
    if booster is None:
        return []

    try:
        return [str(feature) for feature in booster.feature_name()]
    except Exception:
        return []


class MlflowModelRegistry:
    def __init__(self, client=None) -> None:
        self._client = client or MlflowClient()

    def log_model(
        self,
        model,
        feature_cols: list[str],
        metrics: dict,
        request,
        *,
        use_weather: bool,
    ) -> str | None:
        mlflow.log_params({
            "use_weather": use_weather,
            "n_features": len(feature_cols),
            "best_iteration": metrics["best_iteration"],
        })
        mlflow.log_metrics({
            "test_rmse": metrics["test_rmse"],
            "test_mae": metrics["test_mae"],
        })
        mlflow.lightgbm.log_model(
            model,
            artifact_path="model",
            registered_model_name=MODEL_NAME,
        )

        versions = self._client.get_latest_versions(MODEL_NAME, stages=["None"])
        if not versions:
            return None
        version = versions[-1]
        tags = {
            "model_task": "anomaly_detection",
            "weather_features": str(use_weather).lower(),
            "feature_set": ",".join(feature_cols),
            "metrics": ",".join(request.metrics),
        }
        self.tag_version(str(version.version), tags)
        return str(version.version)

    def tag_version(self, version_id: str, tags: dict[str, str]) -> None:
        for key, value in tags.items():
            self._client.set_model_version_tag(MODEL_NAME, version_id, key, value)

    def log_artifact(self, name: str, df: pd.DataFrame) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            df.to_parquet(path, index=False)
            mlflow.log_artifact(str(path))

    def find_production_version(self, model_name: str = MODEL_NAME):
        try:
            return self._client.get_model_version_by_alias(model_name, "production")
        except (AttributeError, MlflowException):
            pass

        try:
            all_versions = self._client.search_model_versions(f"name = '{model_name}'")
        except Exception:
            return None

        production = [
            v for v in all_versions
            if (getattr(v, "tags", {}) or {}).get("active") == "true"
            or (getattr(v, "tags", {}) or {}).get("stage") == "production"
            or getattr(v, "current_stage", None) == "Production"
        ]
        if not production:
            return None
        return max(production, key=lambda v: getattr(v, "last_updated_timestamp", 0) or 0)

    def load_production_model(self, model_name: str = MODEL_NAME):
        version = self.find_production_version(model_name)
        if version is None:
            return None

        run_id = version.run_id
        version_number = str(version.version)
        model = mlflow.lightgbm.load_model(f"models:/{model_name}/{version_number}")

        with tempfile.TemporaryDirectory() as tmp:
            local_path = self._client.download_artifacts(run_id, "resid_stats.parquet", tmp)
            resid_stats = pd.read_parquet(local_path)

        run = self._client.get_run(run_id)
        run_tags = getattr(run.data, "tags", {}) or {}
        version_tags = getattr(version, "tags", {}) or {}
        tags = {**run_tags, **version_tags}
        feature_set = tags.get("feature_set", "")
        feature_cols = [f.strip() for f in feature_set.split(",") if f.strip()]
        if not feature_cols:
            feature_cols = _model_feature_names(model)
        if not feature_cols:
            raise ValueError(
                "Production anomaly model is missing feature metadata. "
                "Expected the model version tag 'feature_set' or LightGBM feature names."
            )

        weather_tag = tags.get("weather_features")
        use_weather = (
            str(weather_tag).lower() == "true"
            if weather_tag is not None
            else any(feature in WEATHER_FEATURE_NAMES for feature in feature_cols)
        )
        metrics = [
            metric.strip().lower()
            for metric in str(tags.get("metrics", "")).split(",")
            if metric.strip()
        ]
        if not metrics:
            metrics = [DEFAULT_METRIC_TYPE]

        cat_features = [c for c in CAT_FEATURES if c in feature_cols]
        return model, resid_stats, feature_cols, cat_features, use_weather, metrics

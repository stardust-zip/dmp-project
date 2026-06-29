"""MLflow model registry for forecasting.

Mirrors :class:`src.ml.anomaly.model_registry.MlflowModelRegistry` but uses the
**sklearn** flavor (the model is a scikit-learn :class:`~sklearn.pipeline.Pipeline`)
and tags forecasting-specific metadata (feature set, forecast horizon, algorithm).
"""

from __future__ import annotations

from typing import Protocol

import mlflow.sklearn
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from src.ml.forecasting.types import (
    CAT_FEATURES,
    DEFAULT_METRIC_TYPE,
    DEFAULT_WEATHER_MODE,
    MODEL_NAME,
)

import mlflow


class ForecastingModelRegistry(Protocol):
    def log_model(
        self,
        pipeline,
        feature_cols: list[str],
        metrics: dict,
        request,
        *,
        horizon: int,
        algorithm: str,
        weather_mode: str,
        model_name: str = MODEL_NAME,
    ) -> str | None: ...

    def find_production_version(self, model_name: str = MODEL_NAME): ...
    def promote_version(
        self, version: str, model_name: str = MODEL_NAME, alias: str = "production"
    ) -> None: ...
    def log_coverage_artifact(
        self,
        *,
        trained_building_ids: list[str],
        dropped_building_ids: list[str],
    ) -> None: ...
    def load_production_forecast_model(self, model_name: str = MODEL_NAME): ...
    def load_production_coverage(self, model_name: str = MODEL_NAME) -> dict | None: ...


class ForecastingMlflowRegistry:
    """Logs/loads the forecasting pipeline to/from the MLflow model registry."""

    def __init__(self, client=None) -> None:
        self._client = client or MlflowClient()

    def log_model(
        self,
        pipeline,
        feature_cols: list[str],
        metrics: dict,
        request,
        *,
        horizon: int,
        algorithm: str,
        weather_mode: str,
        model_name: str = MODEL_NAME,
    ) -> str | None:
        mlflow.log_params(
            {
                "forecast_horizon": horizon,
                "algorithm": algorithm,
                "weather_mode": weather_mode,
                "n_features": len(feature_cols),
            }
        )
        mlflow.log_metrics(
            {
                "test_mae": metrics["test_mae"],
                "test_rmse": metrics["test_rmse"],
                "test_mape": metrics["test_mape"],
            }
        )
        mlflow.sklearn.log_model(
            pipeline,
            artifact_path="model",
            registered_model_name=model_name,
            # MLflow 3.x defaults to the `skops` flavor, which refuses to
            # serialize sklearn pipelines referencing `numpy.dtype` (an
            # "untrusted type"). Use cloudpickle (the historical default) so
            # logging + loading both succeed. Inference loads via the same flavor.
            serialization_format=mlflow.sklearn.SERIALIZATION_FORMAT_CLOUDPICKLE,
        )

        versions = self._client.get_latest_versions(model_name, stages=["None"])
        if not versions:
            return None
        version = versions[-1]
        metric_tag = (
            ",".join(request.metrics)
            if getattr(request, "metrics", None)
            else DEFAULT_METRIC_TYPE
        )
        tags = {
            "model_task": "forecasting",
            "feature_set": ",".join(feature_cols),
            "forecast_horizon": str(horizon),
            "algorithm": algorithm,
            "metric": metric_tag,
            "weather_mode": weather_mode,
        }
        building_id = getattr(request, "building_id", None)
        if building_id:
            tags["building_id"] = building_id
        self._tag_version(str(version.version), tags, model_name=model_name)
        return str(version.version)

    def _tag_version(
        self, version_id: str, tags: dict[str, str], *, model_name: str = MODEL_NAME
    ) -> None:
        for key, value in tags.items():
            self._client.set_model_version_tag(model_name, version_id, key, value)

    def promote_version(
        self, version: str, model_name: str = MODEL_NAME, alias: str = "production"
    ) -> None:
        """Point the production alias at ``version`` so inference can load it.

        A freshly trained forecasting model becomes the production model
        immediately (no manual MLflow UI step), which :meth:`find_production_version`
        resolves via the alias.
        """
        self._client.set_registered_model_alias(model_name, alias, version)

    def log_coverage_artifact(
        self,
        *,
        trained_building_ids: list[str],
        dropped_building_ids: list[str],
    ) -> None:
        """Log the building-coverage of this training run as a JSON artifact.

        Writes ``coverage.json`` to the active MLflow run, recording both the
        buildings the model was trained on and those dropped (>30% missing).
        The forecast UI downloads this via :meth:`load_production_coverage` to
        hide dropped buildings from its dropdown. Count params are logged too so
        the coverage is visible in the MLflow UI without opening the artifact.
        """
        mlflow.log_dict(
            {
                "trained_building_ids": trained_building_ids,
                "dropped_building_ids": dropped_building_ids,
            },
            artifact_file="coverage.json",
        )
        mlflow.log_params(
            {
                "trained_building_count": len(trained_building_ids),
                "dropped_building_count": len(dropped_building_ids),
            }
        )

    def load_production_coverage(self, model_name: str = MODEL_NAME) -> dict | None:
        """Return the building coverage of the production model.

        Returns ``None`` only when there is no production version (so the caller
        can emit a 404). When a production version exists but predates the
        coverage artifact (trained before this feature), the run_id is still
        returned with empty lists — callers treat that as "no exclusions".

        Used by the ``GET /forecast/model-coverage`` endpoint.
        """
        version = self.find_production_version(model_name)
        if version is None:
            return None
        run_id = getattr(version, "run_id", None)
        coverage = {"trained_building_ids": [], "dropped_building_ids": []}
        if run_id:
            try:
                local_path = self._client.download_artifacts(run_id, "coverage.json")
                import json

                with open(local_path, encoding="utf-8") as handle:
                    payload = json.load(handle)
                coverage["trained_building_ids"] = list(
                    payload.get("trained_building_ids", []) or []
                )
                coverage["dropped_building_ids"] = list(
                    payload.get("dropped_building_ids", []) or []
                )
            except Exception:
                # Model predates the coverage artifact -> empty lists (no exclusions).
                pass
        return {"model_run_id": run_id, **coverage}

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
            v
            for v in all_versions
            if (getattr(v, "tags", {}) or {}).get("active") == "true"
            or (getattr(v, "tags", {}) or {}).get("stage") == "production"
            or getattr(v, "current_stage", None) == "Production"
        ]
        if not production:
            return None
        return max(
            production, key=lambda v: getattr(v, "last_updated_timestamp", 0) or 0
        )

    def load_production_forecast_model(self, model_name: str = MODEL_NAME):
        """Load the production forecasting pipeline + metadata.

        Returns ``(pipeline, feature_cols, cat_features, horizon, metric, run_id,
        weather_mode)`` or ``None`` when no production version exists. ``run_id`` is
        the MLflow run that produced the version (used to tag persisted
        ``ForecastResult`` rows). ``weather_mode`` defaults to ``"none"`` for models
        trained before Phase 2 (so old models load unchanged). Used by inference.
        """
        version = self.find_production_version(model_name)
        if version is None:
            return None

        version_number = str(version.version)
        pipeline = mlflow.sklearn.load_model(f"models:/{model_name}/{version_number}")

        run = self._client.get_run(version.run_id)
        run_tags = getattr(run.data, "tags", {}) or {}
        version_tags = getattr(version, "tags", {}) or {}
        tags = {**run_tags, **version_tags}

        feature_set = tags.get("feature_set", "")
        feature_cols = [f.strip() for f in feature_set.split(",") if f.strip()]
        if not feature_cols:
            feature_names = getattr(
                getattr(pipeline, "named_steps", {}).get("model"),
                "feature_names_in_",
                None,
            )
            if feature_names is not None:
                feature_cols = [str(f) for f in feature_names]
        if not feature_cols:
            raise ValueError(
                "Production forecasting model is missing feature metadata "
                "(expected the version tag 'feature_set')."
            )

        try:
            horizon = int(tags.get("forecast_horizon", 24))
        except (TypeError, ValueError):
            horizon = 24

        metric_tag = tags.get("metric", DEFAULT_METRIC_TYPE)
        weather_mode = tags.get("weather_mode", DEFAULT_WEATHER_MODE)
        cat_features = [c for c in CAT_FEATURES if c in feature_cols]
        run_id = getattr(version, "run_id", None)
        return (
            pipeline,
            feature_cols,
            cat_features,
            horizon,
            metric_tag,
            run_id,
            weather_mode,
        )

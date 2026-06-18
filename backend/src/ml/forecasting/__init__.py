"""Forecasting training & inference package (peer of :mod:`src.ml.anomaly`).

Phase 1 (training) is implemented here; inference (ForecastService, operator
forecast-vs-actual endpoint) is Phase 2 and will call
:meth:`ForecastingMlflowRegistry.load_production_forecast_model`.
"""

from src.ml.forecasting.feature_engineering import build_forecast_feature_matrix
from src.ml.forecasting.model_registry import ForecastingMlflowRegistry
from src.ml.forecasting.training import train_forecasting_model
from src.ml.forecasting.types import MODEL_NAME

__all__ = [
    "MODEL_NAME",
    "build_forecast_feature_matrix",
    "ForecastingMlflowRegistry",
    "train_forecasting_model",
]

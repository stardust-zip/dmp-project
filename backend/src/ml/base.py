import time
from abc import ABC, abstractmethod

from sklearn.model_selection import train_test_split

import mlflow


class BaseModelTrainer(ABC):
    def __init__(self, model_name: str, model):
        self.model_name = model_name
        self.model = model

    def train_and_evaluate(self, X, y) -> dict:
        # 1. Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, shuffle=False
        )

        # 2. Train
        start_time = time.time()
        self.model.fit(X_train, y_train)
        execution_time_ms = int((time.time() - start_time) * 1000)

        # 3. Evaluate
        predictions = self.model.predict(X_test)
        metrics = self.evaluate(y_test, predictions)

        # 4. Log to MLflow
        mlflow.sklearn.log_model(
            self.model, artifact_path="model", registered_model_name=self.model_name
        )  # type: ignore
        mlflow.log_metrics(metrics)
        if hasattr(self.model, "n_estimators"):
            mlflow.log_param("n_estimators", self.model.n_estimators)

        return {**metrics, "execution_time_ms": execution_time_ms}

    @abstractmethod
    def evaluate(self, y_test, predictions) -> dict:
        """Return model-specific metrics."""
        pass

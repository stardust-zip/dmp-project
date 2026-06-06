import time
from abc import ABC, abstractmethod

import mlflow.sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.model_selection import train_test_split

import mlflow


class BaseModelTrainer(ABC):
    def __init__(self, model_name: str):
        self.model_name = model_name

    @abstractmethod
    def train_and_evaluate(self, X, y) -> dict:
        """Must return a dictionary of metrics."""
        pass


class RandomForestTrainer(BaseModelTrainer):
    def __init__(self, n_estimators=100):
        super().__init__(model_name="RandomForestBaseline")
        self.model = RandomForestRegressor(n_estimators=n_estimators, random_state=42)

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
        mae = mean_absolute_error(y_test, predictions)
        rmse = root_mean_squared_error(y_test, predictions)

        # 4. Log to MLflow
        mlflow.sklearn.log_model(self.model, artifact_path="model")  # type: ignore
        mlflow.log_metrics({"mae": mae, "rmse": rmse})
        mlflow.log_param("n_estimators", self.model.n_estimators)

        return {"mae": mae, "rmse": rmse, "execution_time_ms": execution_time_ms}

from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score, mean_absolute_error, root_mean_squared_error
from src.ml.base import BaseModelTrainer


class RandomForestTrainer(BaseModelTrainer):
    def __init__(self, model_name, n_estimators=100):
        super().__init__(
            model_name=model_name,
            model=RandomForestRegressor(n_estimators=n_estimators, random_state=42),
        )

    def evaluate(self, y_test, predictions) -> dict:
        mae = mean_absolute_error(y_test, predictions)
        rmse = root_mean_squared_error(y_test, predictions)

        return {"mae": mae, "rmse": rmse}


class RandomForestAlarmClassifier(BaseModelTrainer):
    def __init__(self, n_estimators=100):
        super().__init__(
            model_name="RandomForestAlarmClassifier",
            model=RandomForestClassifier(n_estimators=n_estimators, random_state=42),
        )

    def evaluate(self, y_test, predictions) -> dict:
        accuracy = accuracy_score(y_test, predictions)

        return {"accuracy": accuracy}

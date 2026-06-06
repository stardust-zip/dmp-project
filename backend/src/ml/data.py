import os

import pandas as pd


class DataLoader:
    def __init__(self, file_path: str):
        self.file_path = file_path

    def load_timeseries_target(self, target_column: str):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Data file not found: {self.file_path}")

        df = pd.read_csv(self.file_path, parse_dates=["timestamp"])
        df = df.sort_values("timestamp")

        df["hour"] = df["timestamp"].dt.hour
        df["dayofweek"] = df["timestamp"].dt.dayofweek
        df["month"] = df["timestamp"].dt.month

        df = df.dropna(subset=[target_column])

        features = ["hour", "dayofweek", "month"]
        X = df[features]
        y = df[target_column]

        return X, y

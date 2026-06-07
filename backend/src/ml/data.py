import os

import pandas as pd


class DataLoader:
    def __init__(
        self,
        file_path: str,
        *,
        timezone: str = "UTC",
        outlier_method: str = "iqr",
        iqr_multiplier: float = 1.5,
        zscore_threshold: float = 3.0,
    ):
        self.file_path = file_path
        self.timezone = timezone
        self.outlier_method = outlier_method
        self.iqr_multiplier = iqr_multiplier
        self.zscore_threshold = zscore_threshold

    def load_timeseries_target(self, target_column: str):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Data file not found: {self.file_path}")

        df = pd.read_csv(self.file_path)
        df = self._validate_required_columns(df, target_column)
        df = self._validate_and_normalize_timestamps(df)
        df = self._resolve_duplicates(df, target_column)
        df = self._resolve_missing_data(df, target_column)
        df = self._filter_outliers(df, target_column)
        df = df.sort_values("timestamp")

        df["hour"] = df["timestamp"].dt.hour
        df["dayofweek"] = df["timestamp"].dt.dayofweek
        df["month"] = df["timestamp"].dt.month

        features = ["hour", "dayofweek", "month"]
        X = df[features]
        y = df[target_column]

        return X, y

    @staticmethod
    def _validate_required_columns(
        df: pd.DataFrame, target_column: str
    ) -> pd.DataFrame:
        required_columns = {"timestamp", target_column}
        missing_columns = required_columns.difference(df.columns)
        if missing_columns:
            raise ValueError(
                f"Missing required column(s): {', '.join(sorted(missing_columns))}"
            )

        return df.loc[:, ["timestamp", target_column]].copy()

    def _validate_and_normalize_timestamps(self, df: pd.DataFrame) -> pd.DataFrame:
        timestamps = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        invalid_timestamps = timestamps.isna()
        if invalid_timestamps.any():
            raise ValueError(
                f"Found {invalid_timestamps.sum()} invalid or missing timestamp value(s)"
            )

        df = df.copy()
        df["timestamp"] = timestamps.dt.tz_convert(self.timezone)
        if df["timestamp"].dt.tz is None:
            raise ValueError("Timestamps must be timezone-aware after normalization")

        return df

    @staticmethod
    def _resolve_duplicates(df: pd.DataFrame, target_column: str) -> pd.DataFrame:
        df = df.drop_duplicates().copy()

        if df["timestamp"].duplicated().any():
            df = (
                df.groupby("timestamp", as_index=False, sort=True)
                .agg({target_column: "median"})
                .copy()
            )

        return df

    @staticmethod
    def _resolve_missing_data(df: pd.DataFrame, target_column: str) -> pd.DataFrame:
        df = df.sort_values("timestamp").copy()
        df[target_column] = pd.to_numeric(df[target_column], errors="coerce")

        if df[target_column].isna().all():
            raise ValueError(f"Target column '{target_column}' has no numeric values")

        if df[target_column].isna().any():
            df = df.set_index("timestamp")
            df[target_column] = df[target_column].interpolate(method="time")
            df[target_column] = df[target_column].bfill().ffill()
            df = df.reset_index()

        return df.dropna(subset=[target_column]).copy()

    def _filter_outliers(self, df: pd.DataFrame, target_column: str) -> pd.DataFrame:
        if self.outlier_method == "iqr":
            return self._filter_outliers_iqr(df, target_column)
        if self.outlier_method == "zscore":
            return self._filter_outliers_zscore(df, target_column)
        if self.outlier_method in {None, "none"}:
            return df.copy()

        raise ValueError(f"Unsupported outlier method: {self.outlier_method}")

    def _filter_outliers_iqr(
        self, df: pd.DataFrame, target_column: str
    ) -> pd.DataFrame:
        q1 = df[target_column].quantile(0.25)
        q3 = df[target_column].quantile(0.75)
        iqr = q3 - q1
        if pd.isna(iqr) or iqr == 0:
            return df.copy()

        lower_bound = q1 - (self.iqr_multiplier * iqr)
        upper_bound = q3 + (self.iqr_multiplier * iqr)
        return df[
            df[target_column].between(lower_bound, upper_bound, inclusive="both")
        ].copy()

    def _filter_outliers_zscore(
        self, df: pd.DataFrame, target_column: str
    ) -> pd.DataFrame:
        std = df[target_column].std(ddof=0)
        if pd.isna(std) or std == 0:
            return df.copy()

        zscores = (df[target_column] - df[target_column].mean()).abs() / std
        return df[zscores <= self.zscore_threshold].copy()

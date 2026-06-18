import os, json
import joblib
import numpy as np
import polars as pl


class EnergyForecaster:
    """Load 1 lần, dự đoán nhiều lần. Không phụ thuộc biến global của notebook."""

    def __init__(self, model_dir: str, model_name: str | None = None):
        with open(os.path.join(model_dir, "metadata.json"), encoding="utf-8") as f:
            self.meta = json.load(f)

        self.feature_cols = self.meta["feature_cols"]
        self.vocab        = joblib.load(os.path.join(model_dir, "vocab.pkl"))
        self.imputer      = joblib.load(os.path.join(model_dir, "imputer.pkl"))

        # mặc định dùng best_model trong metadata, hoặc chỉ định tay
        name  = model_name or self.meta.get("best_model") or next(iter(self.meta["models"]))
        fname = self.meta["models"][name]              # vd "xgboost.pkl"
        self.model      = joblib.load(os.path.join(model_dir, fname))
        self.model_name = name

    def _encode(self, df: pl.DataFrame) -> pl.DataFrame:
        exprs = []
        for col in self.feature_cols:                  # ép đúng thứ tự cột
            if col in self.vocab:
                m = self.vocab[col]
                exprs.append(
                    pl.col(col).cast(pl.String)
                      .map_elements(lambda x, m=m: m.get(x, -1), return_dtype=pl.Int32)
                      .cast(pl.Float32).alias(col)
                )
            else:
                exprs.append(pl.col(col).cast(pl.Float32).alias(col))
        return df.select(exprs)

    def predict(self, df: pl.DataFrame) -> np.ndarray:
        """df phải chứa đủ các cột trong feature_cols (đã feature-engineering)."""
        missing = set(self.feature_cols) - set(df.columns)
        if missing:
            raise ValueError(f"Thiếu features: {sorted(missing)}")
        X = self._encode(df).to_numpy().astype(np.float32)
        X = self.imputer.transform(X).astype(np.float32)
        return self.model.predict(X)
    
fc = EnergyForecaster("path to model")
preds = fc.predict(some_dataframe)   # some_dataframe: 1 hay nhiều hàng đều được
print(fc.model_name, preds[:5])
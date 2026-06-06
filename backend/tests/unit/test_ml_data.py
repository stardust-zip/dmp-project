import os
import tempfile

import pandas as pd
import pytest
from src.ml.data import DataLoader


@pytest.fixture
def mock_csv_file():
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range(start="2026-06-01", periods=5, freq="h"),
            "Panther_parking_Lorriane": [
                10.5,
                12.0,
                11.1,
                None,
                15.0,
            ],
        }
    )

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    df.to_csv(temp_file.name, index=False)
    yield temp_file.name

    os.remove(temp_file.name)


def test_data_loader_extracts_features_and_drops_nans(mock_csv_file):
    loader = DataLoader(mock_csv_file)

    X, y = loader.load_timeseries_target("Panther_parking_Lorriane")

    assert len(X) == 4
    assert len(y) == 4
    assert "hour" in X.columns
    assert "dayofweek" in X.columns

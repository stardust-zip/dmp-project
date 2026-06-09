from src.schemas import ModelTrainingRequest
from src.tasks import _registered_model_name


def test_registered_model_name_includes_task_site_and_metric():
    request = ModelTrainingRequest(
        site_id="Site 1",
        metrics=[" Electricity "],
        time_range_start="2026-06-01T00:00:00Z",
        time_range_end="2026-06-02T00:00:00Z",
    )

    assert (
        _registered_model_name(request)
        == "dmp_energy_forecasting_Site_1_electricity"
    )


def test_registered_model_name_separates_sites_and_metrics():
    site_1_electricity = ModelTrainingRequest(
        site_id="Site 1",
        metrics=["electricity"],
        time_range_start="2026-06-01T00:00:00Z",
        time_range_end="2026-06-02T00:00:00Z",
    )
    site_2_steam = ModelTrainingRequest(
        site_id="Site 2",
        metrics=["steam"],
        time_range_start="2026-06-01T00:00:00Z",
        time_range_end="2026-06-02T00:00:00Z",
    )

    assert _registered_model_name(site_1_electricity) != _registered_model_name(
        site_2_steam
    )

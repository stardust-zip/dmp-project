from src import seeder


def test_run_seeder_all_includes_weather_phase(monkeypatch):
    calls = []

    class FakeSession:
        def rollback(self):
            calls.append(("rollback",))

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(seeder, "_validate_data_paths", lambda *args: None)
    monkeypatch.setattr(seeder, "init_db", lambda: calls.append(("init_db",)))
    monkeypatch.setattr(seeder, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        seeder,
        "_run_reference_phase",
        lambda db, meta_csv: calls.append(("reference", meta_csv)),
    )
    monkeypatch.setattr(
        seeder,
        "_run_telemetry_phase",
        lambda db, meter_dir, metrics, chunk_size, batch_size, limit: calls.append(
            ("telemetry", meter_dir, metrics, chunk_size, batch_size, limit)
        ),
    )
    monkeypatch.setattr(
        seeder,
        "_run_weather_phase",
        lambda db, weather_csv: calls.append(("weather", weather_csv)),
    )

    seeder.run_seeder(
        phase="all",
        metrics=("electricity",),
        meta_csv="/tmp/metadata.csv",
        meter_dir="/tmp/meters",
        weather_csv="/tmp/weather.csv",
        limit=5,
    )

    assert ("reference", "/tmp/metadata.csv") in calls
    assert ("telemetry", "/tmp/meters", ("electricity",), 10_000, 10_000, 5) in calls
    assert ("weather", "/tmp/weather.csv") in calls

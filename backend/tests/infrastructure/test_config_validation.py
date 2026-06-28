"""
Infrastructure tests: environment configuration portability.

Every test instantiates _IsolatedSettings — a subclass of the production
Settings that disables .env file loading.  This guarantees tests are not
coupled to whatever .env a developer happens to have on their machine and
that the same tests pass unmodified in CI (where no .env file exists).
"""

import os

import pytest
from pydantic_settings import SettingsConfigDict

from src.core.config import Settings


class _IsolatedSettings(Settings):
    """
    Test-only Settings subclass.

    Why env_file=None: pydantic-settings auto-loads '.env' from the CWD,
    which would silently bind tests to developer-specific values and make
    them non-portable in CI environments where no .env is present.
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")


# ---------------------------------------------------------------------------
# Default value assertions
# ---------------------------------------------------------------------------


def test_project_name_has_a_default_value():
    assert _IsolatedSettings().PROJECT_NAME == "DMP Smart City AI Platform"


def test_api_prefix_follows_v1_convention():
    assert _IsolatedSettings().API_V1_STR == "/api/v1"


def test_database_url_defaults_to_a_postgresql_connection_string():
    assert _IsolatedSettings().DATABASE_URL.startswith("postgresql://")


def test_redis_url_defaults_to_a_valid_redis_scheme():
    assert _IsolatedSettings().REDIS_URL.startswith("redis://")


def test_mlflow_tracking_uri_defaults_to_an_http_endpoint():
    uri = _IsolatedSettings().MLFLOW_TRACKING_URI
    assert uri.startswith("http://") or uri.startswith("https://")


def test_cors_origins_defaults_to_a_non_empty_list():
    origins = _IsolatedSettings().BACKEND_CORS_ORIGINS
    assert isinstance(origins, list)
    assert len(origins) > 0


def test_all_default_cors_origins_are_valid_http_origins():
    for origin in _IsolatedSettings().BACKEND_CORS_ORIGINS:
        assert origin.startswith("http://") or origin.startswith("https://"), (
            f"CORS origin '{origin}' is not a valid HTTP/S URL"
        )


def test_secret_key_has_a_non_empty_value():
    assert _IsolatedSettings().SECRET_KEY


def test_access_token_expiry_is_a_positive_number_of_minutes():
    assert _IsolatedSettings().ACCESS_TOKEN_EXPIRE_MINUTES > 0


# ---------------------------------------------------------------------------
# Environment variable override portability
# ---------------------------------------------------------------------------


def test_database_url_is_overridable_via_environment_variable(monkeypatch):
    custom_url = "postgresql://ci_user:ci_pass@db_host:5432/ci_db"
    monkeypatch.setenv("DATABASE_URL", custom_url)
    assert _IsolatedSettings().DATABASE_URL == custom_url


def test_redis_url_is_overridable_via_environment_variable(monkeypatch):
    custom_url = "redis://ci_redis_host:6380/2"
    monkeypatch.setenv("REDIS_URL", custom_url)
    assert _IsolatedSettings().REDIS_URL == custom_url


def test_mlflow_uri_is_overridable_via_environment_variable(monkeypatch):
    custom_uri = "http://mlflow.staging.internal:5000"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", custom_uri)
    assert _IsolatedSettings().MLFLOW_TRACKING_URI == custom_uri


def test_cors_origins_list_is_overridable_via_environment_variable(monkeypatch):
    monkeypatch.setenv(
        "BACKEND_CORS_ORIGINS", '["http://staging.example.com", "https://app.example.com"]'
    )
    origins = _IsolatedSettings().BACKEND_CORS_ORIGINS
    assert "http://staging.example.com" in origins
    assert "https://app.example.com" in origins


def test_project_name_is_overridable_via_environment_variable(monkeypatch):
    monkeypatch.setenv("PROJECT_NAME", "DMP Staging")
    assert _IsolatedSettings().PROJECT_NAME == "DMP Staging"

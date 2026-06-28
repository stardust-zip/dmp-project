"""
Infrastructure tests: API health endpoint contract.

The /health endpoint is the Docker Compose healthcheck target for the backend
service.  If its contract changes (status code, response body shape), all
11 containers that depend on the backend would stop reaching healthy state.

These tests use FastAPI's TestClient (no real server process needed) to lock
down the contract independently of the database or any external service.
"""

import pytest
from fastapi.testclient import TestClient

from src.main import app

_client = TestClient(app)


# ---------------------------------------------------------------------------
# /health — Docker Compose healthcheck target
# ---------------------------------------------------------------------------


def test_health_endpoint_returns_http_200():
    response = _client.get("/health")
    assert response.status_code == 200


def test_health_endpoint_content_type_is_json():
    response = _client.get("/health")
    assert "application/json" in response.headers["content-type"]


def test_health_endpoint_body_reports_healthy_status():
    response = _client.get("/health")
    assert response.json()["status"] == "healthy"


def test_health_endpoint_body_identifies_the_service():
    """
    The Docker Compose healthcheck uses this exact URL pattern.
    The 'service' field lets operators identify which container returned
    the response when running behind a reverse proxy.
    """
    response = _client.get("/health")
    assert response.json()["service"] == "dmp-backend"


def test_health_endpoint_requires_no_authentication():
    """
    A healthcheck must never need auth credentials — the Docker daemon
    calls it without any Authorization header.
    """
    response = _client.get("/health")
    assert response.status_code != 401
    assert response.status_code != 403


# ---------------------------------------------------------------------------
# / — root endpoint (service discovery)
# ---------------------------------------------------------------------------


def test_root_endpoint_returns_http_200():
    response = _client.get("/")
    assert response.status_code == 200


def test_root_endpoint_includes_docs_link():
    """The root response must point to /docs so operators can reach the OpenAPI UI."""
    body = _client.get("/").json()
    assert "docs" in body
    assert body["docs"] == "/docs"


def test_root_endpoint_includes_redoc_link():
    body = _client.get("/").json()
    assert "redoc" in body
    assert body["redoc"] == "/redoc"


def test_root_endpoint_includes_a_running_message():
    """The root message must confirm the platform is running."""
    body = _client.get("/").json()
    assert "message" in body
    assert "running" in body["message"].lower()

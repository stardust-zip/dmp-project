from fastapi.testclient import TestClient
from src.core.exceptions import NotFoundException, ValidationException
from src.main import app


def test_custom_exception_handler(client):
    """
    Test that our global exception handler catches DMPException
    and returns the correct JSON format.
    """

    @app.get("/test-error/not-found")
    def trigger_not_found():
        raise NotFoundException("User not found", details={"id": 123})

    @app.get("/test-error/validation")
    def trigger_validation():
        raise ValidationException("Invalid email format")

    # Test Not Found
    response = client.get("/test-error/not-found")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "NOT_FOUND"
    assert data["error"]["message"] == "User not found"
    assert data["error"]["details"]["id"] == 123

    # Test Validation
    response = client.get("/test-error/validation")
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["message"] == "Invalid email format"
    assert data["error"]["details"] is None


def test_unhandled_exception_handler():
    """Test that generic exceptions are caught and hidden from the user."""
    with TestClient(app, raise_server_exceptions=False) as client:

        @app.get("/test-error/unhandled")
        def trigger_unhandled():
            raise ValueError("Sensitive system error message")

        response = client.get("/test-error/unhandled")
        assert response.status_code == 500
        data = response.json()
        assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
        assert "unexpected error" in data["error"]["message"]
        assert "Sensitive" not in data["error"]["message"]

def test_health_check(client):
    """Test healthcheck endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "dmp-backend"}


def test_root_endpoint(client):
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    assert "DMP Smart City AI Platform is running" in response.json()["message"]

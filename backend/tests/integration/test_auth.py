from fastapi.testclient import TestClient

from src import models
from src.core.security import create_access_token, verify_password
from src.database import get_db
from src.main import app
from src.seeders.users import DEFAULT_USERS, seed_default_users


def override_db(db_session):
    def _override_db():
        yield db_session

    return _override_db


def test_seed_default_users_is_idempotent(db_session):
    first = seed_default_users(db_session)
    second = seed_default_users(db_session)

    users = db_session.query(models.User).all()

    assert first == {"created": len(DEFAULT_USERS), "updated": 0}
    assert second == {"created": 0, "updated": 0}
    assert len(users) == len(DEFAULT_USERS)
    assert {user.email for user in users} == {user.email for user in DEFAULT_USERS}


def test_seed_default_users_does_not_reset_existing_password_by_default(db_session):
    seed_default_users(db_session, password="first-password")
    seed_default_users(db_session, password="second-password")

    user = (
        db_session.query(models.User)
        .filter(models.User.email == "admin@dmp.com")
        .one()
    )

    assert verify_password("first-password", user.password_hash)
    assert not verify_password("second-password", user.password_hash)


def test_login_uses_persisted_user(db_session):
    seed_default_users(db_session)
    app.dependency_overrides[get_db] = override_db(db_session)
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "admin@dmp.com", "password": "demo123"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]


def test_current_user_is_loaded_from_database(db_session):
    seed_default_users(db_session)
    token = create_access_token(subject="operator@dmp.com", role="Operator")
    app.dependency_overrides[get_db] = override_db(db_session)
    client = TestClient(app)

    try:
        response = client.get(
            "/api/v1/metadata/locations",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200

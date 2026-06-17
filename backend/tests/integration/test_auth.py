from fastapi.testclient import TestClient

from src import models
from src.core.security import create_access_token, verify_password
from src.database import get_db
from src.main import app
from src.seeders.users import _build_seed_users, seed_default_users

# Canonical set of demo emails (invariant regardless of DB state).
_EXPECTED_SEED_USERS = _build_seed_users([])
_EXPECTED_EMAILS = {u.email for u in _EXPECTED_SEED_USERS}
_EXPECTED_COUNT = len(_EXPECTED_SEED_USERS)


def override_db(db_session):
    def _override_db():
        yield db_session

    return _override_db


def test_seed_default_users_is_idempotent(db_session):
    first = seed_default_users(db_session)
    second = seed_default_users(db_session)

    users = db_session.query(models.User).all()

    assert first == {"created": _EXPECTED_COUNT, "updated": 0}
    assert second == {"created": 0, "updated": 0}
    assert len(users) == _EXPECTED_COUNT
    assert {user.email for user in users} == _EXPECTED_EMAILS


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


def test_me_returns_database_user_even_when_token_role_is_stale(db_session):
    seed_default_users(db_session)
    token = create_access_token(subject="admin@dmp.com", role="Operator")
    app.dependency_overrides[get_db] = override_db(db_session)
    client = TestClient(app)

    try:
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "admin@dmp.com"
    assert data["full_name"] == "Demo Admin"
    assert data["role"] == "Admin"

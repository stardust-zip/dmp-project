from fastapi.testclient import TestClient

from src import models
from src.api.v1.deps import get_current_admin
from src.core.security import verify_password
from src.database import get_db
from src.main import app
from src.schemas import UserResponse


def override_db(db_session):
    def _override_db():
        yield db_session

    return _override_db


def override_admin(user):
    def _override_admin():
        return user

    return _override_admin


def test_admin_can_list_users(db_session):
    db_session.add_all(
        [
            models.User(
                email="operator@example.com",
                full_name="Operator User",
                password_hash="hash",
                role="Operator",
            ),
            models.User(
                email="ai@example.com",
                full_name="AI Engineer",
                password_hash="hash",
                role="AI_Engineer",
            ),
        ]
    )
    db_session.commit()
    app.dependency_overrides[get_db] = override_db(db_session)
    app.dependency_overrides[get_current_admin] = override_admin(
        UserResponse(
            id="admin-id",
            email="admin@example.com",
            full_name="Admin User",
            role="Admin",
        )
    )
    client = TestClient(app)

    try:
        response = client.get("/api/v1/users")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [user["email"] for user in response.json()] == [
        "ai@example.com",
        "operator@example.com",
    ]


def test_admin_can_create_user_with_hashed_password(db_session):
    app.dependency_overrides[get_db] = override_db(db_session)
    app.dependency_overrides[get_current_admin] = override_admin(
        UserResponse(
            id="admin-id",
            email="admin@example.com",
            full_name="Admin User",
            role="Admin",
        )
    )
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/users",
            json={
                "email": "operator@example.com",
                "full_name": "Operator User",
                "password": "secret-password",
                "role": "Operator",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "operator@example.com"
    assert data["role"] == "Operator"

    user = (
        db_session.query(models.User)
        .filter(models.User.email == "operator@example.com")
        .one()
    )
    assert user.password_hash != "secret-password"
    assert verify_password("secret-password", user.password_hash)


def test_create_user_rejects_duplicate_email(db_session):
    db_session.add(
        models.User(
            email="operator@example.com",
            full_name="Existing User",
            password_hash="hash",
            role="Operator",
        )
    )
    db_session.commit()
    app.dependency_overrides[get_db] = override_db(db_session)
    app.dependency_overrides[get_current_admin] = override_admin(
        UserResponse(
            id="admin-id",
            email="admin@example.com",
            full_name="Admin User",
            role="Admin",
        )
    )
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/users",
            json={
                "email": "operator@example.com",
                "full_name": "Operator User",
                "password": "secret-password",
                "role": "Operator",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409


def test_admin_can_update_user_role(db_session):
    user = models.User(
        email="operator@example.com",
        full_name="Operator User",
        password_hash="hash",
        role="Operator",
    )
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_db] = override_db(db_session)
    app.dependency_overrides[get_current_admin] = override_admin(
        UserResponse(
            id="admin-id",
            email="admin@example.com",
            full_name="Admin User",
            role="Admin",
        )
    )
    client = TestClient(app)

    try:
        response = client.patch(
            f"/api/v1/users/{user.id}", json={"role": "AI_Engineer"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["role"] == "AI_Engineer"
    db_session.refresh(user)
    assert user.role == "AI_Engineer"


def test_admin_can_delete_user(db_session):
    user = models.User(
        email="operator@example.com",
        full_name="Operator User",
        password_hash="hash",
        role="Operator",
    )
    db_session.add(user)
    db_session.commit()
    user_id = user.id
    app.dependency_overrides[get_db] = override_db(db_session)
    app.dependency_overrides[get_current_admin] = override_admin(
        UserResponse(
            id="admin-id",
            email="admin@example.com",
            full_name="Admin User",
            role="Admin",
        )
    )
    client = TestClient(app)

    try:
        response = client.delete(f"/api/v1/users/{user_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert (
        db_session.query(models.User).filter(models.User.id == user_id).one_or_none()
        is None
    )

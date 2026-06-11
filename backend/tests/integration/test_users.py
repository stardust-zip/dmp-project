from fastapi.testclient import TestClient
import pytest

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


def add_site(db_session, site_id="site-a", name="Site A"):
    db_session.add(models.LocationType(id="site", description="Top-level site"))
    db_session.add(models.Location(id=site_id, location_type_id="site", name=name))
    db_session.commit()


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
            is_global_admin=True,
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
    add_site(db_session)
    app.dependency_overrides[get_db] = override_db(db_session)
    app.dependency_overrides[get_current_admin] = override_admin(
        UserResponse(
            id="admin-id",
            email="admin@example.com",
            full_name="Admin User",
            role="Admin",
            is_global_admin=True,
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
                "contact_number": "+15551234567",
                "assigned_site_ids": ["site-a"],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "operator@example.com"
    assert data["role"] == "Operator"
    assert data["status"] == "Off_Duty"
    assert data["contact_number"] == "+15551234567"
    assert data["assigned_site_ids"] == ["site-a"]

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
            is_global_admin=True,
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
                "assigned_site_ids": ["site-a"],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409


@pytest.mark.parametrize("role", ["PO", "Developer"])
def test_create_user_rejects_removed_roles(db_session, role):
    app.dependency_overrides[get_db] = override_db(db_session)
    app.dependency_overrides[get_current_admin] = override_admin(
        UserResponse(
            id="admin-id",
            email="admin@example.com",
            full_name="Admin User",
            role="Admin",
            is_global_admin=True,
        )
    )
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/users",
            json={
                "email": f"{role.lower()}@example.com",
                "full_name": "Removed Role",
                "password": "secret-password",
                "role": role,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_admin_can_update_user_role(db_session):
    add_site(db_session)
    user = models.User(
        email="operator@example.com",
        full_name="Operator User",
        password_hash="hash",
        role="Operator",
        assigned_site_ids=["site-a"],
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
            is_global_admin=True,
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
            is_global_admin=True,
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

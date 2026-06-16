from fastapi.testclient import TestClient
from uuid import uuid4
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


def _make_site(db_session, site_id="site-a", name="Site A"):
    """Create a site location type + location row. Idempotent per site_id."""
    lt = (
        db_session.query(models.LocationType)
        .filter(models.LocationType.id == "site")
        .one_or_none()
    )
    if lt is None:
        db_session.add(models.LocationType(id="site", description="Top-level site"))
    loc = (
        db_session.query(models.Location)
        .filter(models.Location.id == site_id)
        .one_or_none()
    )
    if loc is None:
        db_session.add(
            models.Location(id=site_id, location_type_id="site", name=name)
        )
        db_session.commit()


def _make_building(db_session, bld_id, site_id, name="Building"):
    """Create a child building under *site_id*. Idempotent."""
    lt = (
        db_session.query(models.LocationType)
        .filter(models.LocationType.id == "building")
        .one_or_none()
    )
    if lt is None:
        db_session.add(models.LocationType(id="building", description="Building"))
    loc = (
        db_session.query(models.Location)
        .filter(models.Location.id == bld_id)
        .one_or_none()
    )
    if loc is None:
        db_session.add(
            models.Location(
                id=bld_id,
                location_type_id="building",
                parent_id=site_id,
                name=name,
            )
        )
        db_session.commit()


def _global_admin() -> UserResponse:
    return UserResponse(
        id=str(uuid4()),
        email="global@example.com",
        full_name="Global Admin",
        role="Admin",
        is_global_admin=True,
    )


def _site_admin(site_ids=None) -> UserResponse:
    return UserResponse(
        id=str(uuid4()),
        email="site@example.com",
        full_name="Site Admin",
        role="Admin",
        assigned_site_ids=site_ids or ["site-a"],
    )


def _client(db_session, admin):
    app.dependency_overrides[get_db] = override_db(db_session)
    app.dependency_overrides[get_current_admin] = override_admin(admin)
    return TestClient(app)


# ──────────────────────────────────────────────────────────────────────
# List users — scope filtering
# ──────────────────────────────────────────────────────────────────────

def test_global_admin_sees_all_users(db_session):
    db_session.add_all(
        [
            models.User(email="op@x.com", full_name="Op", password_hash="h", role="Operator", assigned_site_ids=["site-a"]),
            models.User(email="ai@x.com", full_name="AI", password_hash="h", role="AI_Engineer"),
            models.User(email="admin2@x.com", full_name="Admin2", password_hash="h", role="Admin"),
        ]
    )
    db_session.commit()
    client = _client(db_session, _global_admin())

    try:
        resp = client.get("/api/v1/users")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert "op@x.com" in emails
    assert "ai@x.com" in emails
    assert "admin2@x.com" in emails


def test_site_admin_sees_only_operators_in_their_sites(db_session):
    _make_site(db_session, "site-a", "Site A")
    _make_site(db_session, "site-b", "Site B")
    db_session.add_all(
        [
            models.User(email="op-a@x.com", full_name="OpA", password_hash="h", role="Operator", assigned_site_ids=["site-a"]),
            models.User(email="op-b@x.com", full_name="OpB", password_hash="h", role="Operator", assigned_site_ids=["site-b"]),
            models.User(email="admin2@x.com", full_name="Admin2", password_hash="h", role="Admin", assigned_site_ids=["site-a"]),
            models.User(email="global@x.com", full_name="Global", password_hash="h", role="Admin", is_global_admin=True),
            models.User(email="ai@x.com", full_name="AI", password_hash="h", role="AI_Engineer"),
        ]
    )
    db_session.commit()
    client = _client(db_session, _site_admin(["site-a"]))

    try:
        resp = client.get("/api/v1/users")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    # site admin sees operators in site-a
    assert "op-a@x.com" in emails
    # site admin does NOT see operators from other sites
    assert "op-b@x.com" not in emails
    # site admin does NOT see other admins (global or site-scoped)
    assert "admin2@x.com" not in emails
    assert "global@x.com" not in emails
    # site admin does NOT see AI engineers
    assert "ai@x.com" not in emails


# ──────────────────────────────────────────────────────────────────────
# Create user — single-site enforcement
# ──────────────────────────────────────────────────────────────────────

def test_create_operator_rejects_multi_site_locations(db_session):
    _make_site(db_session, "site-a", "Site A")
    _make_site(db_session, "site-b", "Site B")
    client = _client(db_session, _global_admin())

    try:
        resp = client.post(
            "/api/v1/users",
            json={
                "email": "op@x.com",
                "full_name": "Op",
                "password": "secret",
                "role": "Operator",
                "assigned_site_ids": ["site-a", "site-b"],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422
    assert "single site" in resp.json()["detail"].lower()


def test_create_operator_allows_multi_building_same_site(db_session):
    _make_site(db_session, "site-a", "Site A")
    _make_building(db_session, "bld-1", "site-a", "Building 1")
    _make_building(db_session, "bld-2", "site-a", "Building 2")
    client = _client(db_session, _global_admin())

    try:
        resp = client.post(
            "/api/v1/users",
            json={
                "email": "op@x.com",
                "full_name": "Op",
                "password": "secret",
                "role": "Operator",
                "assigned_site_ids": ["bld-1", "bld-2", "site-a"],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 201
    assert set(resp.json()["assigned_site_ids"]) == {"bld-1", "bld-2", "site-a"}


# ──────────────────────────────────────────────────────────────────────
# Update user — site-scoped access control
# ──────────────────────────────────────────────────────────────────────

def test_site_admin_cannot_edit_operator_outside_scope(db_session):
    _make_site(db_session, "site-a")
    _make_site(db_session, "site-b")
    user = models.User(
        email="op@x.com", full_name="Op", password_hash="h",
        role="Operator", assigned_site_ids=["site-b"],
    )
    db_session.add(user)
    db_session.commit()
    client = _client(db_session, _site_admin(["site-a"]))

    try:
        resp = client.patch(f"/api/v1/users/{user.id}", json={"status": "In_Shift"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403


def test_site_admin_cannot_edit_another_admin(db_session):
    _make_site(db_session, "site-a")
    admin2 = models.User(
        email="admin2@x.com", full_name="Admin2", password_hash="h",
        role="Admin", assigned_site_ids=["site-a"],
    )
    db_session.add(admin2)
    db_session.commit()
    client = _client(db_session, _site_admin(["site-a"]))

    try:
        resp = client.patch(f"/api/v1/users/{admin2.id}", json={"status": "In_Shift"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403


def test_site_admin_can_edit_operator_in_scope(db_session):
    _make_site(db_session, "site-a")
    user = models.User(
        email="op@x.com", full_name="Op", password_hash="h",
        role="Operator", assigned_site_ids=["site-a"],
    )
    db_session.add(user)
    db_session.commit()
    client = _client(db_session, _site_admin(["site-a"]))

    try:
        resp = client.patch(
            f"/api/v1/users/{user.id}",
            json={"full_name": "Updated Op", "status": "In_Shift"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated Op"
    assert resp.json()["status"] == "In_Shift"


def test_site_admin_cannot_delete_operator_outside_scope(db_session):
    _make_site(db_session, "site-a")
    _make_site(db_session, "site-b")
    user = models.User(
        email="op@x.com", full_name="Op", password_hash="h",
        role="Operator", assigned_site_ids=["site-b"],
    )
    db_session.add(user)
    db_session.commit()
    client = _client(db_session, _site_admin(["site-a"]))

    try:
        resp = client.delete(f"/api/v1/users/{user.id}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403


def test_site_admin_cannot_delete_another_admin(db_session):
    _make_site(db_session, "site-a")
    admin2 = models.User(
        email="admin2@x.com", full_name="Admin2", password_hash="h",
        role="Admin", assigned_site_ids=["site-a"],
    )
    db_session.add(admin2)
    db_session.commit()
    client = _client(db_session, _site_admin(["site-a"]))

    try:
        resp = client.delete(f"/api/v1/users/{admin2.id}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403


def test_site_admin_can_delete_operator_in_scope(db_session):
    _make_site(db_session, "site-a")
    user = models.User(
        email="op@x.com", full_name="Op", password_hash="h",
        role="Operator", assigned_site_ids=["site-a"],
    )
    db_session.add(user)
    db_session.commit()
    user_id = user.id
    client = _client(db_session, _site_admin(["site-a"]))

    try:
        resp = client.delete(f"/api/v1/users/{user_id}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 204


# ──────────────────────────────────────────────────────────────────────
# Email uniqueness on update
# ──────────────────────────────────────────────────────────────────────

def test_update_user_rejects_duplicate_email(db_session):
    _make_site(db_session, "site-a")
    db_session.add_all(
        [
            models.User(email="existing@x.com", full_name="Existing", password_hash="h", role="Operator", assigned_site_ids=["site-a"]),
            models.User(email="target@x.com", full_name="Target", password_hash="h", role="Operator", assigned_site_ids=["site-a"]),
        ]
    )
    db_session.commit()
    target = db_session.query(models.User).filter(models.User.email == "target@x.com").one()
    client = _client(db_session, _global_admin())

    try:
        resp = client.patch(f"/api/v1/users/{target.id}", json={"email": "existing@x.com"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409


def test_update_user_allows_same_email(db_session):
    """Updating email to the same value should be a no-op, not a conflict."""
    _make_site(db_session, "site-a")
    user = models.User(
        email="op@x.com", full_name="Op", password_hash="h",
        role="Operator", assigned_site_ids=["site-a"],
    )
    db_session.add(user)
    db_session.commit()
    client = _client(db_session, _global_admin())

    try:
        resp = client.patch(f"/api/v1/users/{user.id}", json={"email": "op@x.com"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────
# Name and email editability
# ──────────────────────────────────────────────────────────────────────

def test_update_user_changes_name_and_email(db_session):
    _make_site(db_session, "site-a")
    user = models.User(
        email="old@x.com", full_name="Old Name", password_hash="h",
        role="Operator", assigned_site_ids=["site-a"],
    )
    db_session.add(user)
    db_session.commit()
    client = _client(db_session, _global_admin())

    try:
        resp = client.patch(
            f"/api/v1/users/{user.id}",
            json={"full_name": "New Name", "email": "new@x.com"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["full_name"] == "New Name"
    assert data["email"] == "new@x.com"


# ──────────────────────────────────────────────────────────────────────
# Keep existing tests
# ──────────────────────────────────────────────────────────────────────

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
    _make_site(db_session)
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


def test_create_user_rejects_duplicate_contact_number(db_session):
    _make_site(db_session)
    db_session.add(
        models.User(
            email="existing@example.com",
            full_name="Existing User",
            password_hash="hash",
            role="Operator",
            contact_number="+1 555 123 4567",
            assigned_site_ids=["site-a"],
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
                "contact_number": "+15551234567",
                "assigned_site_ids": ["site-a"],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "contact number" in response.json()["detail"].lower()


def test_update_user_rejects_duplicate_contact_number(db_session):
    _make_site(db_session)
    db_session.add_all(
        [
            models.User(
                email="existing@example.com",
                full_name="Existing",
                password_hash="h",
                role="Operator",
                contact_number="+1 555 123 4567",
                assigned_site_ids=["site-a"],
            ),
            models.User(
                email="target@example.com",
                full_name="Target",
                password_hash="h",
                role="Operator",
                assigned_site_ids=["site-a"],
            ),
        ]
    )
    db_session.commit()
    target = db_session.query(models.User).filter(models.User.email == "target@example.com").one()
    client = _client(db_session, _global_admin())

    try:
        response = client.patch(
            f"/api/v1/users/{target.id}",
            json={"contact_number": "+15551234567"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "contact number" in response.json()["detail"].lower()


def test_update_user_can_clear_contact_number(db_session):
    _make_site(db_session)
    user = models.User(
        email="operator@example.com",
        full_name="Operator",
        password_hash="h",
        role="Operator",
        contact_number="+1 555 123 4567",
        assigned_site_ids=["site-a"],
    )
    db_session.add(user)
    db_session.commit()
    client = _client(db_session, _global_admin())

    try:
        response = client.patch(
            f"/api/v1/users/{user.id}",
            json={"contact_number": None},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["contact_number"] is None


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
    _make_site(db_session)
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

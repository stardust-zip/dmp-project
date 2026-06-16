from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from src import models
from src.api.v1.deps import get_current_admin, to_user_response
from src.core.security import get_password_hash
from src.database import get_db
from src.schemas import UserCreate, UserResponse, UserRole, UserRoleUpdate

router = APIRouter()


def _role_value(role: object) -> str:
    return str(getattr(role, "value", role))


def _site_ids(value: list[str] | None) -> list[str]:
    return sorted(set(value or []))


def _normalized_contact_number(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "".join(char for char in value.strip() if char.isdigit() or char == "+")
    return normalized or None


def _validate_contact_number_available(
    db: Session,
    contact_number: str | None,
    *,
    exclude_user_id: UUID | None = None,
) -> None:
    normalized_contact = _normalized_contact_number(contact_number)
    if normalized_contact is None:
        return

    users = db.query(models.User).filter(models.User.contact_number.isnot(None)).all()
    for user in users:
        if exclude_user_id is not None and user.id == exclude_user_id:
            continue
        if _normalized_contact_number(user.contact_number) == normalized_contact:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this contact number already exists.",
            )


def _validate_locations_exist(db: Session, location_ids: list[str]) -> None:
    if not location_ids:
        return

    locations = (
        db.query(models.Location.id).filter(models.Location.id.in_(location_ids)).all()
    )
    found_location_ids = {location.id for location in locations}
    missing = sorted(set(location_ids) - found_location_ids)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Assigned locations do not exist: {', '.join(missing)}",
        )


def _resolve_single_site(db: Session, location_ids: list[str]) -> str | None:
    """
    Return the single site that all *location_ids* belong to.

    Walks the parent chain of each location until a ``location_type_id ==
    "site"`` row is found.  If the locations span more than one site a
    422 error is raised — operators may be assigned to multiple buildings
    but they must all live under the same site.
    """
    if not location_ids:
        return None

    # Load all referenced locations (and their immediate parents if needed).
    loc_map: dict[str, models.Location] = {
        loc.id: loc
        for loc in db.query(models.Location)
        .filter(models.Location.id.in_(location_ids))
        .all()
    }
    missing_parents = {
        loc.parent_id
        for loc in loc_map.values()
        if loc.parent_id and loc.parent_id not in loc_map
    }
    if missing_parents:
        for ploc in db.query(models.Location).filter(
            models.Location.id.in_(missing_parents)
        ).all():
            loc_map[ploc.id] = ploc

    site_ids: set[str] = set()
    site_names: list[str] = []

    for loc_id in location_ids:
        current = loc_map.get(loc_id)
        while current:
            if current.location_type_id == "site":
                if current.id not in site_ids:
                    site_names.append(current.name)
                site_ids.add(current.id)
                break
            current = loc_map.get(current.parent_id) if current.parent_id else None

    if len(site_ids) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Operators can only be assigned to locations within a single site. "
                f"These locations span multiple sites: {', '.join(site_names)}."
            ),
        )

    return site_ids.pop() if site_ids else None


def _can_manage_user(current_user: UserResponse, target_user: models.User) -> bool:
    # Global admins can manage any account.
    if current_user.is_global_admin:
        return True
    # Users can always manage their own account.
    if str(target_user.id) == current_user.id:
        return True
    # Site-scoped admins cannot manage any other admin user.
    if target_user.role == "Admin":
        return False
    # Site-scoped admins can manage operators who share at least one
    # assigned site.  Because operators are restricted to a single site
    # (enforced by _resolve_single_site), there is no cross-admin
    # ownership conflict.
    return bool(
        set(current_user.assigned_site_ids) & set(target_user.assigned_site_ids or [])
    )


def _assert_can_assign_scope(
    current_user: UserResponse,
    *,
    role: str,
    assigned_site_ids: list[str],
    is_global_admin: bool,
) -> None:
    if role == UserRole.AIEngineer.value:
        return
    if role == UserRole.Admin.value and is_global_admin:
        if not current_user.is_global_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only global admins can grant global admin access.",
            )
        return
    if (
        role in {UserRole.Admin.value, UserRole.Operator.value}
        and not assigned_site_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Assigned sites are required for scoped Admin and Operator users.",
        )
    if not current_user.is_global_admin:
        unauthorized_sites = sorted(
            set(assigned_site_ids) - set(current_user.assigned_site_ids)
        )
        if unauthorized_sites:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cannot assign locations outside your scope: {', '.join(unauthorized_sites)}",
            )


def _normalized_scope(
    role: str, assigned_site_ids: list[str], is_global_admin: bool
) -> tuple[list[str], bool]:
    if role == UserRole.AIEngineer.value:
        return [], False
    if role != UserRole.Admin.value:
        return assigned_site_ids, False
    return ([] if is_global_admin else assigned_site_ids), is_global_admin


@router.get("", response_model=list[UserResponse])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[UserResponse, Depends(get_current_admin)],
) -> list[UserResponse]:
    """
    List users visible to the current admin.

    * **Global admins** see every account in the system.
    * **Site-scoped admins** see only users who share at least one
      assigned site with them (including themselves).
    """
    query = db.query(models.User)
    if not current_user.is_global_admin:
        # A site-scoped admin can only see users whose assigned_site_ids
        # JSONB array contains at least one of the admin's own sites.
        # Uses PostgreSQL `@>` (contains) operator on the JSONB column.
        site_conditions = [
            models.User.assigned_site_ids.contains([site_id])
            for site_id in current_user.assigned_site_ids
        ]
        if site_conditions:
            query = query.filter(
                (or_(*site_conditions) & (models.User.role != "Admin"))
                | (models.User.id == current_user.id)
            )
        else:
            # Site admin with no assigned sites can only see themselves.
            query = query.filter(models.User.id == current_user.id)
    users = query.order_by(models.User.email).all()
    return [to_user_response(user) for user in users]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[UserResponse, Depends(get_current_admin)],
) -> UserResponse:
    existing_user = (
        db.query(models.User).filter(models.User.email == payload.email).one_or_none()
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )
    _validate_contact_number_available(db, payload.contact_number)

    role = _role_value(payload.role)
    assigned_site_ids, is_global_admin = _normalized_scope(
        role, _site_ids(payload.assigned_site_ids), payload.is_global_admin
    )
    _validate_locations_exist(db, assigned_site_ids)
    # Operators must belong to a single site (multiple buildings within
    # that site are fine).
    if role == UserRole.Operator.value:
        _resolve_single_site(db, assigned_site_ids)
    _assert_can_assign_scope(
        current_user,
        role=role,
        assigned_site_ids=assigned_site_ids,
        is_global_admin=is_global_admin,
    )

    user = models.User(
        email=str(payload.email),
        full_name=payload.full_name,
        password_hash=get_password_hash(payload.password),
        role=role,
        status=_role_value(payload.status),
        contact_number=payload.contact_number,
        assigned_site_ids=assigned_site_ids,
        is_global_admin=is_global_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return to_user_response(user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user_role(
    user_id: UUID,
    payload: UserRoleUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[UserResponse, Depends(get_current_admin)],
) -> UserResponse:
    user = db.query(models.User).filter(models.User.id == user_id).one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    if not _can_manage_user(current_user, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot manage users outside your assigned sites.",
        )

    role = _role_value(payload.role) if payload.role is not None else user.role
    assigned_site_ids = (
        _site_ids(payload.assigned_site_ids)
        if payload.assigned_site_ids is not None
        else _site_ids(user.assigned_site_ids)
    )
    is_global_admin = (
        payload.is_global_admin
        if payload.is_global_admin is not None
        else bool(user.is_global_admin)
    )
    assigned_site_ids, is_global_admin = _normalized_scope(
        role, assigned_site_ids, is_global_admin
    )
    _validate_locations_exist(db, assigned_site_ids)
    if role == UserRole.Operator.value:
        _resolve_single_site(db, assigned_site_ids)
    _assert_can_assign_scope(
        current_user,
        role=role,
        assigned_site_ids=assigned_site_ids,
        is_global_admin=is_global_admin,
    )

    if payload.email is not None:
        normalized_email = str(payload.email).strip().lower()
        if normalized_email != user.email:
            existing = (
                db.query(models.User)
                .filter(models.User.email == normalized_email)
                .one_or_none()
            )
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A user with this email already exists.",
                )
            user.email = normalized_email

    if "contact_number" in payload.model_fields_set:
        _validate_contact_number_available(
            db, payload.contact_number, exclude_user_id=user.id
        )

    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()

    user.role = role
    if payload.status is not None:
        user.status = _role_value(payload.status)
    if "contact_number" in payload.model_fields_set:
        user.contact_number = payload.contact_number
    user.assigned_site_ids = assigned_site_ids
    user.is_global_admin = is_global_admin
    db.commit()
    db.refresh(user)
    return to_user_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[UserResponse, Depends(get_current_admin)],
) -> Response:
    if str(user_id) == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admins cannot deactivate their own account.",
        )

    user = db.query(models.User).filter(models.User.id == user_id).one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    if not _can_manage_user(current_user, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot manage users outside your assigned sites.",
        )

    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

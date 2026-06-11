from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
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


def _can_manage_user(current_user: UserResponse, target_user: models.User) -> bool:
    if current_user.is_global_admin:
        return True
    if str(target_user.id) == current_user.id:
        return True
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
    List all users. Admin users see every account regardless of scope;
    site-based access control is enforced on mutating endpoints (update/delete)
    to prevent cross-site modifications.
    """
    users = db.query(models.User).order_by(models.User.email).all()
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

    role = _role_value(payload.role)
    assigned_site_ids, is_global_admin = _normalized_scope(
        role, _site_ids(payload.assigned_site_ids), payload.is_global_admin
    )
    _validate_locations_exist(db, assigned_site_ids)
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
    _assert_can_assign_scope(
        current_user,
        role=role,
        assigned_site_ids=assigned_site_ids,
        is_global_admin=is_global_admin,
    )

    user.role = role
    if payload.status is not None:
        user.status = _role_value(payload.status)
    if payload.contact_number is not None:
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

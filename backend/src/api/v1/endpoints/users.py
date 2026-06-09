from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from src import models
from src.api.v1.deps import get_current_admin, to_user_response
from src.core.security import get_password_hash
from src.database import get_db
from src.schemas import UserCreate, UserResponse, UserRoleUpdate

router = APIRouter()


def _role_value(role: object) -> str:
    return str(getattr(role, "value", role))


@router.get("", response_model=list[UserResponse])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[UserResponse, Depends(get_current_admin)],
) -> list[UserResponse]:
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

    user = models.User(
        email=str(payload.email),
        full_name=payload.full_name,
        password_hash=get_password_hash(payload.password),
        role=_role_value(payload.role),
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

    user.role = _role_value(payload.role)
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

    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

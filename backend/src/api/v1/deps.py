from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src import models
from src.core.config import settings
from src.database import get_db
from src.schemas import TokenPayload, UserResponse
from starlette.status import HTTP_403_FORBIDDEN

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def to_user_response(user: models.User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        status=user.status,
        contact_number=user.contact_number,
        assigned_site_ids=list(user.assigned_site_ids or []),
        is_global_admin=bool(user.is_global_admin),
    )


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    """
    Decodes token and fetches user.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (jwt.PyJWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    if not token_data.sub:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="Token missing subject"
        )

    user = (
        db.query(models.User)
        .filter(models.User.email == token_data.sub)
        .one_or_none()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return to_user_response(user)


# RBAC Dependencies
def get_current_admin(
    current_user: Annotated[UserResponse, Depends(get_current_user)],
) -> UserResponse:
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=403, detail="Not enough permissions. Admin required."
        )
    return current_user


def user_has_global_read_access(current_user: UserResponse) -> bool:
    return current_user.role == "AI_Engineer" or (
        current_user.role == "Admin" and current_user.is_global_admin
    )


def user_can_access_site(current_user: UserResponse, site_id: str) -> bool:
    if user_has_global_read_access(current_user):
        return True
    return site_id in set(current_user.assigned_site_ids)


def get_current_operator(
    current_user: Annotated[UserResponse, Depends(get_current_user)],
) -> UserResponse:
    if current_user.role not in ["Admin", "Operator"]:
        raise HTTPException(
            status_code=403, detail="Not enough permissions. Operator required."
        )
    return current_user


def get_current_ai_engineer_or_admin(
    current_user: Annotated[UserResponse, Depends(get_current_user)],
) -> UserResponse:
    if current_user.role not in ["Admin", "AI_Engineer"]:
        raise HTTPException(
            status_code=403,
            detail="Not enough permissions. Admin or AI Engineer required.",
        )
    return current_user

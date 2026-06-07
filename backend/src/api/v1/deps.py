from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import ValidationError
from src.api.v1.endpoints.auth import MOCK_DB
from src.core.config import settings
from src.schemas import TokenPayload, UserResponse
from starlette.status import HTTP_403_FORBIDDEN

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> UserResponse:
    """
    Decodes token and fetches user.
    After the demo, just swap `MOCK_DB.get()` with `db.query(User).filter(...)`.
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

    # --- DEMO SPECIFIC LOGIC ---
    # TODO: Replace with real DB session injection and query
    user_data = MOCK_DB.get(token_data.sub)
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse(**user_data)


# RBAC Dependencies
def get_current_admin(
    current_user: Annotated[UserResponse, Depends(get_current_user)],
) -> UserResponse:
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=403, detail="Not enough permissions. Admin required."
        )
    return current_user


def get_current_operator(
    current_user: Annotated[UserResponse, Depends(get_current_user)],
) -> UserResponse:
    # Merging PO and Operator since they share the same features anyway
    # TODO: Either delete PO or update new feature for them
    if current_user.role not in ["Admin", "Operator", "PO"]:
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

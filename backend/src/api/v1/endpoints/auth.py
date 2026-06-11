from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from src import models
from src.api.v1.deps import get_current_user
from src.core.security import create_access_token, verify_password
from src.database import get_db
from src.schemas import Token, UserResponse

router = APIRouter()


@router.post("/login", response_model=Token)
def login_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
):
    """
    OAuth2 compatible token login, get an access token for future requests.
    """
    # OAuth2 spec uses `username` field, but we treat it as email.
    user = (
        db.query(models.User)
        .filter(models.User.email == form_data.username)
        .one_or_none()
    )

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password",
        )

    access_token = create_access_token(subject=user.email, role=user.role)
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
def read_current_user(
    current_user: Annotated[UserResponse, Depends(get_current_user)],
) -> UserResponse:
    return current_user

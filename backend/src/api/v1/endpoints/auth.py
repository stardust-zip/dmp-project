import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from src.core.security import create_access_token, get_password_hash, verify_password
from src.schemas import Token

router = APIRouter()

DEMO_PASSWORD_HASH = get_password_hash("demo123")

MOCK_DB = {
    "admin@dmp.com": {
        "id": str(uuid.uuid4()),
        "email": "admin@dmp.com",
        "full_name": "Demo Admin",
        "role": "Admin",
        "hashed_password": DEMO_PASSWORD_HASH,
    },
    "operator@dmp.com": {
        "id": str(uuid.uuid4()),
        "email": "operator@dmp.com",
        "full_name": "Demo Operator",
        "role": "Operator",
        "hashed_password": DEMO_PASSWORD_HASH,
    },
    "ai@dmp.com": {
        "id": str(uuid.uuid4()),
        "email": "ai@dmp.com",
        "full_name": "Demo AI Engineer",
        "role": "AI_Engineer",
        "hashed_password": DEMO_PASSWORD_HASH,
    },
}


@router.post("/login", response_model=Token)
def login_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """
    OAuth2 compatible token login, get an access token for future requests.
    After demo, inject DB session and query real users.
    """
    # OAuth2 spec uses `username` field, but we treat it as email.
    user_dict = MOCK_DB.get(form_data.username)

    if not user_dict or not verify_password(
        form_data.password, user_dict["hashed_password"]
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password",
        )

    access_token = create_access_token(
        subject=user_dict["email"], role=user_dict["role"]
    )
    return {"access_token": access_token, "token_type": "bearer"}

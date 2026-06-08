import argparse
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src import models
from src.core.security import get_password_hash
from src.database import SessionLocal, init_db


@dataclass(frozen=True)
class SeedUser:
    email: str
    full_name: str
    role: str


DEFAULT_USERS = (
    SeedUser(email="admin@dmp.com", full_name="Demo Admin", role="Admin"),
    SeedUser(email="operator@dmp.com", full_name="Demo Operator", role="Operator"),
    SeedUser(email="ai@dmp.com", full_name="Demo AI Engineer", role="AI_Engineer"),
)


def seed_default_users(
    db: Session,
    *,
    password: str = "demo123",
    reset_password: bool = False,
) -> dict[str, int]:
    """
    Creates or updates the default local/demo users.

    Existing users keep their password unless reset_password=True. This keeps
    the seeder safe to run repeatedly during container startup.
    """
    created = 0
    updated = 0
    password_hash = get_password_hash(password)

    for seed_user in DEFAULT_USERS:
        user = (
            db.query(models.User)
            .filter(models.User.email == seed_user.email)
            .one_or_none()
        )

        if user is None:
            db.add(
                models.User(
                    email=seed_user.email,
                    full_name=seed_user.full_name,
                    role=seed_user.role,
                    password_hash=password_hash,
                )
            )
            created += 1
            continue

        changed = False
        if user.full_name != seed_user.full_name:
            user.full_name = seed_user.full_name
            changed = True
        if user.role != seed_user.role:
            user.role = seed_user.role
            changed = True
        if reset_password:
            user.password_hash = password_hash
            changed = True

        if changed:
            updated += 1

    db.commit()
    return {"created": created, "updated": updated}


def run_user_seeder(
    *,
    password: str = "demo123",
    reset_password: bool = False,
) -> dict[str, int]:
    init_db()
    db = SessionLocal()
    try:
        return seed_default_users(
            db,
            password=password,
            reset_password=reset_password,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed default DMP users.")
    parser.add_argument(
        "--password",
        default="demo123",
        help="Password to use when creating default users.",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Reset passwords for existing default users.",
    )
    args = parser.parse_args()

    result = run_user_seeder(
        password=args.password,
        reset_password=args.reset_password,
    )
    print(
        "Default user seeding completed: "
        f"{result['created']} created, {result['updated']} updated."
    )

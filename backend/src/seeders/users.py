import argparse
from dataclasses import dataclass

from sqlalchemy.orm import Session
from src import models
from src.core.security import get_password_hash
from src.database import SessionLocal, init_db

# ──────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SeedUser:
    email: str
    full_name: str
    role: str
    status: str = "Off_Duty"
    contact_number: str | None = None
    assigned_site_ids: tuple[str, ...] = ()
    is_global_admin: bool = False


# ──────────────────────────────────────────────────────────────────────
# Demo site fallback definitions  (only used when DB has zero sites)
# ──────────────────────────────────────────────────────────────────────

_DEMO_SITE_FALLBACKS: tuple[tuple[str, str], ...] = (
    ("site-downtown", "Downtown Campus"),
    ("site-north", "North Facility"),
    ("site-east", "East Warehouse"),
    ("site-south", "South Office"),
    ("site-harbor", "Harbor District"),
)


def _create_demo_sites(db: Session) -> list[str]:
    """
    Create the canonical set of demo site locations.

    Only called when *zero* site-typed locations exist in the DB.
    Ensures the ``"site"`` location-type row exists first.
    """
    existing_lt = (
        db.query(models.LocationType)
        .filter(models.LocationType.id == "site")
        .one_or_none()
    )
    if existing_lt is None:
        db.add(models.LocationType(id="site", description="Top-level site or campus"))

    ids: list[str] = []
    for site_id, site_name in _DEMO_SITE_FALLBACKS:
        db.add(
            models.Location(
                id=site_id,
                name=site_name,
                location_type_id="site",
            )
        )
        ids.append(site_id)

    db.flush()
    return ids


# ──────────────────────────────────────────────────────────────────────
# Site resolution  (DB sites first → demo fallback if empty)
# ──────────────────────────────────────────────────────────────────────


def _resolve_site_ids(db: Session) -> list[str]:
    """
    Return site-level location IDs to use for demo user assignments.

    * If the DB already contains site locations, those IDs are used
      directly (up to 10, ordered by ID).
    * If no sites exist, a set of demo sites is created as a fallback
      so the seeder remains self-contained.
    """
    existing = (
        db.query(models.Location)
        .filter(models.Location.location_type_id == "site")
        .order_by(models.Location.id)
        .limit(10)
        .all()
    )
    if existing:
        return [loc.id for loc in existing]

    return _create_demo_sites(db)


# ──────────────────────────────────────────────────────────────────────
# Seed user definitions  (site-agnostic — indexes into resolved IDs)
# ──────────────────────────────────────────────────────────────────────


def _build_seed_users(site_ids: list[str]) -> tuple[SeedUser, ...]:
    """
    Build 25 demo users covering the full two-tier admin model.

    Site assignments use positional indexing into *site_ids* so that
    whatever sites exist in the DB (or were just created) are wired in
    automatically.  If fewer than 5 sites are available some users will
    receive fewer assignments — the seeder degrades gracefully.
    """

    def _s(index: int) -> str | None:
        """Return *site_ids[index]* or ``None`` if out of range."""
        return site_ids[index] if index < len(site_ids) else None

    def _id_tuple(*indices: int) -> tuple[str, ...]:
        """Build a sorted tuple of site IDs for the given indices."""
        return tuple(sorted(sid for i in indices if (sid := _s(i)) is not None))

    # Convenience aliases for readability
    S0 = _id_tuple(0)
    S1 = _id_tuple(1)
    S2 = _id_tuple(2)
    S3 = _id_tuple(3)
    S4 = _id_tuple(4)
    S01 = _id_tuple(0, 1)
    S02 = _id_tuple(0, 2)
    S03 = _id_tuple(0, 2, 3)
    S14 = _id_tuple(1, 4)
    S134 = _id_tuple(1, 3, 4)

    return (
        # ── Global Admins (2) ──────────────────────────────────────
        SeedUser(
            email="admin@dmp.com",
            full_name="Demo Admin",
            role="Admin",
            status="Available",
            contact_number="+1 555 100 0001",
            is_global_admin=True,
        ),
        SeedUser(
            email="sysadmin@dmp.com",
            full_name="Alex Rivera",
            role="Admin",
            status="Available",
            contact_number="+1 555 100 0002",
            is_global_admin=True,
        ),
        # ── Site Admins (6) — each scoped to different site(s) ─────
        SeedUser(
            email="schen@dmp.com",
            full_name="Sarah Chen",
            role="Admin",
            status="Available",
            contact_number="+1 555 200 0001",
            is_global_admin=False,
            assigned_site_ids=S01,
        ),
        SeedUser(
            email="mwebb@dmp.com",
            full_name="Marcus Webb",
            role="Admin",
            status="Available",
            contact_number="+1 555 200 0002",
            is_global_admin=False,
            assigned_site_ids=S2,
        ),
        SeedUser(
            email="druiz@dmp.com",
            full_name="Diana Ruiz",
            role="Admin",
            status="Busy",
            contact_number="+1 555 200 0003",
            is_global_admin=False,
            assigned_site_ids=S3,
        ),
        SeedUser(
            email="jcole@dmp.com",
            full_name="James Cole",
            role="Admin",
            status="In_Shift",
            contact_number="+1 555 200 0004",
            is_global_admin=False,
            assigned_site_ids=S03,
        ),
        SeedUser(
            email="nharris@dmp.com",
            full_name="Nia Harris",
            role="Admin",
            status="Available",
            contact_number="+1 555 200 0005",
            is_global_admin=False,
            assigned_site_ids=S14,
        ),
        SeedUser(
            email="siteadmin@dmp.com",
            full_name="Demo Site Admin",
            role="Admin",
            status="Available",
            is_global_admin=False,
            assigned_site_ids=S0,
        ),
        # ── Operators — site #0 (3) ────────────────────────────────
        SeedUser(
            email="op-dt-john@dmp.com",
            full_name="John Keller",
            role="Operator",
            status="Available",
            contact_number="+1 555 300 0001",
            assigned_site_ids=S0,
        ),
        SeedUser(
            email="op-dt-elena@dmp.com",
            full_name="Elena Voss",
            role="Operator",
            status="In_Shift",
            contact_number="+1 555 300 0002",
            assigned_site_ids=S0,
        ),
        SeedUser(
            email="op-dt-ravi@dmp.com",
            full_name="Ravi Patel",
            role="Operator",
            status="Busy",
            assigned_site_ids=S0,
        ),
        # ── Operators — site #1 (2) ────────────────────────────────
        SeedUser(
            email="op-north-mia@dmp.com",
            full_name="Mia Tanaka",
            role="Operator",
            status="In_Shift",
            contact_number="+1 555 300 0004",
            assigned_site_ids=S1,
        ),
        SeedUser(
            email="op-north-omar@dmp.com",
            full_name="Omar Fayed",
            role="Operator",
            status="Off_Duty",
            assigned_site_ids=S1,
        ),
        # ── Operators — site #2 (2) ────────────────────────────────
        SeedUser(
            email="op-east-liam@dmp.com",
            full_name="Liam O'Sullivan",
            role="Operator",
            status="Available",
            assigned_site_ids=S2,
        ),
        SeedUser(
            email="op-east-zara@dmp.com",
            full_name="Zara Khan",
            role="Operator",
            status="On_Break",
            contact_number="+1 555 300 0007",
            assigned_site_ids=S2,
        ),
        # ── Operators — site #3 (2) ────────────────────────────────
        SeedUser(
            email="op-south-chen@dmp.com",
            full_name="Wei Chen",
            role="Operator",
            status="Available",
            assigned_site_ids=S3,
        ),
        SeedUser(
            email="op-south-hieu@dmp.com",
            full_name="Nguyen Ngoc Hieu",
            role="Operator",
            status="On_Leave",
            contact_number="+1 555 300 8888",
            assigned_site_ids=S3,
        ),
        # ── Operators — multi-site (2) ─────────────────────────────
        SeedUser(
            email="op-multi-kai@dmp.com",
            full_name="Kai Nakamura",
            role="Operator",
            status="Available",
            contact_number="+1 555 300 0010",
            assigned_site_ids=S02,
        ),
        SeedUser(
            email="op-multi-fatima@dmp.com",
            full_name="Fatima Al-Rashid",
            role="Operator",
            status="In_Shift",
            assigned_site_ids=S134,
        ),
        # ── Operators — edge cases (2) ─────────────────────────────
        SeedUser(
            email="op-suspended@dmp.com",
            full_name="Tom Briggs",
            role="Operator",
            status="Suspended",
            assigned_site_ids=S2,
        ),
        SeedUser(
            email="op-new@dmp.com",
            full_name="New Hire",
            role="Operator",
            status="Off_Duty",
            # No sites — tests the "No sites assigned" scope column.
        ),
        # ── Operator (legacy demo email) ───────────────────────────
        SeedUser(
            email="operator@dmp.com",
            full_name="Demo Operator",
            role="Operator",
            status="Available",
            assigned_site_ids=S02,
        ),
        # ── AI Engineers (3) — global read-only ────────────────────
        SeedUser(
            email="ai@dmp.com",
            full_name="Demo AI Engineer",
            role="AI_Engineer",
            status="Available",
            contact_number="+1 555 400 0001",
        ),
        SeedUser(
            email="ai-le-tung@dmp.com",
            full_name="Le Van Tung",
            role="AI_Engineer",
            status="Available",
            contact_number="+1 555 400 0002",
        ),
        SeedUser(
            email="ai-nhat-minh@dmp.com",
            full_name="Tran Nhat Minh",
            role="AI_Engineer",
            status="Busy",
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# Core seeder logic
# ──────────────────────────────────────────────────────────────────────


def seed_default_users(
    db: Session,
    *,
    password: str = "demo123",
    reset_password: bool = False,
) -> dict[str, int]:
    """
    Creates or updates the full set of demo users (25).

    * Site assignments use **existing** site-level locations from the
      database.  Demo sites are only created when zero sites exist, so
      the seeder works against a fresh DB without overwriting real data.
    * Existing users keep their password unless ``reset_password=True``.
    * Site assignments are backfilled for users who currently have none.
      Manual assignments made through the UI are **never** overwritten.
    """
    site_ids = _resolve_site_ids(db)
    seed_users = _build_seed_users(site_ids)

    created = 0
    updated = 0
    password_hash = get_password_hash(password)

    for seed_user in seed_users:
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
                    status=seed_user.status,
                    contact_number=seed_user.contact_number,
                    assigned_site_ids=list(seed_user.assigned_site_ids),
                    is_global_admin=seed_user.is_global_admin,
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
        if user.status != seed_user.status:
            user.status = seed_user.status
            changed = True
        if user.contact_number != seed_user.contact_number:
            user.contact_number = seed_user.contact_number
            changed = True

        # Backfill site assignments only if the user has none.
        current_sites = user.assigned_site_ids or []
        if not current_sites:
            assigned = list(seed_user.assigned_site_ids)
            if assigned:
                user.assigned_site_ids = assigned
                changed = True

        if bool(user.is_global_admin) != seed_user.is_global_admin:
            user.is_global_admin = seed_user.is_global_admin
            changed = True
        if reset_password:
            user.password_hash = password_hash
            changed = True

        if changed:
            updated += 1

    db.commit()
    return {"created": created, "updated": updated}


# ──────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────


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

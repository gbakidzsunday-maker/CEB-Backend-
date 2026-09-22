"""
Startup seeding — automatically creates a default Administrator account
on a fresh database so there's always a way to log in, without needing
to hit the open /auth/admin/register endpoint by hand first.

Controlled by the SEED_ADMIN* settings in app.config. Safe to run on
every startup: it only inserts a row when no administrator with the
configured username/email exists yet, so it's a no-op on subsequent
restarts.
"""
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Administrator
from app.security import hash_password

logger = logging.getLogger("app.seed")


def seed_admin(db: Session) -> None:
    if not settings.SEED_ADMIN:
        return

    existing = (
        db.query(Administrator)
        .filter(
            (Administrator.username == settings.SEED_ADMIN_USERNAME)
            | (Administrator.email == settings.SEED_ADMIN_EMAIL)
        )
        .first()
    )
    if existing:
        # Already seeded (or an admin with that username/email was
        # created some other way) — nothing to do.
        return

    admin = Administrator(
        username=settings.SEED_ADMIN_USERNAME,
        email=settings.SEED_ADMIN_EMAIL,
        password_hash=hash_password(settings.SEED_ADMIN_PASSWORD),
    )
    db.add(admin)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with another worker process seeding at the same
        # time — that's fine, the admin now exists either way.
        db.rollback()
        return

    logger.warning(
        "Seeded default administrator account (username=%s). "
        "If SEED_ADMIN_PASSWORD was left at its default value, log in "
        "and change it (or set a real SEED_ADMIN_PASSWORD env var) "
        "before deploying to production.",
        settings.SEED_ADMIN_USERNAME,
    )

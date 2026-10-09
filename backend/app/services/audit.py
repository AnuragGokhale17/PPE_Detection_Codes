import logging

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.models import ActivityLog

log = logging.getLogger(__name__)


def client_ip(request: Request) -> str | None:
    # Behind nginx, run uvicorn with --proxy-headers so request.client is the real client
    return request.client.host if request.client else None


def log_activity(
    db: Session,
    request: Request,
    action: str,
    user_id: int | None = None,
    user_email: str | None = None,
    details: str | None = None,
) -> None:
    """Writes to the same activity_logs table the Flask admin panel reads.
    Commits on its own so audit rows survive a later rollback."""
    try:
        db.add(
            ActivityLog(
                user_id=user_id,
                user_email=user_email,
                action=action,
                details=details,
                ip_address=client_ip(request),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Failed to write activity log '%s'", action)

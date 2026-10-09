"""Request dependencies: current user from the session cookie, permission checks."""
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.permissions import Permission, effective_permissions
from app.core.security import create_token, decode_token, password_fingerprint, utcnow
from app.db.models import User
from app.db.session import get_db


@dataclass
class CurrentUser:
    user: User
    permissions: set[str]

    @property
    def id(self) -> int:
        return self.user.id

    @property
    def email(self) -> str:
        return self.user.email

    @property
    def is_admin(self) -> bool:
        return self.user.role == "admin"

    def has(self, permission: Permission) -> bool:
        return permission.value in self.permissions


def set_session_cookie(response: Response, user: User, auth_time: int) -> None:
    settings = get_settings()
    ttl = timedelta(minutes=settings.session_idle_minutes)
    token = create_token(
        "session",
        str(user.id),
        ttl,
        pv=password_fingerprint(user.password_hash),
        auth=auth_time,
    )
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.session_cookie, path="/")


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail)


def get_current_user(
    request: Request, response: Response, db: Session = Depends(get_db)
) -> CurrentUser:
    settings = get_settings()
    claims = decode_token(request.cookies.get(settings.session_cookie), "session")
    if not claims:
        raise _unauthorized()

    auth_time = int(claims.get("auth", 0))
    if utcnow().timestamp() - auth_time > settings.session_max_hours * 3600:
        raise _unauthorized("Session expired")

    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise _unauthorized()
    # Password changed (or reset) since this session started
    if claims.get("pv") != password_fingerprint(user.password_hash):
        raise _unauthorized("Session expired")

    # Sliding idle timeout: every authenticated request extends the session
    set_session_cookie(response, user, auth_time)
    return CurrentUser(user=user, permissions=effective_permissions(user.role, user.granted_permissions))


def require(*permissions: Permission):
    """Dependency factory: the current user must hold every listed permission."""

    def checker(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        missing = [p.value for p in permissions if not current.has(p)]
        if missing:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {', '.join(missing)}"
            )
        return current

    return checker

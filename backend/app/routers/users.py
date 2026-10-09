"""User administration: accounts, permission grants and the audit log."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, require
from app.core.permissions import (
    DEFAULT_PERMISSIONS,
    GRANTABLE_PERMISSIONS,
    PERMISSION_INFO,
    Permission,
    effective_permissions,
)
from app.db.models import ActivityLog, User, UserPermission
from app.db.session import get_db
from app.schemas.users import (
    AuditLogPage,
    PermissionInfo,
    PermissionsUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services import accounts
from app.services.audit import log_activity

router = APIRouter(tags=["users"])
admin_only = require(Permission.USERS_MANAGE)


def _user_out(user: User) -> UserOut:
    granted = user.granted_permissions
    return UserOut(
        id=user.id,
        email=user.email,
        name=accounts.display_name(user.email),
        role=user.role,
        is_active=bool(user.is_active),
        locked=accounts.lockout_minutes_left(user) is not None,
        password_expired=accounts.is_password_expired(user),
        granted=sorted(granted),
        effective=sorted(effective_permissions(user.role, granted)),
    )


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def _validate_grants(permissions: list[str]) -> set[str]:
    allowed = {p.value for p in GRANTABLE_PERMISSIONS}
    unknown = set(permissions) - allowed
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Not grantable: {', '.join(sorted(unknown))}",
        )
    # Default permissions are implicit; storing them would only add noise
    return set(permissions) - {p.value for p in DEFAULT_PERMISSIONS}


def _set_grants(db: Session, user: User, permissions: set[str], granted_by: int) -> None:
    current = {p.permission: p for p in user.permissions}
    for key in set(current) - permissions:
        user.permissions.remove(current[key])
    for key in permissions - set(current):
        user.permissions.append(UserPermission(permission=key, granted_by=granted_by))


@router.get("/permissions", response_model=list[PermissionInfo])
def list_permissions(_: CurrentUser = Depends(admin_only)):
    return [
        PermissionInfo(
            key=p.value,
            label=info["label"],
            description=info["description"],
            grantable=info["grantable"],
            default=p in DEFAULT_PERMISSIONS,
        )
        for p, info in PERMISSION_INFO.items()
    ]


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: CurrentUser = Depends(admin_only)):
    users = db.scalars(select(User).order_by(User.id)).all()
    return [_user_out(u) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(admin_only),
):
    grants = _validate_grants(body.permissions)
    user, error = accounts.create_user(db, body.email, body.password, body.role)
    if error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=error)
    if grants and body.role != "admin":
        _set_grants(db, user, grants, current.id)
        db.commit()
    log_activity(db, request, "Add User", current.id, current.email, f"Added user {user.email} ({body.role})")
    return _user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(admin_only),
):
    user = _get_user(db, user_id)
    if user.id == current.id and (body.is_active is False or body.role == "user"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate or demote your own account."
        )
    changes = []
    if body.role is not None and body.role != user.role:
        changes.append(f"role {user.role} -> {body.role}")
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        changes.append("activated" if body.is_active else "deactivated")
        user.is_active = body.is_active
    db.commit()
    if changes:
        log_activity(db, request, "Update User", current.id, current.email, f"{user.email}: {', '.join(changes)}")
    return _user_out(user)


@router.put("/users/{user_id}/permissions", response_model=UserOut)
def update_permissions(
    user_id: int,
    body: PermissionsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(admin_only),
):
    user = _get_user(db, user_id)
    grants = _validate_grants(body.permissions)
    before = user.granted_permissions
    _set_grants(db, user, grants, current.id)
    db.commit()
    added, removed = grants - before, before - grants
    if added or removed:
        parts = [f"+{p}" for p in sorted(added)] + [f"-{p}" for p in sorted(removed)]
        log_activity(db, request, "Update Permissions", current.id, current.email, f"{user.email}: {' '.join(parts)}")
    return _user_out(user)


@router.post("/users/{user_id}/unlock", response_model=UserOut)
def unlock_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(admin_only),
):
    user = _get_user(db, user_id)
    accounts.clear_failed_logins(db, user)
    log_activity(db, request, "Unlock User", current.id, current.email, f"Unlocked {user.email}")
    return _user_out(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(admin_only),
):
    user = _get_user(db, user_id)
    if user.id == current.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account.")
    email = user.email
    try:
        accounts.delete_user(db, user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This user is referenced by other records. Deactivate the account instead.",
        )
    log_activity(db, request, "Delete User", current.id, current.email, f"Deleted user {email}")


@router.get("/audit-logs", response_model=AuditLogPage)
def audit_logs(
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(admin_only),
):
    stmt = select(ActivityLog)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                ActivityLog.user_email.ilike(like),
                ActivityLog.action.ilike(like),
                ActivityLog.details.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ActivityLog.timestamp.desc()).limit(limit).offset(offset)).all()
    return AuditLogPage(items=rows, total=total or 0)

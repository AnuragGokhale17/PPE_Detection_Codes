"""Account rules: lockout, password expiry/history, OTP lifecycle, user creation."""
import math
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    as_utc,
    check_password_policy,
    generate_otp,
    hash_otp,
    hash_password,
    otp_matches,
    utcnow,
    verify_password,
)
from app.db.models import AuthOtp, LegacyOtp, PasswordHistory, User, UserPermission


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))


def display_name(email: str) -> str:
    """first.last@solargroup.com -> First Last (same as the Flask extract_name)."""
    local = email.split("@")[0]
    return " ".join(part.capitalize() for part in local.replace("_", ".").split(".") if part)


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'•' * max(len(local) - len(visible), 3)}@{domain}"


# --- Lockout -------------------------------------------------------------------

def lockout_minutes_left(user: User) -> int | None:
    locked_until = as_utc(user.locked_until)
    if locked_until and utcnow() < locked_until:
        return max(1, math.ceil((locked_until - utcnow()).total_seconds() / 60))
    return None


def register_failed_login(db: Session, user: User) -> None:
    settings = get_settings()
    user.failed_attempts = (user.failed_attempts or 0) + 1
    if user.failed_attempts >= settings.max_failed_attempts:
        user.locked_until = utcnow() + timedelta(minutes=settings.lockout_minutes)
    db.commit()


def clear_failed_logins(db: Session, user: User) -> None:
    if user.failed_attempts or user.locked_until:
        user.failed_attempts = 0
        user.locked_until = None
        db.commit()


def is_password_expired(user: User) -> bool:
    updated_at = as_utc(user.password_updated_at)
    if updated_at is None:
        return True
    return utcnow() > updated_at + timedelta(days=get_settings().password_expiry_days)


# --- Passwords -----------------------------------------------------------------

def _is_reused(db: Session, user: User, password: str) -> bool:
    limit = get_settings().password_history_limit
    recent = db.scalars(
        select(PasswordHistory.password_hash)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(limit)
    ).all()
    return any(verify_password(password, h) for h in recent)


def change_password(db: Session, user: User, new_password: str) -> str | None:
    """Applies policy + history checks. Returns an error message or None on success."""
    error = check_password_policy(new_password)
    if error:
        return error
    if _is_reused(db, user, new_password):
        limit = get_settings().password_history_limit
        return f"You cannot reuse any of your last {limit} passwords."

    now = utcnow()
    new_hash = hash_password(new_password)
    user.password_hash = new_hash
    user.password_updated_at = now
    user.failed_attempts = 0
    user.locked_until = None
    db.add(PasswordHistory(user_id=user.id, password_hash=new_hash, created_at=now))
    db.commit()
    return None


def create_user(db: Session, email: str, password: str, role: str) -> tuple[User | None, str | None]:
    settings = get_settings()
    email = normalize_email(email)
    if not email.endswith("@" + settings.allowed_email_domain):
        return None, f"Email must be an @{settings.allowed_email_domain} address."
    error = check_password_policy(password)
    if error:
        return None, error
    if get_user_by_email(db, email):
        return None, "A user with this email already exists."

    now = utcnow()
    password_hash = hash_password(password)
    user = User(
        email=email,
        password_hash=password_hash,
        role=role,
        is_active=True,
        password_updated_at=now,
        failed_attempts=0,
    )
    db.add(user)
    db.flush()
    db.add(PasswordHistory(user_id=user.id, password_hash=password_hash, created_at=now))
    db.commit()
    return user, None


def delete_user(db: Session, user: User) -> None:
    """Removes the user's dependent rows the same way the Flask admin panel did."""
    db.execute(delete(UserPermission).where(UserPermission.user_id == user.id))
    db.execute(delete(AuthOtp).where(AuthOtp.user_id == user.id))
    db.execute(delete(LegacyOtp).where(LegacyOtp.user_id == user.id))
    db.execute(delete(PasswordHistory).where(PasswordHistory.user_id == user.id))
    db.delete(user)
    db.commit()


# --- OTPs ----------------------------------------------------------------------

def issue_otp(db: Session, user: User) -> str:
    settings = get_settings()
    code = generate_otp()
    now = utcnow()
    row = db.get(AuthOtp, user.id)
    if row is None:
        row = AuthOtp(user_id=user.id)
        db.add(row)
    row.code_hash = hash_otp(user.id, code)
    row.attempts = 0
    row.created_at = now
    row.expires_at = now + timedelta(minutes=settings.otp_ttl_minutes)
    db.commit()
    return code


def seconds_until_resend(db: Session, user: User) -> int:
    row = db.get(AuthOtp, user.id)
    if row is None:
        return 0
    elapsed = (utcnow() - as_utc(row.created_at)).total_seconds()
    return max(0, math.ceil(get_settings().otp_resend_seconds - elapsed))


def check_otp(db: Session, user: User, code: str) -> tuple[bool, str]:
    settings = get_settings()
    row = db.get(AuthOtp, user.id)
    if row is None or utcnow() >= as_utc(row.expires_at):
        return False, "Your code is invalid or has expired. Request a new one."
    if not otp_matches(user.id, code, row.code_hash):
        row.attempts += 1
        left = settings.otp_max_attempts - row.attempts
        if left <= 0:
            db.delete(row)
            db.commit()
            return False, "Too many incorrect attempts. Sign in again to get a new code."
        db.commit()
        return False, f"Incorrect code. {left} attempt{'s' if left != 1 else ''} left."
    db.delete(row)
    db.commit()
    return True, "ok"

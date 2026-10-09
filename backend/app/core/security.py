"""Password hashing, password policy, OTPs and signed tokens."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

# bcrypt only looks at the first 72 bytes; longer inputs are rejected by the policy
BCRYPT_MAX_BYTES = 72
_SPECIAL_CHARS = r"[!@#$%^&*(),.?:{}|<>]"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Legacy columns may hold naive timestamps; treat them as UTC like auth.py did."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


# --- Passwords -----------------------------------------------------------------

def hash_password(password: str) -> str:
    # Same $2b$ format passlib produced for the existing users table
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password or not password_hash:
        return False
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("ascii"))
    except ValueError:
        return False


# A real hash to compare against when the email is unknown, so response time
# does not reveal whether an account exists.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def burn_password_check(password: str) -> None:
    verify_password(password or "x", _DUMMY_HASH)


def check_password_policy(password: str) -> str | None:
    """Returns an error message, or None when the password satisfies the policy."""
    if len(password) < 14:
        return "Password must be at least 14 characters long."
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        return f"Password must be at most {BCRYPT_MAX_BYTES} bytes long."
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter."
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter."
    if not re.search(r"\d", password):
        return "Password must contain at least one number."
    if not re.search(_SPECIAL_CHARS, password):
        return "Password must contain at least one special character."
    return None


def password_fingerprint(password_hash: str) -> str:
    """Short keyed digest of the stored hash. Embedded in session and reset tokens
    so that changing the password invalidates both."""
    key = get_settings().secret_key.encode("utf-8")
    return hmac.new(key, password_hash.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


# --- OTPs ----------------------------------------------------------------------

def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(user_id: int, code: str) -> str:
    key = get_settings().secret_key.encode("utf-8")
    return hmac.new(key, f"{user_id}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def otp_matches(user_id: int, code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(user_id, code), code_hash)


# --- Signed tokens -------------------------------------------------------------

def create_token(kind: str, subject: str, ttl: timedelta, **claims: Any) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "typ": kind,
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        **claims,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str | None, kind: str) -> dict[str, Any] | None:
    if not token:
        return None
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != kind:
        return None
    return payload

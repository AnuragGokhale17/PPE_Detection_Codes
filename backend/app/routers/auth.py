"""Sign-in flow: password -> emailed OTP -> session cookie; password reset by email link."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import CurrentUser, clear_session_cookie, get_current_user, set_session_cookie
from app.core.permissions import effective_permissions
from app.core.security import (
    burn_password_check,
    create_token,
    decode_token,
    password_fingerprint,
    utcnow,
    verify_password,
)
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    Me,
    MessageResponse,
    OtpRequest,
    ResendResponse,
    ResetPasswordRequest,
    ResetTokenInfo,
)
from app.services import accounts
from app.services.audit import log_activity
from app.services.mailer import send_otp_email, send_password_reset_email

router = APIRouter(prefix="/auth", tags=["auth"])

OTP_COOKIE_PATH = "/api/auth"
INVALID_CREDENTIALS = "Invalid email or password."


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, detail={"code": code, "message": message})


def _set_otp_cookie(response: Response, user: User) -> None:
    settings = get_settings()
    ttl = timedelta(minutes=settings.otp_ttl_minutes)
    token = create_token("otp", str(user.id), ttl, pv=password_fingerprint(user.password_hash))
    response.set_cookie(
        settings.otp_cookie,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=OTP_COOKIE_PATH,
    )


def _pending_user(request: Request, db: Session) -> User:
    """The user who passed the password step and is now waiting on their OTP."""
    settings = get_settings()
    claims = decode_token(request.cookies.get(settings.otp_cookie), "otp")
    user = db.get(User, int(claims["sub"])) if claims else None
    if (
        user is None
        or not user.is_active
        or claims.get("pv") != password_fingerprint(user.password_hash)
    ):
        raise _error(401, "otp_session_expired", "Your sign-in session expired. Sign in again.")
    return user


def _me(current: CurrentUser) -> Me:
    return Me(
        id=current.user.id,
        email=current.user.email,
        name=accounts.display_name(current.user.email),
        role=current.user.role,
        permissions=sorted(current.permissions),
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    user = accounts.get_user_by_email(db, body.email)
    if user is None:
        burn_password_check(body.password)
        raise _error(401, "invalid_credentials", INVALID_CREDENTIALS)

    minutes_left = accounts.lockout_minutes_left(user)
    if minutes_left:
        raise _error(423, "locked", f"Account locked. Try again in {minutes_left} minutes.")
    if not user.is_active:
        raise _error(403, "inactive", "Account is inactive. Contact an administrator.")

    if not verify_password(body.password, user.password_hash):
        accounts.register_failed_login(db, user)
        log_activity(db, request, "Login Failed", user.id, user.email, "Incorrect password")
        raise _error(401, "invalid_credentials", INVALID_CREDENTIALS)

    accounts.clear_failed_logins(db, user)

    if accounts.is_password_expired(user):
        raise _error(
            403,
            "password_expired",
            f"Your password has expired ({settings.password_expiry_days}-day policy). Reset it to continue.",
        )

    code = accounts.issue_otp(db, user)
    if not send_otp_email(user.email, code, settings.otp_ttl_minutes):
        raise _error(502, "email_failed", "Could not send the sign-in code. Try again shortly.")

    _set_otp_cookie(response, user)
    return LoginResponse(
        email_hint=accounts.mask_email(user.email),
        resend_in=settings.otp_resend_seconds,
    )


@router.post("/resend-otp", response_model=ResendResponse)
def resend_otp(request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    user = _pending_user(request, db)
    wait = accounts.seconds_until_resend(db, user)
    if wait > 0:
        raise _error(429, "too_soon", f"Wait {wait} seconds before requesting another code.")

    code = accounts.issue_otp(db, user)
    if not send_otp_email(user.email, code, settings.otp_ttl_minutes):
        raise _error(502, "email_failed", "Could not send the sign-in code. Try again shortly.")
    _set_otp_cookie(response, user)
    return ResendResponse(resend_in=settings.otp_resend_seconds)


@router.post("/verify-otp", response_model=Me)
def verify_otp(body: OtpRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    user = _pending_user(request, db)
    ok, message = accounts.check_otp(db, user, body.otp)
    if not ok:
        raise _error(400, "otp_invalid", message)

    set_session_cookie(response, user, auth_time=int(utcnow().timestamp()))
    response.delete_cookie(settings.otp_cookie, path=OTP_COOKIE_PATH)
    log_activity(db, request, "Login Success", user.id, user.email, "User logged in via OTP")
    return _me(CurrentUser(user, effective_permissions(user.role, user.granted_permissions)))


@router.post("/logout", response_model=MessageResponse)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    claims = decode_token(request.cookies.get(settings.session_cookie), "session")
    if claims:
        user = db.get(User, int(claims["sub"]))
        if user:
            log_activity(db, request, "Logout", user.id, user.email, "User logged out")
    clear_session_cookie(response)
    return MessageResponse(message="You have been signed out.")


@router.get("/me", response_model=Me)
def me(current: CurrentUser = Depends(get_current_user)):
    return _me(current)


# --- Password reset -----------------------------------------------------------

FORGOT_MESSAGE = "If an account exists for that email, we have sent a password reset link."


def _user_from_reset_token(db: Session, token: str) -> User | None:
    claims = decode_token(token, "reset")
    if not claims:
        return None
    user = db.get(User, int(claims["sub"]))
    # pv binds the token to the current password, so a used link stops working
    if user is None or not user.is_active or claims.get("pv") != password_fingerprint(user.password_hash):
        return None
    return user


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(body: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    user = accounts.get_user_by_email(db, body.email)
    if user and user.is_active:
        token = create_token(
            "reset",
            str(user.id),
            timedelta(minutes=settings.reset_token_ttl_minutes),
            pv=password_fingerprint(user.password_hash),
        )
        link = f"{settings.app_base_url.rstrip('/')}/reset-password/{token}"
        sent = send_password_reset_email(user.email, link, settings.reset_token_ttl_minutes)
        log_activity(
            db,
            request,
            "Password Reset Request",
            user.id,
            user.email,
            "Reset link sent via email" if sent else "Reset email failed to send",
        )
    else:
        burn_password_check("x")
    # Same answer whether or not the account exists
    return MessageResponse(message=FORGOT_MESSAGE)


@router.get("/reset-password/{token}", response_model=ResetTokenInfo)
def reset_token_info(token: str, db: Session = Depends(get_db)):
    user = _user_from_reset_token(db, token)
    if user is None:
        return ResetTokenInfo(valid=False)
    return ResetTokenInfo(valid=True, email_hint=accounts.mask_email(user.email))


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(body: ResetPasswordRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _user_from_reset_token(db, body.token)
    if user is None:
        raise _error(400, "token_invalid", "The reset link is invalid or has expired.")
    if body.password != body.confirm_password:
        raise _error(400, "mismatch", "Passwords do not match.")

    error = accounts.change_password(db, user, body.password)
    if error:
        raise _error(400, "policy", error)

    clear_session_cookie(response)
    log_activity(db, request, "Password Reset Success", user.id, user.email, "Password updated")
    return MessageResponse(message="Password updated. Sign in with your new password.")

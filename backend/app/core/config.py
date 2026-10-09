"""Application settings.

Variable names match the existing `.env` used by app.py / inference.py / cooldown.py,
so one `.env` at the repository root serves the legacy services and the new API.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Later files win: backend/.env overrides the shared repo-root .env
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    # --- Database ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_pass: str = ""
    db_name: str = "ppes"
    # Full SQLAlchemy URL; overrides the DB_* parts when set (tests use sqlite)
    database_url: str | None = None

    # --- Sessions & tokens ---
    secret_key: str
    jwt_algorithm: str = "HS256"
    session_idle_minutes: int = 10
    session_max_hours: int = 12
    otp_ttl_minutes: int = 5
    otp_max_attempts: int = 5
    otp_resend_seconds: int = 60
    reset_token_ttl_minutes: int = 30
    session_cookie: str = "ppe_session"
    otp_cookie: str = "ppe_otp"
    cookie_secure: bool = True

    # --- Account policy (same rules as the Flask app) ---
    allowed_email_domain: str = "solargroup.com"
    max_failed_attempts: int = 3
    lockout_minutes: int = 30
    password_expiry_days: int = 30
    password_history_limit: int = 5

    # --- Email ---
    smtp_server: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    mail_use_tls: bool = True
    mail_sender_name: str = "PPE Safety Portal"
    # Dev only: print OTPs and reset links to the API log when SMTP is not configured
    dev_print_emails: bool = False

    # Public URL of the Next.js frontend (used in password-reset links)
    app_base_url: str = "http://localhost:3000"

    # --- Object storage (MinIO) ---
    bucket_name: str = "mybucket"
    internal_s3_endpoint_url: str = "https://127.0.0.1:9000"
    s3_endpoint_url: str = "https://ppes-siil.solargroup.com:9000"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    s3_verify_tls: bool = False
    # Used instead of MinIO when no S3 credentials are configured (dev, tests).
    # Same layout the workers use: object key a/b.jpg -> <dir>/a/b.jpg
    local_storage_dir: Path = REPO_DIR / "var" / "storage"

    # --- Uploads, snapshots, model-assisted labelling ---
    max_upload_mb: int = 20
    snapshot_timeout_seconds: int = 12
    prelabel_device: str = "cpu"
    prelabel_conf: float = 0.25
    # Where model_versions.weights_path is resolved from (the GPU server's checkout)
    models_root: Path = REPO_DIR
    @property
    def sqlalchemy_url(self) -> str | URL:
        if self.database_url:
            return self.database_url
        # URL.create takes the raw password, so DB_PASS_ENC is not needed here
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_pass,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_server and self.smtp_username and self.smtp_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()

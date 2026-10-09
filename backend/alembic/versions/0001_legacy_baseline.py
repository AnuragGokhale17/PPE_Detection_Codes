"""Legacy schema used by app.py / auth.py / inference.py / cooldown.py

Only for creating a fresh development database. The production database already
has these tables, so mark it as being at this revision instead of running it:

    alembic stamp 0001_legacy
    alembic upgrade head

Revision ID: 0001_legacy
Revises:
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_legacy"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("_password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("password_updated_at", sa.DateTime(timezone=True)),
        sa.Column("failed_attempts", sa.Integer, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "password_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("_password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "otps",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("otp_code", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "activity_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer),
        sa.Column("user_email", sa.String(255)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("details", sa.Text),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ppes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("class1", sa.Text),
        sa.Column("production_house", sa.Text),
        sa.Column("camera_unit", sa.Text),
        sa.Column("date1", sa.Date),
        sa.Column("time1", sa.Time),
        sa.Column("image_url", sa.Text),
        sa.Column("area", sa.Text),
        sa.Column("camera_status", sa.Boolean, server_default=sa.true()),
        sa.Column("violation", sa.Boolean, server_default=sa.true()),
        sa.Column("violations", sa.Text),
        sa.Column("compliance", sa.Text),
        sa.Column("violation_count", sa.Integer, server_default="0"),
        sa.Column("compliance_count", sa.Integer, server_default="0"),
        sa.Column("people_count", sa.Integer, server_default="0"),
        sa.Column("violator_count", sa.Integer, server_default="0"),
        sa.Column("required_ppes", sa.Text),
    )
    op.create_table(
        "camera_health",
        sa.Column("camera_id", sa.Text, primary_key=True),
        sa.Column("plant", sa.Text),
        sa.Column("production_house", sa.Text),
        sa.Column("area", sa.Text),
        sa.Column("rtsp_link", sa.Text),
        sa.Column("status", sa.Boolean),
        sa.Column("last_checked", sa.DateTime),
    )
    op.create_table(
        "ppes_emails_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("class_label", sa.Text),
        sa.Column("production_house", sa.Text),
        sa.Column("area", sa.Text),
        sa.Column("to_recipients", sa.Text),
        sa.Column("cc_recipients", sa.Text),
        sa.Column("insert_date", sa.Date),
        sa.Column("insert_time", sa.Time),
    )


def downgrade() -> None:
    for table in (
        "ppes_emails_records",
        "camera_health",
        "ppes",
        "activity_logs",
        "otps",
        "password_history",
        "users",
    ):
        op.drop_table(table)

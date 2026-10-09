"""Per-user permissions and hashed OTPs (additive; legacy tables untouched)

Revision ID: 0002_permissions
Revises: 0001_legacy
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_permissions"
down_revision = "0001_legacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_permissions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("permission", sa.String(64), nullable=False),
        sa.Column("granted_by", sa.Integer),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "permission", name="uq_user_permission"),
    )
    op.create_table(
        "auth_otps",
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("auth_otps")
    op.drop_table("user_permissions")

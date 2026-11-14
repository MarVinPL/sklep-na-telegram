"""Add persistent Passkey rate-limit buckets.

Revision ID: 20261112_0002
Revises: 20261112_0001
"""

import sqlalchemy as sa

from alembic import op

revision = "20261112_0002"
down_revision = "20261112_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_rate_limits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bucket_key", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("bucket_key", name="uq_auth_rate_limits_bucket_key"),
    )
    op.create_index(
        "ix_auth_rate_limits_window_start", "auth_rate_limits", ["window_start"]
    )


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limits_window_start", table_name="auth_rate_limits")
    op.drop_table("auth_rate_limits")

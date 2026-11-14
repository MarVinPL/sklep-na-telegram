"""Add short-lived, one-time Passkey handoff tickets.

Revision ID: 20261112_0003
Revises: 20261112_0002
"""

import sqlalchemy as sa

from alembic import op

revision = "20261112_0003"
down_revision = "20261112_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passkey_handoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_passkey_handoffs_user_id", "passkey_handoffs", ["user_id"])
    op.create_index(
        "ix_passkey_handoffs_token_hash", "passkey_handoffs", ["token_hash"], unique=True
    )
    op.create_index("ix_passkey_handoffs_expires_at", "passkey_handoffs", ["expires_at"])


def downgrade() -> None:
    op.drop_table("passkey_handoffs")

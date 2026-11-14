"""Add encrypted independent recovery contacts.

Revision ID: 20261114_0004
Revises: 20261112_0003
"""

import sqlalchemy as sa

from alembic import op

revision = "20261114_0004"
down_revision = "20261112_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_contacts",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("encrypted_email", sa.LargeBinary(), nullable=False),
        sa.Column("email_digest", sa.String(length=64), nullable=False),
        sa.Column("verification_token_hash", sa.String(length=64), nullable=True),
        sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("email_digest", name="uq_recovery_contacts_email_digest"),
    )
    op.create_index(
        "ix_recovery_contacts_verification_expires_at",
        "recovery_contacts",
        ["verification_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_recovery_contacts_verification_expires_at", table_name="recovery_contacts")
    op.drop_table("recovery_contacts")

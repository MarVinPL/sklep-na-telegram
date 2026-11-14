"""Add an independent verification attestation for recovery contacts.

Revision ID: 20261114_0007
Revises: 20261114_0006
"""

import sqlalchemy as sa

from alembic import op

revision = "20261114_0007"
down_revision = "20261114_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recovery_contacts", sa.Column("independence_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("recovery_contacts", sa.Column("independence_verifier_user_id", sa.Integer(), nullable=True))
    op.add_column("recovery_contacts", sa.Column("independence_method", sa.String(length=32), nullable=True))
    op.add_column("recovery_contacts", sa.Column("independence_audit_ref", sa.String(length=128), nullable=True))
    op.add_column("recovery_contacts", sa.Column("independence_revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("recovery_contacts", sa.Column("independence_revocation_reason", sa.String(length=500), nullable=True))
    op.create_foreign_key(
        "fk_recovery_contacts_independence_verifier",
        "recovery_contacts",
        "users",
        ["independence_verifier_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_recovery_contacts_independence_verifier", "recovery_contacts", type_="foreignkey")
    op.drop_column("recovery_contacts", "independence_revocation_reason")
    op.drop_column("recovery_contacts", "independence_revoked_at")
    op.drop_column("recovery_contacts", "independence_audit_ref")
    op.drop_column("recovery_contacts", "independence_method")
    op.drop_column("recovery_contacts", "independence_verifier_user_id")
    op.drop_column("recovery_contacts", "independence_verified_at")

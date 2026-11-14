"""Add separate security-operator RBAC and audited two-person changes.

Revision ID: 20261114_0005
Revises: 20261114_0004
"""

import sqlalchemy as sa

from alembic import op

revision = "20261114_0005"
down_revision = "20261114_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_operators",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("granted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("grant_reason", sa.Text(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "operator_change_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operator_change_requests_target_user_id", "operator_change_requests", ["target_user_id"])
    op.create_index("ix_operator_change_requests_status", "operator_change_requests", ["status"])
    op.create_index("ix_operator_change_requests_expires_at", "operator_change_requests", ["expires_at"])
    op.create_table(
        "operator_change_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("approver_user_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["operator_change_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "approver_user_id", name="uq_operator_change_approval"),
    )
    op.create_index("ix_operator_change_approvals_request_id", "operator_change_approvals", ["request_id"])
    op.create_table(
        "recovery_operator_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("recovery_user_id", sa.Integer(), nullable=False),
        sa.Column("operator_user_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recovery_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["operator_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "operator_user_id", name="uq_recovery_case_operator_decision"),
    )
    op.create_index("ix_recovery_operator_decisions_case_id", "recovery_operator_decisions", ["case_id"])
    op.create_index("ix_recovery_operator_decisions_recovery_user_id", "recovery_operator_decisions", ["recovery_user_id"])


def downgrade() -> None:
    op.drop_index("ix_recovery_operator_decisions_recovery_user_id", table_name="recovery_operator_decisions")
    op.drop_index("ix_recovery_operator_decisions_case_id", table_name="recovery_operator_decisions")
    op.drop_table("recovery_operator_decisions")
    op.drop_index("ix_operator_change_approvals_request_id", table_name="operator_change_approvals")
    op.drop_table("operator_change_approvals")
    op.drop_index("ix_operator_change_requests_expires_at", table_name="operator_change_requests")
    op.drop_index("ix_operator_change_requests_status", table_name="operator_change_requests")
    op.drop_index("ix_operator_change_requests_target_user_id", table_name="operator_change_requests")
    op.drop_table("operator_change_requests")
    op.drop_table("security_operators")

"""Add recovery cases and durable notification outbox.

Revision ID: 20261114_0006
Revises: 20261114_0005
"""

import sqlalchemy as sa

from alembic import op

revision = "20261114_0006"
down_revision = "20261114_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("contact_approval_token_hash", sa.String(length=64), nullable=True),
        sa.Column("contact_approval_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contact_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("veto_token_hash", sa.String(length=64), nullable=True),
        sa.Column("veto_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vetoed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("veto_reason", sa.Text(), nullable=True),
        sa.Column("operator_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recovery_cases_user_id", "recovery_cases", ["user_id"])
    op.create_index("ix_recovery_cases_status", "recovery_cases", ["status"])
    op.create_index("ix_recovery_cases_hold_ends_at", "recovery_cases", ["hold_ends_at"])

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("event_key", "channel", name="uq_notification_event_channel"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_outbox_status_next", "notification_outbox", ["status", "next_attempt_at"])
    op.create_index("ix_notification_outbox_user_id", "notification_outbox", ["user_id"])

    op.create_table(
        "notification_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outbox_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["outbox_id"], ["notification_outbox.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbox_id", "attempt_number", name="uq_notification_attempt_number"),
    )
    op.create_index("ix_notification_attempts_outbox_id", "notification_attempts", ["outbox_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_attempts_outbox_id", table_name="notification_attempts")
    op.drop_table("notification_attempts")
    op.drop_index("ix_notification_outbox_user_id", table_name="notification_outbox")
    op.drop_index("ix_notification_outbox_status_next", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_index("ix_recovery_cases_hold_ends_at", table_name="recovery_cases")
    op.drop_index("ix_recovery_cases_status", table_name="recovery_cases")
    op.drop_index("ix_recovery_cases_user_id", table_name="recovery_cases")
    op.drop_table("recovery_cases")

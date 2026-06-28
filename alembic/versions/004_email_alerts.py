"""Add email alert settings, events, and monitor alert state."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_email_alerts"
down_revision: Union[str, None] = "003_status_pages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "monitor_states",
        sa.Column("alert_open", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "monitor_states",
        sa.Column("alert_opened_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "alert_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("smtp_host", sa.String(length=255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("smtp_username", sa.String(length=255), nullable=True),
        sa.Column("smtp_password_encrypted_or_secret_ref", sa.String(length=255), nullable=True),
        sa.Column("smtp_from", sa.String(length=255), nullable=True),
        sa.Column("alert_to", sa.String(length=255), nullable=True),
        sa.Column("send_resolved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("monitor_id", sa.Integer(), nullable=True),
        sa.Column("check_result_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["check_result_id"], ["check_results.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_events_created_at", "alert_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alert_events_created_at", table_name="alert_events")
    op.drop_table("alert_events")
    op.drop_table("alert_settings")
    op.drop_column("monitor_states", "alert_opened_at")
    op.drop_column("monitor_states", "alert_open")

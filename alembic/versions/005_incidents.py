"""Add incidents, incident updates, and monitor open incident link."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_incidents"
down_revision: Union[str, None] = "004_email_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("monitor_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="major"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_created", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incidents_started_at", "incidents", ["started_at"], unique=False)
    op.create_index("ix_incidents_status", "incidents", ["status"], unique=False)

    op.create_table(
        "incident_updates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_incident_updates_incident_id_created_at",
        "incident_updates",
        ["incident_id", "created_at"],
        unique=False,
    )

    with op.batch_alter_table("monitor_states") as batch_op:
        batch_op.add_column(sa.Column("open_incident_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_monitor_states_open_incident_id",
            "incidents",
            ["open_incident_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("monitor_states") as batch_op:
        batch_op.drop_constraint("fk_monitor_states_open_incident_id", type_="foreignkey")
        batch_op.drop_column("open_incident_id")
    op.drop_index("ix_incident_updates_incident_id_created_at", table_name="incident_updates")
    op.drop_table("incident_updates")
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_started_at", table_name="incidents")
    op.drop_table("incidents")

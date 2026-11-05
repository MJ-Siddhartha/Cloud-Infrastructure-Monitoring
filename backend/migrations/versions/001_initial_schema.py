"""Initial schema — incidents table.

Revision ID: 001_initial_schema
Revises: None
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("alert_name", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(50), server_default="warning", nullable=True),
        sa.Column("instance", sa.String(255), nullable=True),
        sa.Column("metric_name", sa.String(255), nullable=True),
        sa.Column("metric_value", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), server_default="firing", nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_payload", sa.JSON(), nullable=True),
        sa.Column("recovery_action", sa.String(255), nullable=True),
        sa.Column("recovery_status", sa.String(50), nullable=True),
        sa.Column("recovery_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_output", sa.Text(), nullable=True),
        sa.Column("recovery_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint", "started_at", name="uq_fingerprint_started_at"),
    )
    op.create_index("ix_incidents_fingerprint", "incidents", ["fingerprint"])
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_alert_name", "incidents", ["alert_name"])
    op.create_index("ix_incidents_instance", "incidents", ["instance"])
    op.create_index("ix_incidents_severity", "incidents", ["severity"])


def downgrade() -> None:
    op.drop_index("ix_incidents_severity", table_name="incidents")
    op.drop_index("ix_incidents_instance", table_name="incidents")
    op.drop_index("ix_incidents_alert_name", table_name="incidents")
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_fingerprint", table_name="incidents")
    op.drop_table("incidents")

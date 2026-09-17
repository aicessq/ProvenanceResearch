"""add ingest task reliability metadata

Revision ID: 0002_ingest_task_reliability
Revises: 0001_phase1_initial
Create Date: 2026-08-04 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_ingest_task_reliability"
down_revision = "0001_phase1_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingest_tasks", sa.Column("celery_task_id", sa.String(length=255), nullable=True))
    op.add_column(
        "ingest_tasks",
        sa.Column("dispatch_status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
    )
    op.add_column("ingest_tasks", sa.Column("dispatched_at", sa.DateTime(), nullable=True))
    op.add_column(
        "ingest_tasks", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
    )
    op.add_column(
        "ingest_tasks", sa.Column("recovery_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
    )
    op.add_column("ingest_tasks", sa.Column("worker_id", sa.String(length=255), nullable=True))
    op.add_column("ingest_tasks", sa.Column("attempt_token", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("ingest_tasks", sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))

    op.create_check_constraint(
        "ck_ingest_tasks_attempt_count_nonnegative", "ingest_tasks", "attempt_count >= 0"
    )
    op.create_check_constraint(
        "ck_ingest_tasks_recovery_count_nonnegative", "ingest_tasks", "recovery_count >= 0"
    )
    op.create_check_constraint(
        "ck_ingest_tasks_status",
        "ingest_tasks",
        "status IN ('queued', 'processing', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_ingest_tasks_dispatch_status",
        "ingest_tasks",
        "dispatch_status IN ('pending', 'dispatched', 'failed')",
    )
    op.create_index(
        "idx_ingest_tasks_stale_dispatch",
        "ingest_tasks",
        ["status", "dispatch_status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "idx_ingest_tasks_stale_processing",
        "ingest_tasks",
        ["status", "last_heartbeat_at"],
        unique=False,
    )
    op.create_index("idx_ingest_tasks_celery_task_id", "ingest_tasks", ["celery_task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_ingest_tasks_celery_task_id", table_name="ingest_tasks")
    op.drop_index("idx_ingest_tasks_stale_processing", table_name="ingest_tasks")
    op.drop_index("idx_ingest_tasks_stale_dispatch", table_name="ingest_tasks")
    op.drop_constraint("ck_ingest_tasks_dispatch_status", "ingest_tasks", type_="check")
    op.drop_constraint("ck_ingest_tasks_status", "ingest_tasks", type_="check")
    op.drop_constraint("ck_ingest_tasks_recovery_count_nonnegative", "ingest_tasks", type_="check")
    op.drop_constraint("ck_ingest_tasks_attempt_count_nonnegative", "ingest_tasks", type_="check")
    op.drop_column("ingest_tasks", "last_heartbeat_at")
    op.drop_column("ingest_tasks", "attempt_token")
    op.drop_column("ingest_tasks", "worker_id")
    op.drop_column("ingest_tasks", "recovery_count")
    op.drop_column("ingest_tasks", "attempt_count")
    op.drop_column("ingest_tasks", "dispatched_at")
    op.drop_column("ingest_tasks", "dispatch_status")
    op.drop_column("ingest_tasks", "celery_task_id")

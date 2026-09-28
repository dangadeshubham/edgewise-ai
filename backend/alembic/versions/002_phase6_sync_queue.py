"""Phase 6: Durable Synchronization Queue Schema Extensions

Revision ID: 002_phase6_sync_queue
Revises: 001_initial
Create Date: 2026-09-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002_phase6_sync_queue"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- sync_items additions ---
    # revision, content_hash, processing_started_at
    with op.batch_alter_table("sync_items") as batch_op:
        batch_op.add_column(
            sa.Column("revision", sa.Integer(), nullable=True, server_default="1")
        )
        batch_op.add_column(
            sa.Column("content_hash", sa.String(128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("processing_started_at", sa.DateTime(), nullable=True)
        )

    # --- sync_attempts additions ---
    # attempt_number, started_at, completed_at, error_category
    with op.batch_alter_table("sync_attempts") as batch_op:
        batch_op.add_column(
            sa.Column("attempt_number", sa.Integer(), nullable=True, server_default="1")
        )
        batch_op.add_column(
            sa.Column("started_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("completed_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("error_category", sa.String(64), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("sync_attempts") as batch_op:
        batch_op.drop_column("error_category")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("attempt_number")

    with op.batch_alter_table("sync_items") as batch_op:
        batch_op.drop_column("processing_started_at")
        batch_op.drop_column("content_hash")
        batch_op.drop_column("revision")

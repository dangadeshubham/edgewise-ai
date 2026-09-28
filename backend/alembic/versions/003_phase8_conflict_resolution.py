"""Phase 8: Conflict Resolution Schema Extensions

Revision ID: 003_phase8_conflict_resolution
Revises: 002_phase6_sync_queue
Create Date: 2026-09-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003_phase8_conflict_resolution"
down_revision: Union[str, None] = "002_phase6_sync_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add resolution_metadata_json and version to conflicts table
    with op.batch_alter_table("conflicts") as batch_op:
        batch_op.add_column(
            sa.Column("resolution_metadata_json", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=True, server_default="1")
        )


def downgrade() -> None:
    with op.batch_alter_table("conflicts") as batch_op:
        batch_op.drop_column("version")
        batch_op.drop_column("resolution_metadata_json")

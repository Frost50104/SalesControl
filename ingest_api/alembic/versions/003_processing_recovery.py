"""Add processing_started_at for stuck chunk recovery.

Revision ID: 003
Revises: 002
Create Date: 2026-01-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add processing_started_at to track when processing began
    op.add_column(
        "audio_chunks",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Add index for efficient stuck chunk queries
    op.create_index(
        "ix_audio_chunks_status_processing_started",
        "audio_chunks",
        ["status", "processing_started_at"],
        postgresql_where=sa.text("status = 'PROCESSING'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audio_chunks_status_processing_started",
        table_name="audio_chunks",
    )
    op.drop_column("audio_chunks", "processing_started_at")

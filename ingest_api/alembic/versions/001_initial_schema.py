"""Initial schema with devices and audio_chunks tables.

Revision ID: 001
Revises:
Create Date: 2026-01-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create devices table
    op.create_table(
        "devices",
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("point_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("register_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("device_id"),
    )

    # Create audio_chunks table
    op.create_table(
        "audio_chunks",
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("point_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("register_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False),
        sa.Column("codec", sa.String(32), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("channels", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="UPLOADED"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.device_id"],
            ondelete="CASCADE",
        ),
    )

    # Create indexes
    op.create_index(
        "ix_audio_chunks_point_start",
        "audio_chunks",
        ["point_id", "start_ts"],
    )
    op.create_index(
        "ix_audio_chunks_device_start",
        "audio_chunks",
        ["device_id", "start_ts"],
    )


def downgrade() -> None:
    op.drop_index("ix_audio_chunks_device_start", table_name="audio_chunks")
    op.drop_index("ix_audio_chunks_point_start", table_name="audio_chunks")
    op.drop_table("audio_chunks")
    op.drop_table("devices")

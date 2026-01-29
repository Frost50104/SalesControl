"""Add VAD worker tables: speech_segments, dialogues, dialogue_segments, device_dialogue_state.

Also adds error_message column to audio_chunks.

Revision ID: 002
Revises: 001
Create Date: 2026-01-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add error_message column to audio_chunks
    op.add_column(
        "audio_chunks",
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    # Create speech_segments table
    op.create_table(
        "speech_segments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["audio_chunks.chunk_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_speech_segments_chunk_id",
        "speech_segments",
        ["chunk_id"],
    )

    # Create dialogues table
    op.create_table(
        "dialogues",
        sa.Column(
            "dialogue_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("point_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("register_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="vad"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("dialogue_id"),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.device_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_dialogues_device_start",
        "dialogues",
        ["device_id", "start_ts"],
    )
    op.create_index(
        "ix_dialogues_point_start",
        "dialogues",
        ["point_id", "start_ts"],
    )

    # Create dialogue_segments table (many-to-many relationship)
    op.create_table(
        "dialogue_segments",
        sa.Column("dialogue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("dialogue_id", "chunk_id", "start_ms", "end_ms"),
        sa.ForeignKeyConstraint(
            ["dialogue_id"],
            ["dialogues.dialogue_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["audio_chunks.chunk_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_dialogue_segments_dialogue_id",
        "dialogue_segments",
        ["dialogue_id"],
    )
    op.create_index(
        "ix_dialogue_segments_chunk_id",
        "dialogue_segments",
        ["chunk_id"],
    )

    # Create device_dialogue_state table (for cross-chunk dialogue continuity)
    op.create_table(
        "device_dialogue_state",
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("open_dialogue_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_speech_end_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("device_id"),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.device_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["open_dialogue_id"],
            ["dialogues.dialogue_id"],
            ondelete="SET NULL",
        ),
    )

    # Add index for finding chunks by status (for worker polling)
    op.create_index(
        "ix_audio_chunks_status",
        "audio_chunks",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_audio_chunks_status", table_name="audio_chunks")
    op.drop_table("device_dialogue_state")
    op.drop_index("ix_dialogue_segments_chunk_id", table_name="dialogue_segments")
    op.drop_index("ix_dialogue_segments_dialogue_id", table_name="dialogue_segments")
    op.drop_table("dialogue_segments")
    op.drop_index("ix_dialogues_point_start", table_name="dialogues")
    op.drop_index("ix_dialogues_device_start", table_name="dialogues")
    op.drop_table("dialogues")
    op.drop_index("ix_speech_segments_chunk_id", table_name="speech_segments")
    op.drop_table("speech_segments")
    op.drop_column("audio_chunks", "error_message")

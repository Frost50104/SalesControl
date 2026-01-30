"""Add ASR tables and fields to dialogues.

Adds asr_status and related fields to dialogues table.
Creates dialogue_transcripts table for storing transcription results.

Revision ID: 004
Revises: 003
Create Date: 2026-01-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add ASR fields to dialogues table
    op.add_column(
        "dialogues",
        sa.Column(
            "asr_status",
            sa.Text(),
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column(
        "dialogues",
        sa.Column("asr_processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dialogues",
        sa.Column("asr_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dialogues",
        sa.Column("asr_finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dialogues",
        sa.Column("asr_error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "dialogues",
        sa.Column("asr_pass", sa.Text(), nullable=True),  # 'fast' or 'accurate'
    )
    op.add_column(
        "dialogues",
        sa.Column("asr_model", sa.Text(), nullable=True),
    )

    # Index for efficient polling of PENDING dialogues
    op.create_index(
        "ix_dialogues_asr_status",
        "dialogues",
        ["asr_status"],
    )

    # Create dialogue_transcripts table
    op.create_table(
        "dialogue_transcripts",
        sa.Column(
            "transcript_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("dialogue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language", sa.Text(), nullable=False, server_default="ru"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("segments_json", postgresql.JSONB(), nullable=True),
        sa.Column("avg_logprob", sa.Float(), nullable=True),
        sa.Column("no_speech_prob", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("transcript_id"),
        sa.ForeignKeyConstraint(
            ["dialogue_id"],
            ["dialogues.dialogue_id"],
            ondelete="CASCADE",
        ),
        # UNIQUE constraint on dialogue_id (one transcript per dialogue)
        sa.UniqueConstraint("dialogue_id", name="uq_dialogue_transcripts_dialogue_id"),
    )

    # Index for transcript lookup by dialogue
    op.create_index(
        "ix_dialogue_transcripts_dialogue_id",
        "dialogue_transcripts",
        ["dialogue_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dialogue_transcripts_dialogue_id", table_name="dialogue_transcripts")
    op.drop_table("dialogue_transcripts")
    op.drop_index("ix_dialogues_asr_status", table_name="dialogues")
    op.drop_column("dialogues", "asr_model")
    op.drop_column("dialogues", "asr_pass")
    op.drop_column("dialogues", "asr_error_message")
    op.drop_column("dialogues", "asr_finished_at")
    op.drop_column("dialogues", "asr_started_at")
    op.drop_column("dialogues", "asr_processing_started_at")
    op.drop_column("dialogues", "asr_status")

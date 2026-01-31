"""Add review labels tables for human-in-the-loop workflow.

Adds dialogue_reviews table for flagging and correcting analyses.
Adds review_status field to dialogues table.
Adds dialogue_upsell_analysis_history for storing previous analysis versions.

Revision ID: 006
Revises: 005
Create Date: 2026-01-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add review_status to dialogues table
    op.add_column(
        "dialogues",
        sa.Column(
            "review_status",
            sa.Text(),
            nullable=False,
            server_default="NONE",
        ),
    )

    # Index for filtering by review status
    op.create_index(
        "ix_dialogues_review_status",
        "dialogues",
        ["review_status"],
    )

    # Create dialogue_reviews table
    op.create_table(
        "dialogue_reviews",
        sa.Column(
            "review_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("dialogue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "reviewer",
            sa.Text(),
            nullable=True,
        ),  # Optional identifier (no PII)
        sa.Column(
            "flag",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),  # Is this a flag/issue report?
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
        ),  # 'bad_asr', 'llm_missed_upsell', 'llm_false_positive', 'wrong_quality', 'wrong_category', 'other'
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
        ),  # Additional notes
        sa.Column(
            "corrected",
            postgresql.JSONB(),
            nullable=True,
        ),  # Corrected values: {attempted, quality_score, categories, closing_question, customer_reaction}
        sa.PrimaryKeyConstraint("review_id"),
        sa.ForeignKeyConstraint(
            ["dialogue_id"],
            ["dialogues.dialogue_id"],
            ondelete="CASCADE",
        ),
        # Check constraint for reason values
        sa.CheckConstraint(
            "reason IN ('bad_asr', 'llm_missed_upsell', 'llm_false_positive', 'wrong_quality', 'wrong_category', 'other')",
            name="ck_dialogue_reviews_reason",
        ),
    )

    # Index for querying reviews by dialogue
    op.create_index(
        "ix_dialogue_reviews_dialogue_id",
        "dialogue_reviews",
        ["dialogue_id"],
    )

    # Index for querying by creation time
    op.create_index(
        "ix_dialogue_reviews_created_at",
        "dialogue_reviews",
        ["created_at"],
    )

    # Create dialogue_upsell_analysis_history for storing previous analysis versions
    op.create_table(
        "dialogue_upsell_analysis_history",
        sa.Column(
            "history_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("dialogue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Snapshot of original analysis
        sa.Column("attempted", sa.Text(), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=False),
        sa.Column("categories", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("closing_question", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("customer_reaction", sa.Text(), nullable=False),
        sa.Column("evidence_quotes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("analysis_model", sa.Text(), nullable=True),
        sa.Column("analysis_prompt_version", sa.Text(), nullable=True),
        sa.Column(
            "original_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("history_id"),
        sa.ForeignKeyConstraint(
            ["dialogue_id"],
            ["dialogues.dialogue_id"],
            ondelete="CASCADE",
        ),
    )

    # Index for querying history by dialogue
    op.create_index(
        "ix_dialogue_upsell_analysis_history_dialogue_id",
        "dialogue_upsell_analysis_history",
        ["dialogue_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dialogue_upsell_analysis_history_dialogue_id",
        table_name="dialogue_upsell_analysis_history",
    )
    op.drop_table("dialogue_upsell_analysis_history")
    op.drop_index("ix_dialogue_reviews_created_at", table_name="dialogue_reviews")
    op.drop_index("ix_dialogue_reviews_dialogue_id", table_name="dialogue_reviews")
    op.drop_table("dialogue_reviews")
    op.drop_index("ix_dialogues_review_status", table_name="dialogues")
    op.drop_column("dialogues", "review_status")

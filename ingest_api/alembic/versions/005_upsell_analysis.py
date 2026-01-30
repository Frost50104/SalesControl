"""Add upsell analysis tables and fields.

Adds analysis_status and related fields to dialogues table.
Creates dialogue_upsell_analysis table for storing LLM analysis results.

Revision ID: 005
Revises: 004
Create Date: 2026-01-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add analysis fields to dialogues table
    op.add_column(
        "dialogues",
        sa.Column(
            "analysis_status",
            sa.Text(),
            nullable=False,
            server_default="PENDING",
        ),
    )
    op.add_column(
        "dialogues",
        sa.Column("analysis_processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dialogues",
        sa.Column("analysis_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dialogues",
        sa.Column("analysis_finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dialogues",
        sa.Column("analysis_error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "dialogues",
        sa.Column("analysis_model", sa.Text(), nullable=True),
    )
    op.add_column(
        "dialogues",
        sa.Column("analysis_prompt_version", sa.Text(), nullable=True),
    )

    # Index for efficient polling of PENDING dialogues for analysis
    op.create_index(
        "ix_dialogues_analysis_status",
        "dialogues",
        ["analysis_status"],
    )

    # Create dialogue_upsell_analysis table
    op.create_table(
        "dialogue_upsell_analysis",
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("dialogue_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Upsell evaluation fields
        sa.Column(
            "attempted",
            sa.Text(),
            nullable=False,
        ),  # 'yes' | 'no' | 'uncertain'
        sa.Column(
            "quality_score",
            sa.Integer(),
            nullable=False,
        ),  # 0..3
        sa.Column(
            "categories",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),  # Array of category strings
        sa.Column(
            "closing_question",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "customer_reaction",
            sa.Text(),
            nullable=False,
        ),  # 'accepted' | 'rejected' | 'unclear'
        sa.Column(
            "evidence_quotes",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),  # Array of quote strings
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=True,
        ),  # 0..1
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("analysis_id"),
        sa.ForeignKeyConstraint(
            ["dialogue_id"],
            ["dialogues.dialogue_id"],
            ondelete="CASCADE",
        ),
        # UNIQUE constraint on dialogue_id (one analysis per dialogue)
        sa.UniqueConstraint("dialogue_id", name="uq_dialogue_upsell_analysis_dialogue_id"),
        # Check constraint for attempted values
        sa.CheckConstraint(
            "attempted IN ('yes', 'no', 'uncertain')",
            name="ck_dialogue_upsell_analysis_attempted",
        ),
        # Check constraint for quality_score range
        sa.CheckConstraint(
            "quality_score >= 0 AND quality_score <= 3",
            name="ck_dialogue_upsell_analysis_quality_score",
        ),
        # Check constraint for customer_reaction values
        sa.CheckConstraint(
            "customer_reaction IN ('accepted', 'rejected', 'unclear')",
            name="ck_dialogue_upsell_analysis_customer_reaction",
        ),
    )

    # Index for analysis lookup by dialogue
    op.create_index(
        "ix_dialogue_upsell_analysis_dialogue_id",
        "dialogue_upsell_analysis",
        ["dialogue_id"],
    )

    # Index for aggregation queries by categories (GIN for JSONB)
    op.create_index(
        "ix_dialogue_upsell_analysis_categories",
        "dialogue_upsell_analysis",
        ["categories"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_dialogue_upsell_analysis_categories", table_name="dialogue_upsell_analysis")
    op.drop_index("ix_dialogue_upsell_analysis_dialogue_id", table_name="dialogue_upsell_analysis")
    op.drop_table("dialogue_upsell_analysis")
    op.drop_index("ix_dialogues_analysis_status", table_name="dialogues")
    op.drop_column("dialogues", "analysis_prompt_version")
    op.drop_column("dialogues", "analysis_model")
    op.drop_column("dialogues", "analysis_error_message")
    op.drop_column("dialogues", "analysis_finished_at")
    op.drop_column("dialogues", "analysis_started_at")
    op.drop_column("dialogues", "analysis_processing_started_at")
    op.drop_column("dialogues", "analysis_status")

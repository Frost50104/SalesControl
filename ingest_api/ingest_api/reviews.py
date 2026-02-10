"""Reviews API routes for human-in-the-loop workflow."""

import csv
import io
import json
import logging
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["reviews"])


# =============================================================================
# Schemas
# =============================================================================


class ReviewReason(str, Enum):
    BAD_ASR = "bad_asr"
    LLM_MISSED_UPSELL = "llm_missed_upsell"
    LLM_FALSE_POSITIVE = "llm_false_positive"
    WRONG_QUALITY = "wrong_quality"
    WRONG_CATEGORY = "wrong_category"
    OTHER = "other"


class ReviewStatus(str, Enum):
    NONE = "NONE"
    FLAGGED = "FLAGGED"
    RESOLVED = "RESOLVED"


class CorrectedAnalysis(BaseModel):
    """Manually corrected analysis values."""

    attempted: str | None = Field(None, pattern="^(yes|no|uncertain)$")
    quality_score: int | None = Field(None, ge=0, le=3)
    categories: list[str] | None = None
    closing_question: bool | None = None
    customer_reaction: str | None = Field(None, pattern="^(accepted|rejected|unclear)$")


class CreateReviewRequest(BaseModel):
    """Request to create a review/flag."""

    reason: ReviewReason
    notes: str | None = None
    corrected: CorrectedAnalysis | None = None
    reviewer: str | None = None  # Optional identifier (no PII)


class ReviewResponse(BaseModel):
    """Review record."""

    review_id: UUID
    dialogue_id: UUID
    created_at: datetime
    reviewer: str | None
    flag: bool
    reason: str
    notes: str | None
    corrected: dict | None


class ReviewWithDialogue(BaseModel):
    """Review with dialogue summary."""

    review_id: UUID
    dialogue_id: UUID
    created_at: datetime
    reviewer: str | None
    flag: bool
    reason: str
    notes: str | None
    corrected: dict | None
    # Dialogue info
    dialogue_start_ts: datetime
    dialogue_end_ts: datetime
    point_id: UUID
    review_status: str
    # Analysis summary
    attempted: str | None = None
    quality_score: int | None = None
    categories: list[str] | None = None
    customer_reaction: str | None = None
    text_snippet: str | None = None


class ReviewListResponse(BaseModel):
    """List of reviews."""

    total: int
    reviews: list[ReviewWithDialogue]


class RerunResponse(BaseModel):
    """Response from analysis rerun."""

    dialogue_id: UUID
    message: str
    previous_analysis_archived: bool


class ExportFormat(str, Enum):
    CSV = "csv"
    JSON = "json"


# =============================================================================
# Review endpoints
# =============================================================================


@router.post(
    "/reviews/{dialogue_id}",
    response_model=ReviewResponse,
    dependencies=[Depends(get_current_user)],
)
async def create_review(
    dialogue_id: UUID,
    request: CreateReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    """
    Create a review/flag for a dialogue.

    Marks the dialogue as FLAGGED and creates a review record.
    """
    # Check dialogue exists
    check_query = text("SELECT dialogue_id FROM dialogues WHERE dialogue_id = :dialogue_id")
    result = await session.execute(check_query, {"dialogue_id": dialogue_id})
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Dialogue not found")

    # Update dialogue review_status
    update_query = text("""
        UPDATE dialogues
        SET review_status = 'FLAGGED'
        WHERE dialogue_id = :dialogue_id
    """)
    await session.execute(update_query, {"dialogue_id": dialogue_id})

    # Insert review record
    corrected_json = request.corrected.model_dump(exclude_none=True) if request.corrected else None

    insert_query = text("""
        INSERT INTO dialogue_reviews (dialogue_id, reviewer, flag, reason, notes, corrected)
        VALUES (:dialogue_id, :reviewer, true, :reason, :notes, :corrected)
        RETURNING review_id, dialogue_id, created_at, reviewer, flag, reason, notes, corrected
    """)

    result = await session.execute(
        insert_query,
        {
            "dialogue_id": dialogue_id,
            "reviewer": request.reviewer,
            "reason": request.reason.value,
            "notes": request.notes,
            "corrected": json.dumps(corrected_json) if corrected_json else None,
        },
    )
    await session.commit()

    row = result.fetchone()
    return ReviewResponse(
        review_id=row.review_id,
        dialogue_id=row.dialogue_id,
        created_at=row.created_at,
        reviewer=row.reviewer,
        flag=row.flag,
        reason=row.reason,
        notes=row.notes,
        corrected=row.corrected,
    )


@router.get(
    "/reviews",
    response_model=ReviewListResponse,
    dependencies=[Depends(get_current_user)],
)
async def list_reviews(
    date_from: date | None = Query(None, alias="date", description="Filter by date"),
    point_id: UUID | None = Query(None, description="Filter by point_id"),
    status: ReviewStatus | None = Query(None, description="Filter by review status"),
    reason: ReviewReason | None = Query(None, description="Filter by reason"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_session),
) -> ReviewListResponse:
    """
    List reviews with optional filters.
    """
    filters = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if date_from:
        date_start = datetime.combine(date_from, datetime.min.time()).replace(tzinfo=timezone.utc)
        date_end = datetime.combine(date_from, datetime.max.time()).replace(tzinfo=timezone.utc)
        filters.append("d.start_ts >= :date_start AND d.start_ts < :date_end")
        params["date_start"] = date_start
        params["date_end"] = date_end

    if point_id:
        filters.append("d.point_id = :point_id")
        params["point_id"] = point_id

    if status:
        filters.append("d.review_status = :status")
        params["status"] = status.value

    if reason:
        filters.append("dr.reason = :reason")
        params["reason"] = reason.value

    where_clause = " AND ".join(filters)

    # Count total
    count_query = text(f"""
        SELECT COUNT(*)
        FROM dialogue_reviews dr
        JOIN dialogues d ON dr.dialogue_id = d.dialogue_id
        WHERE {where_clause}
    """)
    result = await session.execute(count_query, params)
    total = result.scalar() or 0

    # Get reviews with dialogue info
    query = text(f"""
        SELECT
            dr.review_id,
            dr.dialogue_id,
            dr.created_at,
            dr.reviewer,
            dr.flag,
            dr.reason,
            dr.notes,
            dr.corrected,
            d.start_ts as dialogue_start_ts,
            d.end_ts as dialogue_end_ts,
            d.point_id,
            d.review_status,
            dua.attempted,
            dua.quality_score,
            dua.categories,
            dua.customer_reaction,
            LEFT(dt.text, 200) as text_snippet
        FROM dialogue_reviews dr
        JOIN dialogues d ON dr.dialogue_id = d.dialogue_id
        LEFT JOIN dialogue_upsell_analysis dua ON d.dialogue_id = dua.dialogue_id
        LEFT JOIN dialogue_transcripts dt ON d.dialogue_id = dt.dialogue_id
        WHERE {where_clause}
        ORDER BY dr.created_at DESC
        LIMIT :limit OFFSET :offset
    """)

    result = await session.execute(query, params)
    rows = result.fetchall()

    reviews = [
        ReviewWithDialogue(
            review_id=row.review_id,
            dialogue_id=row.dialogue_id,
            created_at=row.created_at,
            reviewer=row.reviewer,
            flag=row.flag,
            reason=row.reason,
            notes=row.notes,
            corrected=row.corrected,
            dialogue_start_ts=row.dialogue_start_ts,
            dialogue_end_ts=row.dialogue_end_ts,
            point_id=row.point_id,
            review_status=row.review_status,
            attempted=row.attempted,
            quality_score=row.quality_score,
            categories=row.categories if isinstance(row.categories, list) else [],
            customer_reaction=row.customer_reaction,
            text_snippet=row.text_snippet,
        )
        for row in rows
    ]

    return ReviewListResponse(total=total, reviews=reviews)


@router.patch(
    "/reviews/{review_id}",
    response_model=ReviewResponse,
    dependencies=[Depends(get_current_user)],
)
async def update_review(
    review_id: UUID,
    resolved: bool = Query(True, description="Mark as resolved"),
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    """
    Update review status (mark as resolved).
    """
    # Get review
    get_query = text("""
        SELECT review_id, dialogue_id, created_at, reviewer, flag, reason, notes, corrected
        FROM dialogue_reviews
        WHERE review_id = :review_id
    """)
    result = await session.execute(get_query, {"review_id": review_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Review not found")

    # Update dialogue review_status
    new_status = "RESOLVED" if resolved else "FLAGGED"
    update_query = text("""
        UPDATE dialogues
        SET review_status = :status
        WHERE dialogue_id = :dialogue_id
    """)
    await session.execute(update_query, {"dialogue_id": row.dialogue_id, "status": new_status})
    await session.commit()

    return ReviewResponse(
        review_id=row.review_id,
        dialogue_id=row.dialogue_id,
        created_at=row.created_at,
        reviewer=row.reviewer,
        flag=row.flag,
        reason=row.reason,
        notes=row.notes,
        corrected=row.corrected,
    )


# =============================================================================
# Analysis rerun endpoint
# =============================================================================


@router.post(
    "/analysis/rerun/{dialogue_id}",
    response_model=RerunResponse,
    dependencies=[Depends(get_current_user)],
)
async def rerun_analysis(
    dialogue_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> RerunResponse:
    """
    Trigger re-analysis of a dialogue.

    Archives current analysis to history and resets analysis_status to PENDING.
    """
    # Check dialogue exists and has ASR done
    check_query = text("""
        SELECT d.dialogue_id, d.asr_status, d.analysis_status,
               dua.analysis_id, dua.attempted, dua.quality_score, dua.categories,
               dua.closing_question, dua.customer_reaction, dua.evidence_quotes,
               dua.summary, dua.confidence, dua.created_at as analysis_created_at,
               d.analysis_model, d.analysis_prompt_version
        FROM dialogues d
        LEFT JOIN dialogue_upsell_analysis dua ON d.dialogue_id = dua.dialogue_id
        WHERE d.dialogue_id = :dialogue_id
    """)
    result = await session.execute(check_query, {"dialogue_id": dialogue_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Dialogue not found")

    if row.asr_status != "DONE":
        raise HTTPException(status_code=400, detail="ASR not completed for this dialogue")

    archived = False

    # Archive current analysis if exists
    if row.analysis_id:
        archive_query = text("""
            INSERT INTO dialogue_upsell_analysis_history (
                dialogue_id, attempted, quality_score, categories, closing_question,
                customer_reaction, evidence_quotes, summary, confidence,
                analysis_model, analysis_prompt_version, original_created_at
            )
            VALUES (
                :dialogue_id, :attempted, :quality_score, :categories, :closing_question,
                :customer_reaction, :evidence_quotes, :summary, :confidence,
                :analysis_model, :analysis_prompt_version, :original_created_at
            )
        """)
        await session.execute(
            archive_query,
            {
                "dialogue_id": dialogue_id,
                "attempted": row.attempted,
                "quality_score": row.quality_score,
                "categories": json.dumps(row.categories) if row.categories else "[]",
                "closing_question": row.closing_question,
                "customer_reaction": row.customer_reaction,
                "evidence_quotes": json.dumps(row.evidence_quotes) if row.evidence_quotes else "[]",
                "summary": row.summary,
                "confidence": row.confidence,
                "analysis_model": row.analysis_model,
                "analysis_prompt_version": row.analysis_prompt_version,
                "original_created_at": row.analysis_created_at,
            },
        )

        # Delete current analysis
        delete_query = text("DELETE FROM dialogue_upsell_analysis WHERE dialogue_id = :dialogue_id")
        await session.execute(delete_query, {"dialogue_id": dialogue_id})
        archived = True

    # Reset analysis status to PENDING
    reset_query = text("""
        UPDATE dialogues
        SET analysis_status = 'PENDING',
            analysis_processing_started_at = NULL,
            analysis_started_at = NULL,
            analysis_finished_at = NULL,
            analysis_error_message = NULL,
            analysis_model = NULL,
            analysis_prompt_version = NULL
        WHERE dialogue_id = :dialogue_id
    """)
    await session.execute(reset_query, {"dialogue_id": dialogue_id})
    await session.commit()

    logger.info(
        "analysis_rerun_triggered",
        extra={"dialogue_id": str(dialogue_id), "archived": archived},
    )

    return RerunResponse(
        dialogue_id=dialogue_id,
        message="Analysis queued for re-processing",
        previous_analysis_archived=archived,
    )


# =============================================================================
# Export endpoint
# =============================================================================


@router.get(
    "/exports/reviews",
    dependencies=[Depends(get_current_user)],
)
async def export_reviews(
    date_from: date = Query(..., alias="from", description="Start date"),
    date_to: date = Query(..., alias="to", description="End date"),
    format: ExportFormat = Query(ExportFormat.JSON, description="Export format"),
    session: AsyncSession = Depends(get_session),
):
    """
    Export reviewed/flagged dialogues for dataset building.

    Returns dialogues with their reviews, analysis, and transcripts.
    """
    start_ts = datetime.combine(date_from, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_ts = datetime.combine(date_to, datetime.max.time()).replace(tzinfo=timezone.utc)

    query = text("""
        SELECT
            d.dialogue_id,
            d.point_id,
            d.register_id,
            d.start_ts,
            d.end_ts,
            d.review_status,
            dt.text as transcript,
            dua.attempted as llm_attempted,
            dua.quality_score as llm_quality_score,
            dua.categories as llm_categories,
            dua.closing_question as llm_closing_question,
            dua.customer_reaction as llm_customer_reaction,
            dua.summary as llm_summary,
            dua.evidence_quotes as llm_evidence_quotes,
            dua.confidence as llm_confidence,
            dr.review_id,
            dr.created_at as review_created_at,
            dr.reason as review_reason,
            dr.notes as review_notes,
            dr.corrected as review_corrected
        FROM dialogues d
        LEFT JOIN dialogue_transcripts dt ON d.dialogue_id = dt.dialogue_id
        LEFT JOIN dialogue_upsell_analysis dua ON d.dialogue_id = dua.dialogue_id
        LEFT JOIN dialogue_reviews dr ON d.dialogue_id = dr.dialogue_id
        WHERE d.start_ts >= :start_ts AND d.start_ts < :end_ts
          AND d.review_status != 'NONE'
        ORDER BY d.start_ts
    """)

    result = await session.execute(query, {"start_ts": start_ts, "end_ts": end_ts})
    rows = result.fetchall()

    if format == ExportFormat.JSON:
        data = []
        for row in rows:
            item = {
                "dialogue_id": str(row.dialogue_id),
                "point_id": str(row.point_id),
                "register_id": str(row.register_id),
                "start_ts": row.start_ts.isoformat(),
                "end_ts": row.end_ts.isoformat(),
                "review_status": row.review_status,
                "transcript": row.transcript,
                "llm_analysis": {
                    "attempted": row.llm_attempted,
                    "quality_score": row.llm_quality_score,
                    "categories": row.llm_categories,
                    "closing_question": row.llm_closing_question,
                    "customer_reaction": row.llm_customer_reaction,
                    "summary": row.llm_summary,
                    "evidence_quotes": row.llm_evidence_quotes,
                    "confidence": row.llm_confidence,
                },
                "review": {
                    "review_id": str(row.review_id) if row.review_id else None,
                    "created_at": row.review_created_at.isoformat() if row.review_created_at else None,
                    "reason": row.review_reason,
                    "notes": row.review_notes,
                    "corrected": row.review_corrected,
                } if row.review_id else None,
            }
            data.append(item)

        content = json.dumps(data, ensure_ascii=False, indent=2)
        return StreamingResponse(
            io.StringIO(content),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="reviews_{date_from}_{date_to}.json"'
            },
        )

    else:  # CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            "dialogue_id",
            "point_id",
            "start_ts",
            "end_ts",
            "review_status",
            "transcript",
            "llm_attempted",
            "llm_quality_score",
            "llm_categories",
            "llm_customer_reaction",
            "llm_summary",
            "review_reason",
            "review_notes",
            "corrected_attempted",
            "corrected_quality_score",
            "corrected_categories",
            "corrected_customer_reaction",
        ])

        for row in rows:
            corrected = row.review_corrected or {}
            writer.writerow([
                str(row.dialogue_id),
                str(row.point_id),
                row.start_ts.isoformat(),
                row.end_ts.isoformat(),
                row.review_status,
                row.transcript,
                row.llm_attempted,
                row.llm_quality_score,
                json.dumps(row.llm_categories) if row.llm_categories else "",
                row.llm_customer_reaction,
                row.llm_summary,
                row.review_reason,
                row.review_notes,
                corrected.get("attempted", ""),
                corrected.get("quality_score", ""),
                json.dumps(corrected.get("categories", [])) if corrected.get("categories") else "",
                corrected.get("customer_reaction", ""),
            ])

        output.seek(0)
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="reviews_{date_from}_{date_to}.csv"'
            },
        )

"""Analytics API routes for upsell analysis dashboard."""

import logging
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_current_user
from .db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


# =============================================================================
# Schemas
# =============================================================================


class HourlyStats(BaseModel):
    """Hourly statistics."""

    hour: int = Field(..., ge=0, le=23)
    dialogues_total: int
    attempted_yes: int
    attempted_no: int
    attempted_uncertain: int
    avg_quality: float
    accepted_count: int
    rejected_count: int


class CategoryCount(BaseModel):
    """Category count."""

    category: str
    count: int


class DailyAnalyticsResponse(BaseModel):
    """Daily analytics aggregates."""

    date: date
    point_id: UUID | None

    # Totals
    dialogues_total: int
    dialogues_analyzed: int
    dialogues_skipped: int
    dialogues_error: int

    # Upsell metrics
    attempted_yes: int
    attempted_no: int
    attempted_uncertain: int
    attempted_rate: float  # attempted_yes / dialogues_analyzed

    # Quality metrics
    avg_quality: float
    quality_distribution: dict[int, int]  # score -> count

    # Customer reaction
    accepted_count: int
    rejected_count: int
    unclear_count: int
    accepted_rate: float  # accepted / (accepted + rejected)

    # Categories
    top_categories: list[CategoryCount]

    # Hourly breakdown
    hourly: list[HourlyStats]


class DialogueAnalysisSummary(BaseModel):
    """Summary of a dialogue analysis."""

    dialogue_id: UUID
    start_ts: datetime
    end_ts: datetime
    quality_score: int
    attempted: str
    categories: list[str]
    customer_reaction: str
    closing_question: bool
    summary: str
    text_snippet: str | None = None


class DialogueListResponse(BaseModel):
    """List of dialogues with analysis."""

    date: date
    point_id: UUID | None
    total: int
    dialogues: list[DialogueAnalysisSummary]


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/daily",
    response_model=DailyAnalyticsResponse,
    dependencies=[Depends(get_current_user)],
)
async def get_daily_analytics(
    date: date = Query(..., description="Date in YYYY-MM-DD format"),
    point_id: UUID | None = Query(None, description="Filter by point_id"),
    session: AsyncSession = Depends(get_session),
) -> DailyAnalyticsResponse:
    """
    Get daily analytics aggregates.

    Returns aggregated upsell metrics for the specified date,
    optionally filtered by point_id.
    """
    # Base date filter
    date_start = datetime.combine(date, datetime.min.time()).replace(tzinfo=timezone.utc)
    date_end = datetime.combine(date, datetime.max.time()).replace(tzinfo=timezone.utc)

    # Build point filter
    point_filter = "AND d.point_id = :point_id" if point_id else ""
    params: dict[str, Any] = {"date_start": date_start, "date_end": date_end}
    if point_id:
        params["point_id"] = point_id

    # Get dialogue counts by status
    status_query = text(f"""
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE d.analysis_status = 'DONE') as analyzed,
            COUNT(*) FILTER (WHERE d.analysis_status = 'SKIPPED') as skipped,
            COUNT(*) FILTER (WHERE d.analysis_status = 'ERROR') as error
        FROM dialogues d
        WHERE d.start_ts >= :date_start AND d.start_ts < :date_end
            AND d.asr_status = 'DONE'
            {point_filter}
    """)
    result = await session.execute(status_query, params)
    status_row = result.fetchone()

    dialogues_total = status_row.total or 0
    dialogues_analyzed = status_row.analyzed or 0
    dialogues_skipped = status_row.skipped or 0
    dialogues_error = status_row.error or 0

    if dialogues_analyzed == 0:
        # No data - return empty response
        return DailyAnalyticsResponse(
            date=date,
            point_id=point_id,
            dialogues_total=dialogues_total,
            dialogues_analyzed=0,
            dialogues_skipped=dialogues_skipped,
            dialogues_error=dialogues_error,
            attempted_yes=0,
            attempted_no=0,
            attempted_uncertain=0,
            attempted_rate=0.0,
            avg_quality=0.0,
            quality_distribution={0: 0, 1: 0, 2: 0, 3: 0},
            accepted_count=0,
            rejected_count=0,
            unclear_count=0,
            accepted_rate=0.0,
            top_categories=[],
            hourly=[],
        )

    # Get upsell metrics
    metrics_query = text(f"""
        SELECT
            COUNT(*) FILTER (WHERE dua.attempted = 'yes') as attempted_yes,
            COUNT(*) FILTER (WHERE dua.attempted = 'no') as attempted_no,
            COUNT(*) FILTER (WHERE dua.attempted = 'uncertain') as attempted_uncertain,
            AVG(dua.quality_score) as avg_quality,
            COUNT(*) FILTER (WHERE dua.quality_score = 0) as quality_0,
            COUNT(*) FILTER (WHERE dua.quality_score = 1) as quality_1,
            COUNT(*) FILTER (WHERE dua.quality_score = 2) as quality_2,
            COUNT(*) FILTER (WHERE dua.quality_score = 3) as quality_3,
            COUNT(*) FILTER (WHERE dua.customer_reaction = 'accepted') as accepted,
            COUNT(*) FILTER (WHERE dua.customer_reaction = 'rejected') as rejected,
            COUNT(*) FILTER (WHERE dua.customer_reaction = 'unclear') as unclear
        FROM dialogues d
        JOIN dialogue_upsell_analysis dua ON d.dialogue_id = dua.dialogue_id
        WHERE d.start_ts >= :date_start AND d.start_ts < :date_end
            AND d.analysis_status = 'DONE'
            {point_filter}
    """)
    result = await session.execute(metrics_query, params)
    metrics_row = result.fetchone()

    attempted_yes = metrics_row.attempted_yes or 0
    attempted_no = metrics_row.attempted_no or 0
    attempted_uncertain = metrics_row.attempted_uncertain or 0
    accepted_count = metrics_row.accepted or 0
    rejected_count = metrics_row.rejected or 0
    unclear_count = metrics_row.unclear or 0

    # Calculate rates
    attempted_rate = attempted_yes / dialogues_analyzed if dialogues_analyzed > 0 else 0.0
    accepted_total = accepted_count + rejected_count
    accepted_rate = accepted_count / accepted_total if accepted_total > 0 else 0.0

    # Get top categories
    categories_query = text(f"""
        SELECT category, COUNT(*) as count
        FROM dialogues d
        JOIN dialogue_upsell_analysis dua ON d.dialogue_id = dua.dialogue_id,
        jsonb_array_elements_text(dua.categories) as category
        WHERE d.start_ts >= :date_start AND d.start_ts < :date_end
            AND d.analysis_status = 'DONE'
            {point_filter}
        GROUP BY category
        ORDER BY count DESC
        LIMIT 10
    """)
    result = await session.execute(categories_query, params)
    top_categories = [
        CategoryCount(category=row.category, count=row.count)
        for row in result.fetchall()
    ]

    # Get hourly breakdown
    hourly_query = text(f"""
        SELECT
            EXTRACT(HOUR FROM d.start_ts) as hour,
            COUNT(*) as dialogues_total,
            COUNT(*) FILTER (WHERE dua.attempted = 'yes') as attempted_yes,
            COUNT(*) FILTER (WHERE dua.attempted = 'no') as attempted_no,
            COUNT(*) FILTER (WHERE dua.attempted = 'uncertain') as attempted_uncertain,
            AVG(dua.quality_score) as avg_quality,
            COUNT(*) FILTER (WHERE dua.customer_reaction = 'accepted') as accepted,
            COUNT(*) FILTER (WHERE dua.customer_reaction = 'rejected') as rejected
        FROM dialogues d
        JOIN dialogue_upsell_analysis dua ON d.dialogue_id = dua.dialogue_id
        WHERE d.start_ts >= :date_start AND d.start_ts < :date_end
            AND d.analysis_status = 'DONE'
            {point_filter}
        GROUP BY EXTRACT(HOUR FROM d.start_ts)
        ORDER BY hour
    """)
    result = await session.execute(hourly_query, params)
    hourly = [
        HourlyStats(
            hour=int(row.hour),
            dialogues_total=row.dialogues_total,
            attempted_yes=row.attempted_yes or 0,
            attempted_no=row.attempted_no or 0,
            attempted_uncertain=row.attempted_uncertain or 0,
            avg_quality=float(row.avg_quality or 0),
            accepted_count=row.accepted or 0,
            rejected_count=row.rejected or 0,
        )
        for row in result.fetchall()
    ]

    return DailyAnalyticsResponse(
        date=date,
        point_id=point_id,
        dialogues_total=dialogues_total,
        dialogues_analyzed=dialogues_analyzed,
        dialogues_skipped=dialogues_skipped,
        dialogues_error=dialogues_error,
        attempted_yes=attempted_yes,
        attempted_no=attempted_no,
        attempted_uncertain=attempted_uncertain,
        attempted_rate=round(attempted_rate, 4),
        avg_quality=round(float(metrics_row.avg_quality or 0), 2),
        quality_distribution={
            0: metrics_row.quality_0 or 0,
            1: metrics_row.quality_1 or 0,
            2: metrics_row.quality_2 or 0,
            3: metrics_row.quality_3 or 0,
        },
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        unclear_count=unclear_count,
        accepted_rate=round(accepted_rate, 4),
        top_categories=top_categories,
        hourly=hourly,
    )


@router.get(
    "/dialogues",
    response_model=DialogueListResponse,
    dependencies=[Depends(get_current_user)],
)
async def get_dialogues_with_analysis(
    date: date = Query(..., description="Date in YYYY-MM-DD format"),
    point_id: UUID | None = Query(None, description="Filter by point_id"),
    min_quality: int | None = Query(None, ge=0, le=3, description="Minimum quality score"),
    attempted: str | None = Query(None, description="Filter by attempted: yes, no, uncertain"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_session),
) -> DialogueListResponse:
    """
    Get list of dialogues with their analysis.

    Returns dialogue details including quality score, categories, and summary.
    Optionally includes a text snippet from the transcript.
    """
    # Base date filter
    date_start = datetime.combine(date, datetime.min.time()).replace(tzinfo=timezone.utc)
    date_end = datetime.combine(date, datetime.max.time()).replace(tzinfo=timezone.utc)

    # Build filters
    filters = ["d.start_ts >= :date_start", "d.start_ts < :date_end", "d.analysis_status = 'DONE'"]
    params: dict[str, Any] = {
        "date_start": date_start,
        "date_end": date_end,
        "limit": limit,
        "offset": offset,
    }

    if point_id:
        filters.append("d.point_id = :point_id")
        params["point_id"] = point_id

    if min_quality is not None:
        filters.append("dua.quality_score >= :min_quality")
        params["min_quality"] = min_quality

    if attempted:
        filters.append("dua.attempted = :attempted")
        params["attempted"] = attempted

    where_clause = " AND ".join(filters)

    # Count total
    count_query = text(f"""
        SELECT COUNT(*)
        FROM dialogues d
        JOIN dialogue_upsell_analysis dua ON d.dialogue_id = dua.dialogue_id
        WHERE {where_clause}
    """)
    result = await session.execute(count_query, params)
    total = result.scalar() or 0

    # Get dialogues with analysis
    query = text(f"""
        SELECT
            d.dialogue_id,
            d.start_ts,
            d.end_ts,
            dua.quality_score,
            dua.attempted,
            dua.categories,
            dua.customer_reaction,
            dua.closing_question,
            dua.summary,
            LEFT(dt.text, 200) as text_snippet
        FROM dialogues d
        JOIN dialogue_upsell_analysis dua ON d.dialogue_id = dua.dialogue_id
        LEFT JOIN dialogue_transcripts dt ON d.dialogue_id = dt.dialogue_id
        WHERE {where_clause}
        ORDER BY d.start_ts DESC
        LIMIT :limit OFFSET :offset
    """)
    result = await session.execute(query, params)
    rows = result.fetchall()

    dialogues = [
        DialogueAnalysisSummary(
            dialogue_id=row.dialogue_id,
            start_ts=row.start_ts,
            end_ts=row.end_ts,
            quality_score=row.quality_score,
            attempted=row.attempted,
            categories=row.categories if isinstance(row.categories, list) else [],
            customer_reaction=row.customer_reaction,
            closing_question=row.closing_question,
            summary=row.summary,
            text_snippet=row.text_snippet,
        )
        for row in rows
    ]

    return DialogueListResponse(
        date=date,
        point_id=point_id,
        total=total,
        dialogues=dialogues,
    )


# =============================================================================
# Additional endpoints for dashboard
# =============================================================================


class PointInfo(BaseModel):
    """Information about a sales point."""

    point_id: UUID
    name: str | None = None
    dialogue_count: int


class PointsResponse(BaseModel):
    """List of points."""

    points: list[PointInfo]


class DialogueDetailResponse(BaseModel):
    """Detailed dialogue information including full transcript."""

    dialogue_id: UUID
    point_id: UUID
    register_id: UUID
    start_ts: datetime
    end_ts: datetime

    # Analysis
    quality_score: int
    attempted: str
    categories: list[str]
    customer_reaction: str
    closing_question: bool
    summary: str
    evidence_quotes: list[str]
    confidence: float | None

    # Review status
    review_status: str = "NONE"

    # Transcript
    text: str


@router.get(
    "/points",
    response_model=PointsResponse,
    dependencies=[Depends(get_current_user)],
)
async def get_points(
    days: int = Query(30, ge=1, le=365, description="Look back N days for points"),
    session: AsyncSession = Depends(get_session),
) -> PointsResponse:
    """
    Get list of sales points with dialogue counts.

    Returns distinct point_ids from dialogues within the last N days.
    """
    query = text("""
        SELECT
            d.point_id,
            COUNT(*) as dialogue_count
        FROM dialogues d
        WHERE d.start_ts >= NOW() - INTERVAL ':days days'
        GROUP BY d.point_id
        ORDER BY dialogue_count DESC
    """.replace(":days", str(days)))

    result = await session.execute(query)
    rows = result.fetchall()

    points = [
        PointInfo(
            point_id=row.point_id,
            name=None,  # No names stored currently
            dialogue_count=row.dialogue_count,
        )
        for row in rows
    ]

    return PointsResponse(points=points)


@router.get(
    "/dialogues/{dialogue_id}",
    response_model=DialogueDetailResponse,
    dependencies=[Depends(get_current_user)],
)
async def get_dialogue_detail(
    dialogue_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DialogueDetailResponse:
    """
    Get detailed information about a specific dialogue.

    Includes full transcript text and analysis with evidence quotes.
    """
    query = text("""
        SELECT
            d.dialogue_id,
            d.point_id,
            d.register_id,
            d.start_ts,
            d.end_ts,
            d.review_status,
            dua.quality_score,
            dua.attempted,
            dua.categories,
            dua.customer_reaction,
            dua.closing_question,
            dua.summary,
            dua.evidence_quotes,
            dua.confidence,
            dt.text
        FROM dialogues d
        JOIN dialogue_upsell_analysis dua ON d.dialogue_id = dua.dialogue_id
        LEFT JOIN dialogue_transcripts dt ON d.dialogue_id = dt.dialogue_id
        WHERE d.dialogue_id = :dialogue_id
    """)

    result = await session.execute(query, {"dialogue_id": dialogue_id})
    row = result.fetchone()

    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dialogue not found")

    return DialogueDetailResponse(
        dialogue_id=row.dialogue_id,
        point_id=row.point_id,
        register_id=row.register_id,
        start_ts=row.start_ts,
        end_ts=row.end_ts,
        quality_score=row.quality_score,
        attempted=row.attempted,
        categories=row.categories if isinstance(row.categories, list) else [],
        customer_reaction=row.customer_reaction,
        closing_question=row.closing_question,
        summary=row.summary,
        evidence_quotes=row.evidence_quotes if isinstance(row.evidence_quotes, list) else [],
        confidence=row.confidence,
        review_status=row.review_status or "NONE",
        text=row.text or "",
    )

"""Main entry point for analysis worker."""

import asyncio
import logging
import signal
import sys
from typing import Any
from uuid import UUID

from . import repository
from .db import check_db_connection, close_db, get_session
from .logging_setup import setup_logging
from .metrics import Timer, get_metrics, log_metrics
from .openai_client import analyze_dialogue
from .prefilter import check_should_skip
from .recovery import recover_stuck_dialogues
from .settings import get_settings

logger = logging.getLogger(__name__)

# Graceful shutdown flag
_shutdown_event = asyncio.Event()


def _handle_signal(signum: int, frame: Any) -> None:
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown")
    _shutdown_event.set()


async def process_dialogue(dialogue: dict[str, Any]) -> None:
    """
    Process a single dialogue: prefilter, analyze with LLM, save result.
    """
    settings = get_settings()
    metrics = get_metrics()
    dialogue_id = dialogue["dialogue_id"]

    logger.info(
        "Processing dialogue",
        extra={"dialogue_id": str(dialogue_id)},
    )

    # Get dialogue duration
    async with get_session() as session:
        duration_sec = await repository.get_dialogue_duration_sec(session, dialogue_id)

    # Check prefilter
    prefilter_result = check_should_skip(dialogue, duration_sec)

    if prefilter_result.should_skip:
        logger.info(
            "Dialogue skipped by prefilter",
            extra={
                "dialogue_id": str(dialogue_id),
                "skipped_reason": prefilter_result.reason,
            },
        )
        metrics.record_dialogue_skipped(prefilter_result.reason or "unknown")

        async with get_session() as session:
            # Save minimal analysis record
            await repository.save_skipped_analysis(
                session,
                dialogue_id=dialogue_id,
                reason=prefilter_result.reason or "prefilter",
            )
            # Update status to SKIPPED
            await repository.update_dialogue_analysis_status(
                session, dialogue_id, "SKIPPED"
            )
        return

    # Call LLM for analysis
    with Timer() as llm_timer:
        llm_result = analyze_dialogue(
            transcript_text=dialogue["transcript_text"],
            duration_sec=duration_sec,
            point_id=str(dialogue["point_id"]),
            register_id=str(dialogue["register_id"]),
        )

    # Save analysis to database
    async with get_session() as session:
        await repository.upsert_dialogue_analysis(
            session,
            dialogue_id=dialogue_id,
            attempted=llm_result.analysis.attempted,
            quality_score=llm_result.analysis.quality_score,
            categories=llm_result.analysis.categories,
            closing_question=llm_result.analysis.closing_question,
            customer_reaction=llm_result.analysis.customer_reaction,
            evidence_quotes=llm_result.analysis.evidence_quotes,
            summary=llm_result.analysis.summary,
            confidence=llm_result.analysis.confidence,
        )

        # Update dialogue status to DONE
        await repository.update_dialogue_analysis_status(
            session,
            dialogue_id=dialogue_id,
            status="DONE",
            model=llm_result.model,
            prompt_version=settings.prompt_version,
        )

    logger.info(
        "Dialogue analysis completed",
        extra={
            "dialogue_id": str(dialogue_id),
            "attempted": llm_result.analysis.attempted,
            "quality_score": llm_result.analysis.quality_score,
            "llm_latency_sec": round(llm_result.latency_sec, 3),
            "model": llm_result.model,
        },
    )


async def process_batch() -> int:
    """
    Fetch and process a batch of dialogues.
    Returns number of dialogues processed.
    """
    settings = get_settings()
    metrics = get_metrics()

    async with get_session() as session:
        dialogues = await repository.fetch_pending_dialogues(session, settings.batch_size)

        if not dialogues:
            return 0

        logger.info(f"Fetched {len(dialogues)} dialogues for analysis")

        # Mark all as PROCESSING
        for dialogue in dialogues:
            await repository.update_dialogue_analysis_status(
                session, dialogue["dialogue_id"], "PROCESSING"
            )

    # Process each dialogue (outside the batch transaction)
    processed = 0
    for dialogue in dialogues:
        dialogue_id = dialogue["dialogue_id"]
        try:
            with Timer() as total_timer:
                await process_dialogue(dialogue)

            # Record metrics for non-skipped dialogues
            # (skipped ones are recorded in process_dialogue)
            async with get_session() as session:
                # Check if it was actually processed (not skipped)
                # by checking if we have a real analysis
                pass  # Metrics are recorded in process_dialogue

            processed += 1

        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                "Failed to process dialogue",
                extra={
                    "dialogue_id": str(dialogue_id),
                    "error": str(e),
                    "error_type": error_type,
                },
                exc_info=True,
            )
            metrics.record_dialogue_error(error_type)
            async with get_session() as session:
                await repository.update_dialogue_analysis_status(
                    session, dialogue_id, "ERROR", str(e)[:1000]
                )

    return processed


async def recovery_loop() -> None:
    """Periodically recover stuck dialogues."""
    settings = get_settings()
    metrics = get_metrics()

    while not _shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                _shutdown_event.wait(),
                timeout=settings.analysis_recovery_interval_sec,
            )
            break  # Shutdown requested
        except asyncio.TimeoutError:
            pass

        try:
            requeued = await recover_stuck_dialogues()
            if requeued > 0:
                metrics.record_dialogues_requeued(requeued)
        except Exception as e:
            logger.error(f"Error in recovery loop: {e}", exc_info=True)


async def metrics_loop() -> None:
    """Periodically log metrics."""
    settings = get_settings()

    while not _shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                _shutdown_event.wait(),
                timeout=settings.metrics_log_interval_sec,
            )
            break  # Shutdown requested
        except asyncio.TimeoutError:
            pass

        try:
            log_metrics()
        except Exception as e:
            logger.error(f"Error logging metrics: {e}", exc_info=True)


async def run_worker() -> None:
    """Main worker loop."""
    settings = get_settings()

    logger.info(
        "Starting Analysis worker",
        extra={
            "poll_interval_sec": settings.poll_interval_sec,
            "batch_size": settings.batch_size,
            "openai_model": settings.openai_model,
            "prompt_version": settings.prompt_version,
            "prefilter_enabled": settings.prefilter_enabled,
            "analysis_stuck_timeout_sec": settings.analysis_stuck_timeout_sec,
        },
    )

    # Validate OpenAI API key is configured
    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY not configured")
        sys.exit(1)

    # Wait for database to be ready
    for attempt in range(30):
        if await check_db_connection():
            logger.info("Database connection established")
            break
        logger.warning(f"Database not ready, retrying in 2s (attempt {attempt + 1}/30)")
        await asyncio.sleep(2)
    else:
        logger.error("Could not connect to database after 30 attempts")
        sys.exit(1)

    # Start background tasks
    recovery_task = asyncio.create_task(recovery_loop())
    metrics_task = asyncio.create_task(metrics_loop())

    try:
        # Main processing loop
        while not _shutdown_event.is_set():
            try:
                processed = await process_batch()

                if processed == 0:
                    # No work - wait before polling again
                    try:
                        await asyncio.wait_for(
                            _shutdown_event.wait(),
                            timeout=settings.poll_interval_sec,
                        )
                    except asyncio.TimeoutError:
                        pass
                else:
                    # More work might be available - continue immediately
                    # But check for shutdown signal
                    if _shutdown_event.is_set():
                        break

            except Exception as e:
                logger.error(f"Error in worker loop: {e}", exc_info=True)
                # Wait before retrying to avoid tight error loop
                try:
                    await asyncio.wait_for(_shutdown_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass

    finally:
        # Cancel background tasks
        recovery_task.cancel()
        metrics_task.cancel()
        try:
            await asyncio.gather(recovery_task, metrics_task, return_exceptions=True)
        except Exception:
            pass

        # Final metrics log
        log_metrics()

    logger.info("Worker shutdown complete")


async def async_main() -> None:
    """Async entry point."""
    settings = get_settings()
    setup_logging(settings.log_level)

    try:
        await run_worker()
    finally:
        await close_db()


def main() -> None:
    """Main entry point."""
    # Set up signal handlers
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    asyncio.run(async_main())


if __name__ == "__main__":
    main()

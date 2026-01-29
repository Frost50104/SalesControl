"""Main entry point for VAD worker."""

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from . import repository
from .db import check_db_connection, close_db, get_session
from .dialogue_builder import process_chunk_dialogues
from .logging_setup import setup_logging
from .metrics import Timer, get_metrics, log_metrics
from .settings import get_settings
from .vad import run_vad

logger = logging.getLogger(__name__)

# Graceful shutdown flag
_shutdown_event = asyncio.Event()


def _handle_signal(signum: int, frame: Any) -> None:
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown")
    _shutdown_event.set()


async def process_chunk(chunk: dict[str, Any]) -> tuple[int, int]:
    """
    Process a single audio chunk: run VAD and build dialogues.
    Returns (segments_count, dialogues_count) for metrics.
    """
    settings = get_settings()
    chunk_id = chunk["chunk_id"]
    file_path = chunk["file_path"]
    metrics = get_metrics()

    # Build full file path
    full_path = Path(settings.audio_storage_dir) / file_path

    logger.info(
        "Processing chunk",
        extra={"chunk_id": str(chunk_id), "file_path": str(full_path)},
    )

    # Run VAD with retries and timing
    speech_segments = None
    last_error = None
    vad_time = 0.0

    for attempt in range(settings.max_retries):
        try:
            with Timer() as vad_timer:
                speech_segments = run_vad(str(full_path))
            vad_time = vad_timer.elapsed
            break
        except FileNotFoundError as e:
            last_error = e
            if attempt < settings.max_retries - 1:
                delay = settings.retry_delay_sec * (2**attempt)  # Exponential backoff
                logger.warning(
                    f"File not found, retrying in {delay}s",
                    extra={"chunk_id": str(chunk_id), "attempt": attempt + 1},
                )
                await asyncio.sleep(delay)
            else:
                raise
        except Exception as e:
            last_error = e
            logger.error(
                "VAD processing failed",
                extra={"chunk_id": str(chunk_id), "error": str(e)},
            )
            raise

    if speech_segments is None:
        raise last_error or Exception("VAD failed without error")

    logger.info(
        "VAD completed",
        extra={
            "chunk_id": str(chunk_id),
            "speech_segments": len(speech_segments),
            "vad_time_sec": round(vad_time, 3),
        },
    )

    # Save results and build dialogues
    dialogues_created = 0
    async with get_session() as session:
        # Save speech segments
        await repository.save_speech_segments(session, chunk_id, speech_segments)

        # Build/update dialogues (count is approximate, based on creates)
        # We'll track this better in the future
        await process_chunk_dialogues(session, chunk, speech_segments)

        # Mark as DONE
        await repository.update_chunk_status(session, chunk_id, "DONE")

    logger.info("Chunk processed successfully", extra={"chunk_id": str(chunk_id)})
    return len(speech_segments), dialogues_created


async def process_batch() -> int:
    """
    Fetch and process a batch of chunks.
    Returns number of chunks processed.
    """
    settings = get_settings()
    metrics = get_metrics()

    async with get_session() as session:
        chunks = await repository.fetch_queued_chunks(session, settings.batch_size)

        if not chunks:
            return 0

        logger.info(f"Fetched {len(chunks)} chunks for processing")

        # Mark all as PROCESSING
        for chunk in chunks:
            await repository.update_chunk_status(
                session, chunk["chunk_id"], "PROCESSING"
            )

    # Process each chunk (outside the batch transaction)
    processed = 0
    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        try:
            with Timer() as total_timer:
                segments_count, dialogues_count = await process_chunk(chunk)

            # Record successful metrics
            metrics.record_chunk_processed(
                vad_time_sec=0,  # Already captured in process_chunk
                total_time_sec=total_timer.elapsed,
                segments_count=segments_count,
                dialogues_count=dialogues_count,
            )
            processed += 1

        except FileNotFoundError as e:
            logger.error(
                "File not found for chunk",
                extra={"chunk_id": str(chunk_id), "error": str(e)},
            )
            metrics.record_chunk_error("FileNotFoundError")
            async with get_session() as session:
                await repository.update_chunk_status(
                    session, chunk_id, "ERROR", f"File not found: {e}"
                )

        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                "Failed to process chunk",
                extra={"chunk_id": str(chunk_id), "error": str(e), "error_type": error_type},
            )
            metrics.record_chunk_error(error_type)
            async with get_session() as session:
                await repository.update_chunk_status(
                    session, chunk_id, "ERROR", str(e)[:1000]
                )

    return processed


async def recovery_loop() -> None:
    """Periodically requeue stuck chunks."""
    settings = get_settings()
    metrics = get_metrics()

    while not _shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                _shutdown_event.wait(),
                timeout=settings.recovery_interval_sec,
            )
            break  # Shutdown requested
        except asyncio.TimeoutError:
            pass

        try:
            async with get_session() as session:
                requeued = await repository.requeue_stuck_chunks(
                    session, settings.stuck_timeout_sec
                )
                if requeued > 0:
                    metrics.record_chunks_requeued(requeued)
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
        "Starting VAD worker",
        extra={
            "poll_interval_sec": settings.poll_interval_sec,
            "batch_size": settings.batch_size,
            "vad_aggressiveness": settings.vad_aggressiveness,
            "silence_gap_sec": settings.silence_gap_sec,
            "max_dialogue_sec": settings.max_dialogue_sec,
            "stuck_timeout_sec": settings.stuck_timeout_sec,
            "recovery_interval_sec": settings.recovery_interval_sec,
            "metrics_log_interval_sec": settings.metrics_log_interval_sec,
        },
    )

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

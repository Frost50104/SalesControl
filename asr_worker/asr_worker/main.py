"""Main entry point for ASR worker."""

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from . import repository
from .audio_assembler import (
    assemble_dialogue_audio,
    cleanup_assembled_audio,
    prepare_dialogue_segments,
)
from .audio_fetcher import cleanup_chunk_cache, fetch_chunk_file, AudioFetchError
from .db import check_db_connection, close_db, get_session
from .heuristics import check_needs_accurate_pass
from .logging_setup import setup_logging
from .metrics import Timer, get_metrics, log_metrics
from .recovery import recover_stuck_dialogues
from .settings import get_settings
from .transcribe import transcribe_audio, preload_models

logger = logging.getLogger(__name__)

# Graceful shutdown flag
_shutdown_event = asyncio.Event()


def _handle_signal(signum: int, frame: Any) -> None:
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown")
    _shutdown_event.set()


async def process_dialogue(
    dialogue: dict[str, Any],
    http_client: httpx.AsyncClient,
) -> tuple[float, str]:
    """
    Process a single dialogue: fetch audio, transcribe, save result.

    Returns (audio_duration_sec, pass_type).
    """
    settings = get_settings()
    dialogue_id = dialogue["dialogue_id"]

    logger.info(
        "Processing dialogue",
        extra={"dialogue_id": str(dialogue_id)},
    )

    # 1. Get dialogue segments from database
    async with get_session() as session:
        segments = await repository.get_dialogue_segments(session, dialogue_id)

    if not segments:
        raise ValueError(f"No segments found for dialogue {dialogue_id}")

    # 2. Get unique chunk IDs and fetch them
    unique_chunk_ids = list({seg["chunk_id"] for seg in segments})
    chunk_paths: dict[UUID, Path] = {}

    for chunk_id in unique_chunk_ids:
        path = await fetch_chunk_file(chunk_id, http_client)
        chunk_paths[chunk_id] = path

    # 3. Prepare and assemble audio segments
    segment_infos = prepare_dialogue_segments(segments, chunk_paths)
    audio_path, audio_duration_sec = assemble_dialogue_audio(segment_infos)

    try:
        # 4. Fast pass transcription
        with Timer() as fast_timer:
            fast_result = transcribe_audio(audio_path, model_type="fast")

        # 5. Check if accurate pass is needed
        decision = check_needs_accurate_pass(fast_result, audio_duration_sec)

        if decision.needs_accurate_pass:
            # 6. Accurate pass transcription
            with Timer() as accurate_timer:
                final_result = transcribe_audio(audio_path, model_type="accurate")
            asr_time = accurate_timer.elapsed
            pass_type = "accurate"
        else:
            final_result = fast_result
            asr_time = fast_timer.elapsed
            pass_type = "fast"

        # Calculate RTF for this dialogue
        rtf = asr_time / audio_duration_sec if audio_duration_sec > 0 else 0

        logger.info(
            "Transcription completed",
            extra={
                "dialogue_id": str(dialogue_id),
                "pass_type": pass_type,
                "model": final_result.model_name,
                "asr_time_sec": round(asr_time, 3),
                "audio_duration_sec": round(audio_duration_sec, 2),
                "rtf": round(rtf, 3),
                "text_length": len(final_result.text),
            },
        )

        # 7. Save transcript to database
        async with get_session() as session:
            await repository.upsert_dialogue_transcript(
                session,
                dialogue_id=dialogue_id,
                language=final_result.language,
                text_content=final_result.text,
                segments_json=final_result.segments,
                avg_logprob=final_result.avg_logprob,
                no_speech_prob=final_result.no_speech_prob,
            )

            # 8. Update dialogue status to DONE
            await repository.update_dialogue_asr_status(
                session,
                dialogue_id=dialogue_id,
                status="DONE",
                asr_pass=pass_type,
                asr_model=final_result.model_name,
            )

        return audio_duration_sec, pass_type

    finally:
        # Clean up assembled audio
        cleanup_assembled_audio(audio_path)
        # Clean up chunk cache for this dialogue's chunks
        cleanup_chunk_cache(unique_chunk_ids)


async def process_batch(http_client: httpx.AsyncClient) -> int:
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

        logger.info(f"Fetched {len(dialogues)} dialogues for ASR processing")

        # Mark all as PROCESSING
        for dialogue in dialogues:
            await repository.update_dialogue_asr_status(
                session, dialogue["dialogue_id"], "PROCESSING"
            )

    # Process each dialogue (outside the batch transaction)
    processed = 0
    for dialogue in dialogues:
        dialogue_id = dialogue["dialogue_id"]
        try:
            with Timer() as total_timer:
                audio_duration_sec, pass_type = await process_dialogue(
                    dialogue, http_client
                )

            # Record successful metrics
            metrics.record_dialogue_processed(
                asr_time_sec=total_timer.elapsed,  # Total includes fetching/assembly
                total_time_sec=total_timer.elapsed,
                audio_duration_sec=audio_duration_sec,
                pass_type=pass_type,
            )
            processed += 1

        except AudioFetchError as e:
            logger.error(
                "Failed to fetch audio for dialogue",
                extra={"dialogue_id": str(dialogue_id), "error": str(e)},
            )
            metrics.record_dialogue_error("AudioFetchError")
            async with get_session() as session:
                await repository.update_dialogue_asr_status(
                    session, dialogue_id, "ERROR", f"Audio fetch failed: {e}"
                )

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
                await repository.update_dialogue_asr_status(
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
                timeout=settings.asr_recovery_interval_sec,
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
        "Starting ASR worker",
        extra={
            "poll_interval_sec": settings.poll_interval_sec,
            "batch_size": settings.batch_size,
            "whisper_model_fast": settings.whisper_model_fast,
            "whisper_model_accurate": settings.whisper_model_accurate,
            "whisper_compute_type": settings.whisper_compute_type,
            "whisper_threads": settings.whisper_threads,
            "asr_stuck_timeout_sec": settings.asr_stuck_timeout_sec,
            "ingest_internal_base_url": settings.ingest_internal_base_url,
        },
    )

    # Validate internal token is configured
    if not settings.internal_token:
        logger.error("INTERNAL_TOKEN not configured, cannot fetch audio from ingest_api")
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

    # Preload Whisper models
    logger.info("Preloading Whisper models...")
    preload_models()

    # Create HTTP client for fetching audio
    http_client = httpx.AsyncClient(timeout=settings.http_timeout_sec)

    # Start background tasks
    recovery_task = asyncio.create_task(recovery_loop())
    metrics_task = asyncio.create_task(metrics_loop())

    try:
        # Main processing loop
        while not _shutdown_event.is_set():
            try:
                processed = await process_batch(http_client)

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
        # Close HTTP client
        await http_client.aclose()

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

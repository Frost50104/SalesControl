#!/usr/bin/env python3
"""
End-to-end test for VAD worker.

Creates test audio files with speech patterns and verifies:
1. Chunks are processed (QUEUED -> DONE)
2. Speech segments are detected
3. Dialogues are built
4. Cross-chunk dialogue continuity works
"""

import asyncio
import os
import struct
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from pydub import AudioSegment
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://ingest:ingest@localhost:5432/ingest"
)
AUDIO_STORAGE_DIR = os.getenv(
    "AUDIO_STORAGE_DIR",
    "/home/petr/PycharmProjects/SalesСontrol/infra/audio_storage"
)

SAMPLE_RATE = 48000
CHANNELS = 1


def generate_tone(duration_ms: int, frequency: int = 440, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Generate a sine wave tone (simulates speech for VAD)."""
    num_samples = int(sample_rate * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, num_samples, False)
    # Add some harmonics and noise to make it more speech-like
    wave = (
        0.5 * np.sin(2 * np.pi * frequency * t) +
        0.3 * np.sin(2 * np.pi * frequency * 2 * t) +
        0.1 * np.sin(2 * np.pi * frequency * 3 * t) +
        0.05 * np.random.randn(num_samples)
    )
    wave = (wave * 32767 * 0.8).astype(np.int16)
    return wave.tobytes()


def generate_silence(duration_ms: int, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Generate silence with very low noise."""
    num_samples = int(sample_rate * duration_ms / 1000)
    # Very quiet noise (won't trigger VAD)
    wave = (np.random.randn(num_samples) * 50).astype(np.int16)
    return wave.tobytes()


def create_test_audio(pattern: list[tuple[str, int]], sample_rate: int = SAMPLE_RATE) -> AudioSegment:
    """
    Create test audio from pattern.

    Pattern is list of tuples: [("speech", 2000), ("silence", 3000), ...]
    """
    audio_data = b""
    for segment_type, duration_ms in pattern:
        if segment_type == "speech":
            audio_data += generate_tone(duration_ms, frequency=300 + np.random.randint(0, 200))
        else:
            audio_data += generate_silence(duration_ms)

    return AudioSegment(
        data=audio_data,
        sample_width=2,
        frame_rate=sample_rate,
        channels=1,
    )


async def setup_test_device(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create test device and return (device_id, point_id, register_id)."""
    device_id = uuid.uuid4()
    point_id = uuid.uuid4()
    register_id = uuid.uuid4()

    # Hash of "test-token"
    token_hash = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"

    await session.execute(text("""
        INSERT INTO devices (device_id, point_id, register_id, token_hash, is_enabled)
        VALUES (:device_id, :point_id, :register_id, :token_hash, true)
        ON CONFLICT (device_id) DO NOTHING
    """), {
        "device_id": device_id,
        "point_id": point_id,
        "register_id": register_id,
        "token_hash": token_hash,
    })

    return device_id, point_id, register_id


async def create_test_chunks(
    session: AsyncSession,
    device_id: uuid.UUID,
    point_id: uuid.UUID,
    register_id: uuid.UUID,
    audio_storage_dir: str,
) -> list[uuid.UUID]:
    """
    Create test audio chunks that test cross-chunk dialogue continuity.

    Scenario:
    - Chunk 1 (60s): Speech at 0-5s, 10-15s, 50-58s (dialogue continues at end)
    - Chunk 2 (60s): Speech at 2-10s, 40-45s (should join with chunk1 end)
    - Chunk 3 (60s): Speech at 30-35s (new dialogue after >12s gap)

    Expected dialogues:
    1. Chunk1 speech at 0-5s + 10-15s (small gaps)
    2. Chunk1 50-58s + Chunk2 2-10s (cross-chunk, gap < 12s)
    3. Chunk2 40-45s (standalone)
    4. Chunk3 30-35s (new dialogue after long gap)
    """
    chunks = []
    base_time = datetime(2026, 1, 29, 10, 0, 0, tzinfo=timezone.utc)

    # Chunk 1 pattern: speech periods with cross-chunk continuation at end
    chunk1_pattern = [
        ("speech", 5000),    # 0-5s: speech
        ("silence", 5000),   # 5-10s: silence
        ("speech", 5000),    # 10-15s: speech
        ("silence", 35000),  # 15-50s: long silence (>12s, new dialogue)
        ("speech", 8000),    # 50-58s: speech (will continue to chunk2)
        ("silence", 2000),   # 58-60s: short silence at end
    ]

    # Chunk 2 pattern: continues from chunk1, then new dialogue
    chunk2_pattern = [
        ("silence", 2000),   # 0-2s: silence (gap from chunk1 = 2+2 = 4s < 12s)
        ("speech", 8000),    # 2-10s: speech (continues dialogue from chunk1)
        ("silence", 30000),  # 10-40s: long silence (>12s)
        ("speech", 5000),    # 40-45s: new dialogue
        ("silence", 15000),  # 45-60s: silence at end (>12s gap)
    ]

    # Chunk 3 pattern: standalone dialogue after long gap
    chunk3_pattern = [
        ("silence", 30000),  # 0-30s: silence (gap from chunk2 = 15+30 = 45s >> 12s)
        ("speech", 5000),    # 30-35s: new dialogue
        ("silence", 25000),  # 35-60s: silence
    ]

    patterns = [chunk1_pattern, chunk2_pattern, chunk3_pattern]

    for i, pattern in enumerate(patterns):
        chunk_id = uuid.uuid4()
        start_ts = base_time + timedelta(seconds=i * 60)
        end_ts = start_ts + timedelta(seconds=60)

        # Create audio file
        audio = create_test_audio(pattern)

        # Save to storage
        date_str = start_ts.strftime("%Y-%m-%d")
        hour_str = start_ts.strftime("%H")
        relative_path = f"audio/{point_id}/{register_id}/{date_str}/{hour_str}/chunk_{start_ts.strftime('%Y%m%d_%H%M%S')}_{chunk_id}.ogg"
        full_path = Path(audio_storage_dir) / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Export as OGG
        audio.export(str(full_path), format="ogg", codec="libopus")
        file_size = full_path.stat().st_size

        # Insert chunk record
        await session.execute(text("""
            INSERT INTO audio_chunks (
                chunk_id, device_id, point_id, register_id,
                start_ts, end_ts, duration_sec,
                codec, sample_rate, channels,
                file_path, file_size_bytes, status
            ) VALUES (
                :chunk_id, :device_id, :point_id, :register_id,
                :start_ts, :end_ts, :duration_sec,
                :codec, :sample_rate, :channels,
                :file_path, :file_size_bytes, 'QUEUED'
            )
        """), {
            "chunk_id": chunk_id,
            "device_id": device_id,
            "point_id": point_id,
            "register_id": register_id,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "duration_sec": 60,
            "codec": "opus",
            "sample_rate": SAMPLE_RATE,
            "channels": CHANNELS,
            "file_path": relative_path,
            "file_size_bytes": file_size,
        })

        chunks.append(chunk_id)
        print(f"Created chunk {i+1}: {chunk_id}")
        print(f"  File: {full_path} ({file_size} bytes)")

    return chunks


async def check_results(session: AsyncSession, chunk_ids: list[uuid.UUID]) -> dict:
    """Check processing results."""
    results = {
        "chunks_processed": 0,
        "chunks_error": 0,
        "speech_segments": 0,
        "dialogues": 0,
        "cross_chunk_dialogues": 0,
    }

    # Check chunk statuses
    for chunk_id in chunk_ids:
        result = await session.execute(text("""
            SELECT status, error_message FROM audio_chunks WHERE chunk_id = :chunk_id
        """), {"chunk_id": chunk_id})
        row = result.fetchone()
        if row:
            if row.status == "DONE":
                results["chunks_processed"] += 1
            elif row.status == "ERROR":
                results["chunks_error"] += 1
                print(f"  Chunk {chunk_id} ERROR: {row.error_message}")

    # Count speech segments
    result = await session.execute(text("""
        SELECT COUNT(*) FROM speech_segments WHERE chunk_id = ANY(:chunk_ids)
    """), {"chunk_ids": chunk_ids})
    results["speech_segments"] = result.scalar()

    # Count dialogues
    result = await session.execute(text("""
        SELECT COUNT(DISTINCT dialogue_id) FROM dialogue_segments WHERE chunk_id = ANY(:chunk_ids)
    """), {"chunk_ids": chunk_ids})
    results["dialogues"] = result.scalar()

    # Check for cross-chunk dialogues (dialogues with segments from multiple chunks)
    result = await session.execute(text("""
        SELECT dialogue_id, COUNT(DISTINCT chunk_id) as chunk_count
        FROM dialogue_segments
        WHERE chunk_id = ANY(:chunk_ids)
        GROUP BY dialogue_id
        HAVING COUNT(DISTINCT chunk_id) > 1
    """), {"chunk_ids": chunk_ids})
    cross_chunk = result.fetchall()
    results["cross_chunk_dialogues"] = len(cross_chunk)

    return results


async def print_detailed_results(session: AsyncSession, chunk_ids: list[uuid.UUID]):
    """Print detailed results for debugging."""
    print("\n" + "="*60)
    print("DETAILED RESULTS")
    print("="*60)

    # Chunks
    print("\n--- Chunks ---")
    result = await session.execute(text("""
        SELECT chunk_id, start_ts, status, error_message
        FROM audio_chunks
        WHERE chunk_id = ANY(:chunk_ids)
        ORDER BY start_ts
    """), {"chunk_ids": chunk_ids})
    for row in result.fetchall():
        print(f"  {row.chunk_id}: {row.start_ts} -> {row.status}")
        if row.error_message:
            print(f"    ERROR: {row.error_message[:100]}")

    # Speech segments
    print("\n--- Speech Segments ---")
    result = await session.execute(text("""
        SELECT c.start_ts, s.chunk_id, s.start_ms, s.end_ms, (s.end_ms - s.start_ms) as duration_ms
        FROM speech_segments s
        JOIN audio_chunks c ON c.chunk_id = s.chunk_id
        WHERE s.chunk_id = ANY(:chunk_ids)
        ORDER BY c.start_ts, s.start_ms
    """), {"chunk_ids": chunk_ids})
    for row in result.fetchall():
        print(f"  Chunk {str(row.chunk_id)[:8]}... @ {row.start_ms}-{row.end_ms}ms ({row.duration_ms}ms)")

    # Dialogues
    print("\n--- Dialogues ---")
    result = await session.execute(text("""
        SELECT d.dialogue_id, d.start_ts, d.end_ts,
               EXTRACT(EPOCH FROM (d.end_ts - d.start_ts)) as duration_sec
        FROM dialogues d
        WHERE d.dialogue_id IN (
            SELECT DISTINCT dialogue_id FROM dialogue_segments WHERE chunk_id = ANY(:chunk_ids)
        )
        ORDER BY d.start_ts
    """), {"chunk_ids": chunk_ids})
    dialogues = result.fetchall()

    for row in dialogues:
        print(f"\n  Dialogue {str(row.dialogue_id)[:8]}...")
        print(f"    Time: {row.start_ts} -> {row.end_ts} ({row.duration_sec:.1f}s)")

        # Get segments for this dialogue
        seg_result = await session.execute(text("""
            SELECT ds.chunk_id, ds.start_ms, ds.end_ms, c.start_ts as chunk_start
            FROM dialogue_segments ds
            JOIN audio_chunks c ON c.chunk_id = ds.chunk_id
            WHERE ds.dialogue_id = :dialogue_id
            ORDER BY c.start_ts, ds.start_ms
        """), {"dialogue_id": row.dialogue_id})
        segments = seg_result.fetchall()

        chunk_ids_in_dialogue = set()
        for seg in segments:
            chunk_ids_in_dialogue.add(seg.chunk_id)
            print(f"      Chunk {str(seg.chunk_id)[:8]}... @ {seg.start_ms}-{seg.end_ms}ms")

        if len(chunk_ids_in_dialogue) > 1:
            print(f"    ** CROSS-CHUNK DIALOGUE ** ({len(chunk_ids_in_dialogue)} chunks)")


async def main():
    print("="*60)
    print("VAD WORKER END-TO-END TEST")
    print("="*60)

    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # Setup
        print("\n[1] Creating test device...")
        device_id, point_id, register_id = await setup_test_device(session)
        print(f"  Device: {device_id}")
        print(f"  Point: {point_id}")
        print(f"  Register: {register_id}")

        # Create test chunks
        print("\n[2] Creating test audio chunks...")
        chunk_ids = await create_test_chunks(
            session, device_id, point_id, register_id, AUDIO_STORAGE_DIR
        )
        await session.commit()

        print(f"\n[3] Created {len(chunk_ids)} chunks with status QUEUED")
        print("    Run the VAD worker to process them:")
        print(f"    DATABASE_URL={DATABASE_URL} \\")
        print(f"    AUDIO_STORAGE_DIR={AUDIO_STORAGE_DIR} \\")
        print("    python -m vad_worker.main")
        print("\n    Or wait for the worker if it's already running...")

        # Poll for completion
        print("\n[4] Waiting for processing (max 60s)...")
        for i in range(60):
            result = await session.execute(text("""
                SELECT COUNT(*) FROM audio_chunks
                WHERE chunk_id = ANY(:chunk_ids) AND status = 'QUEUED'
            """), {"chunk_ids": chunk_ids})
            queued = result.scalar()

            if queued == 0:
                print(f"    All chunks processed after {i+1}s")
                break

            print(f"    {queued} chunks still QUEUED... ({i+1}s)")
            await asyncio.sleep(1)
            await session.commit()  # Refresh
        else:
            print("    Timeout! Some chunks still not processed.")

        # Check results
        print("\n[5] Checking results...")
        results = await check_results(session, chunk_ids)

        print(f"\n{'='*60}")
        print("SUMMARY")
        print("="*60)
        print(f"  Chunks processed: {results['chunks_processed']}/{len(chunk_ids)}")
        print(f"  Chunks with errors: {results['chunks_error']}")
        print(f"  Speech segments detected: {results['speech_segments']}")
        print(f"  Dialogues created: {results['dialogues']}")
        print(f"  Cross-chunk dialogues: {results['cross_chunk_dialogues']}")

        # Print detailed results
        await print_detailed_results(session, chunk_ids)

        # Validate expectations
        print("\n" + "="*60)
        print("VALIDATION")
        print("="*60)

        success = True

        if results['chunks_processed'] != len(chunk_ids):
            print(f"  FAIL: Not all chunks processed ({results['chunks_processed']}/{len(chunk_ids)})")
            success = False
        else:
            print(f"  OK: All {len(chunk_ids)} chunks processed")

        if results['speech_segments'] < 5:
            print(f"  FAIL: Too few speech segments ({results['speech_segments']}, expected >= 5)")
            success = False
        else:
            print(f"  OK: Found {results['speech_segments']} speech segments")

        if results['dialogues'] < 2:
            print(f"  FAIL: Too few dialogues ({results['dialogues']}, expected >= 2)")
            success = False
        else:
            print(f"  OK: Found {results['dialogues']} dialogues")

        if results['cross_chunk_dialogues'] < 1:
            print(f"  FAIL: No cross-chunk dialogues found (expected >= 1)")
            success = False
        else:
            print(f"  OK: Found {results['cross_chunk_dialogues']} cross-chunk dialogue(s)")

        print("\n" + "="*60)
        if success:
            print("ALL TESTS PASSED!")
        else:
            print("SOME TESTS FAILED!")
        print("="*60)

        return 0 if success else 1

    await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

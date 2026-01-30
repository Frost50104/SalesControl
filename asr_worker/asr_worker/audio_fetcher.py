"""Audio chunk fetcher - downloads chunks from ingest_api internal endpoint."""

import logging
from pathlib import Path
from uuid import UUID

import aiofiles
import httpx

from .settings import get_settings

logger = logging.getLogger(__name__)


class AudioFetchError(Exception):
    """Error fetching audio from ingest_api."""
    pass


async def fetch_chunk_file(
    chunk_id: UUID,
    client: httpx.AsyncClient,
) -> Path:
    """
    Download audio chunk from ingest_api internal endpoint.
    Caches to local file in AUDIO_TMP_DIR/chunks/{chunk_id}.ogg.

    Returns path to downloaded file.
    """
    settings = get_settings()

    # Check cache first
    cache_dir = Path(settings.audio_tmp_dir) / "chunks"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{chunk_id}.ogg"

    if cache_path.exists():
        logger.debug(f"Chunk {chunk_id} found in cache")
        return cache_path

    # Download from ingest_api
    url = f"{settings.ingest_internal_base_url}/api/v1/internal/chunks/{chunk_id}/file"
    headers = {"Authorization": f"Bearer {settings.internal_token}"}

    try:
        response = await client.get(url, headers=headers, timeout=settings.http_timeout_sec)
        response.raise_for_status()

        # Write to temp file first, then rename
        temp_path = cache_path.with_suffix(".tmp")
        async with aiofiles.open(temp_path, "wb") as f:
            await f.write(response.content)

        temp_path.rename(cache_path)

        logger.info(
            "Downloaded chunk",
            extra={
                "chunk_id": str(chunk_id),
                "file_size": len(response.content),
            },
        )
        return cache_path

    except httpx.HTTPStatusError as e:
        logger.error(
            "HTTP error fetching chunk",
            extra={
                "chunk_id": str(chunk_id),
                "status_code": e.response.status_code,
                "error": str(e),
            },
        )
        raise AudioFetchError(f"HTTP {e.response.status_code} fetching chunk {chunk_id}") from e
    except httpx.RequestError as e:
        logger.error(
            "Request error fetching chunk",
            extra={"chunk_id": str(chunk_id), "error": str(e)},
        )
        raise AudioFetchError(f"Request error fetching chunk {chunk_id}: {e}") from e


async def prefetch_chunks(
    chunk_ids: list[UUID],
    client: httpx.AsyncClient,
) -> dict[UUID, Path]:
    """
    Prefetch multiple chunks concurrently.
    Returns mapping of chunk_id to local file path.
    """
    results = {}
    for chunk_id in chunk_ids:
        try:
            path = await fetch_chunk_file(chunk_id, client)
            results[chunk_id] = path
        except AudioFetchError as e:
            logger.error(f"Failed to prefetch chunk {chunk_id}: {e}")
            raise
    return results


def cleanup_chunk_cache(chunk_ids: list[UUID]) -> int:
    """
    Remove cached chunk files.
    Returns count of removed files.
    """
    settings = get_settings()
    cache_dir = Path(settings.audio_tmp_dir) / "chunks"

    removed = 0
    for chunk_id in chunk_ids:
        cache_path = cache_dir / f"{chunk_id}.ogg"
        if cache_path.exists():
            try:
                cache_path.unlink()
                removed += 1
            except OSError as e:
                logger.warning(f"Failed to remove cached chunk {chunk_id}: {e}")

    return removed


def cleanup_all_cache() -> int:
    """
    Remove all cached chunk files.
    Returns count of removed files.
    """
    settings = get_settings()
    cache_dir = Path(settings.audio_tmp_dir) / "chunks"

    if not cache_dir.exists():
        return 0

    removed = 0
    for path in cache_dir.glob("*.ogg"):
        try:
            path.unlink()
            removed += 1
        except OSError as e:
            logger.warning(f"Failed to remove cached file {path}: {e}")

    return removed

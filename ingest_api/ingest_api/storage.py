"""File storage management for audio chunks."""

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

import aiofiles
import aiofiles.os

from .settings import get_settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Storage operation failed."""

    pass


def get_chunk_path(
    point_id: UUID,
    register_id: UUID,
    start_ts: datetime,
    chunk_id: UUID,
) -> str:
    """
    Generate relative path for audio chunk.

    Format: audio/<point_id>/<register_id>/<YYYY-MM-DD>/<HH>/chunk_<start_ts>_<chunk_id>.ogg
    """
    date_str = start_ts.strftime("%Y-%m-%d")
    hour_str = start_ts.strftime("%H")
    ts_str = start_ts.strftime("%Y%m%d_%H%M%S")

    return (
        f"audio/{point_id}/{register_id}/{date_str}/{hour_str}/"
        f"chunk_{ts_str}_{chunk_id}.ogg"
    )


async def save_chunk_file(
    content: bytes,
    relative_path: str,
) -> tuple[str, int]:
    """
    Save audio chunk to storage atomically.

    Args:
        content: File content bytes
        relative_path: Relative path within storage dir

    Returns:
        Tuple of (full_path, file_size_bytes)

    Raises:
        StorageError: If save fails
    """
    settings = get_settings()
    base_dir = Path(settings.audio_storage_dir)
    full_path = base_dir / relative_path
    dir_path = full_path.parent

    try:
        # Ensure directory exists
        await aiofiles.os.makedirs(dir_path, exist_ok=True)

        # Write to temp file first, then rename atomically
        fd, temp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix="chunk_",
            dir=dir_path,
        )
        os.close(fd)

        try:
            async with aiofiles.open(temp_path, "wb") as f:
                await f.write(content)

            # Atomic rename
            await aiofiles.os.rename(temp_path, full_path)

            file_size = len(content)
            logger.info(
                "chunk_file_saved",
                extra={
                    "path": relative_path,
                    "size_bytes": file_size,
                },
            )
            return str(full_path), file_size

        except Exception:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    except Exception as e:
        logger.error(
            "chunk_file_save_failed",
            extra={"path": relative_path, "error": str(e)},
        )
        raise StorageError(f"Failed to save chunk: {e}") from e


async def check_storage_writable() -> bool:
    """Check if storage directory is writable."""
    settings = get_settings()
    base_dir = Path(settings.audio_storage_dir)

    try:
        # Ensure base dir exists
        await aiofiles.os.makedirs(base_dir, exist_ok=True)

        # Try to write a test file
        test_file = base_dir / ".write_test"
        async with aiofiles.open(test_file, "w") as f:
            await f.write("test")
        await aiofiles.os.remove(test_file)
        return True

    except Exception as e:
        logger.error(
            "storage_write_check_failed",
            extra={"dir": str(base_dir), "error": str(e)},
        )
        return False


async def delete_chunk_file(file_path: str) -> bool:
    """Delete a chunk file from storage."""
    try:
        if await aiofiles.os.path.exists(file_path):
            await aiofiles.os.remove(file_path)
            logger.info("chunk_file_deleted", extra={"path": file_path})
            return True
        return False
    except Exception as e:
        logger.error(
            "chunk_file_delete_failed",
            extra={"path": file_path, "error": str(e)},
        )
        return False

"""Tests for spool janitor (retention by age and size)."""

import os
import time
from pathlib import Path

import pytest

from recorder_agent.spool import SpoolJanitor


@pytest.fixture
def spool_dir(tmp_path: Path) -> Path:
    d = tmp_path / "spool"
    d.mkdir()
    (d / "outbox").mkdir()
    (d / "uploaded").mkdir()
    return d


def _create_ogg(directory: Path, name: str, size: int = 1024, age_s: float = 0) -> Path:
    """Create a fake .ogg file with a specific size and mtime."""
    p = directory / name
    p.write_bytes(b"\x00" * size)
    if age_s > 0:
        mtime = time.time() - age_s
        os.utime(p, (mtime, mtime))
    return p


class TestSpoolJanitor:
    def test_delete_expired_files(self, spool_dir: Path) -> None:
        outbox = spool_dir / "outbox"
        # file older than 1 day
        _create_ogg(outbox, "chunk_old.ogg", age_s=2 * 86400)
        # recent file
        _create_ogg(outbox, "chunk_new.ogg", age_s=0)

        janitor = SpoolJanitor(spool_dir, max_days=1, max_gb=100)
        stats = janitor.run_once()

        assert stats["deleted_by_age"] == 1
        assert not (outbox / "chunk_old.ogg").exists()
        assert (outbox / "chunk_new.ogg").exists()

    def test_enforce_size_limit(self, spool_dir: Path) -> None:
        outbox = spool_dir / "outbox"
        # create 5 files of 1KB each
        for i in range(5):
            _create_ogg(outbox, f"chunk_{i:04d}.ogg", size=1024, age_s=5 - i)

        # limit to 3KB → should delete 2 oldest
        janitor = SpoolJanitor(spool_dir, max_days=999, max_gb=3 * 1024 / (1024**3))
        stats = janitor.run_once()

        assert stats["deleted_by_size"] == 2
        remaining = list(outbox.glob("*.ogg"))
        assert len(remaining) == 3

    def test_total_size(self, spool_dir: Path) -> None:
        outbox = spool_dir / "outbox"
        _create_ogg(outbox, "a.ogg", size=500)
        _create_ogg(outbox, "b.ogg", size=700)

        janitor = SpoolJanitor(spool_dir, max_days=999, max_gb=100)
        assert janitor.total_size_bytes() == 1200

    def test_total_files(self, spool_dir: Path) -> None:
        outbox = spool_dir / "outbox"
        for i in range(3):
            _create_ogg(outbox, f"f{i}.ogg")

        janitor = SpoolJanitor(spool_dir, max_days=999, max_gb=100)
        assert janitor.total_files() == 3

    def test_no_files(self, spool_dir: Path) -> None:
        janitor = SpoolJanitor(spool_dir, max_days=1, max_gb=1)
        stats = janitor.run_once()
        assert stats["deleted_by_age"] == 0
        assert stats["deleted_by_size"] == 0

    def test_both_policies(self, spool_dir: Path) -> None:
        """Files can be deleted by both age and size policies."""
        uploaded = spool_dir / "uploaded"
        _create_ogg(uploaded, "chunk_ancient.ogg", size=2048, age_s=30 * 86400)
        _create_ogg(uploaded, "chunk_recent.ogg", size=2048, age_s=0)

        janitor = SpoolJanitor(spool_dir, max_days=7, max_gb=100)
        stats = janitor.run_once()
        assert stats["deleted_by_age"] == 1

"""Tests for the uploader: timestamp parsing, queue logic, HTTP upload."""

from pathlib import Path

import pytest

from recorder_agent.uploader import Uploader


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    outbox = tmp_path / "outbox"
    uploaded = tmp_path / "uploaded"
    outbox.mkdir()
    uploaded.mkdir()
    return outbox, uploaded


def _make_uploader(outbox: Path, uploaded: Path, **kwargs) -> Uploader:
    defaults = dict(
        outbox_dir=outbox,
        uploaded_dir=uploaded,
        ingest_url="https://audio.example.com",
        ingest_token="test-token",
        point_id="00000000-0000-0000-0000-000000000001",
        register_id="00000000-0000-0000-0000-000000000002",
        device_id="00000000-0000-0000-0000-000000000003",
        chunk_seconds=60,
        sample_rate=48000,
    )
    defaults.update(kwargs)
    return Uploader(**defaults)


class TestTimestampParsing:
    def test_valid_filename(self, dirs: tuple[Path, Path]) -> None:
        outbox, uploaded = dirs
        up = _make_uploader(outbox, uploaded)
        p = outbox / "chunk_20240115_143022.ogg"
        p.write_bytes(b"\x00")

        start, end = up._parse_timestamps(p)
        assert start == "2024-01-15T14:30:22"
        assert end == "2024-01-15T14:31:22"

    def test_invalid_filename(self, dirs: tuple[Path, Path]) -> None:
        outbox, uploaded = dirs
        up = _make_uploader(outbox, uploaded)
        p = outbox / "random_file.ogg"
        p.write_bytes(b"\x00")

        start, end = up._parse_timestamps(p)
        assert start is None
        assert end is None

    def test_custom_chunk_seconds(self, dirs: tuple[Path, Path]) -> None:
        outbox, uploaded = dirs
        up = _make_uploader(outbox, uploaded, chunk_seconds=120)
        p = outbox / "chunk_20240115_143022.ogg"
        p.write_bytes(b"\x00")

        start, end = up._parse_timestamps(p)
        assert end == "2024-01-15T14:32:22"


class TestQueueSize:
    def test_empty_queue(self, dirs: tuple[Path, Path]) -> None:
        outbox, uploaded = dirs
        up = _make_uploader(outbox, uploaded)
        assert up.queue_size == 0

    def test_queue_with_chunks(self, dirs: tuple[Path, Path]) -> None:
        outbox, uploaded = dirs
        for i in range(3):
            (outbox / f"chunk_20240115_14300{i}.ogg").write_bytes(b"\x00")
        up = _make_uploader(outbox, uploaded)
        assert up.queue_size == 3

    def test_ignores_non_chunk_files(self, dirs: tuple[Path, Path]) -> None:
        outbox, uploaded = dirs
        (outbox / "chunk_20240115_143000.ogg").write_bytes(b"\x00")
        (outbox / "something_else.txt").write_bytes(b"\x00")
        (outbox / "chunk_20240115_143001.ogg.part").write_bytes(b"\x00")
        up = _make_uploader(outbox, uploaded)
        assert up.queue_size == 1


class TestPendingChunks:
    def test_sorted_oldest_first(self, dirs: tuple[Path, Path]) -> None:
        outbox, uploaded = dirs
        (outbox / "chunk_20240115_143002.ogg").write_bytes(b"\x00")
        (outbox / "chunk_20240115_143000.ogg").write_bytes(b"\x00")
        (outbox / "chunk_20240115_143001.ogg").write_bytes(b"\x00")

        up = _make_uploader(outbox, uploaded)
        pending = up._pending_chunks()
        names = [p.name for p in pending]
        assert names == [
            "chunk_20240115_143000.ogg",
            "chunk_20240115_143001.ogg",
            "chunk_20240115_143002.ogg",
        ]


class TestMoveToUploaded:
    def test_move_success(self, dirs: tuple[Path, Path]) -> None:
        outbox, uploaded = dirs
        p = outbox / "chunk_20240115_143000.ogg"
        p.write_bytes(b"data")

        up = _make_uploader(outbox, uploaded)
        up._move_to_uploaded(p)

        assert not p.exists()
        assert (uploaded / "chunk_20240115_143000.ogg").exists()

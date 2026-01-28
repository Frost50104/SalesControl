"""Chunk uploader with exponential backoff retry."""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# Pattern to extract timestamp from chunk filename: chunk_20240115_080000.ogg
_TS_PATTERN = re.compile(r"chunk_(\d{8}_\d{6})\.ogg$")


class Uploader:
    """Watch outbox for completed chunks and upload them to the ingest API."""

    def __init__(
        self,
        outbox_dir: Path,
        uploaded_dir: Path,
        ingest_url: str,
        ingest_token: str,
        point_id: str,
        register_id: str,
        device_id: str,
        chunk_seconds: int,
        sample_rate: int,
        retry_min_s: float = 2.0,
        retry_max_s: float = 300.0,
    ) -> None:
        self._outbox = outbox_dir
        self._uploaded = uploaded_dir
        self._url = f"{ingest_url.rstrip('/')}/api/v1/chunks"
        self._token = ingest_token
        self._point_id = point_id
        self._register_id = register_id
        self._device_id = device_id
        self._chunk_seconds = chunk_seconds
        self._sample_rate = sample_rate
        self._retry_min = retry_min_s
        self._retry_max = retry_max_s

        self._running = False
        self._thread: threading.Thread | None = None
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self._token}"

        # stats
        self.uploaded_count = 0
        self.failed_count = 0
        self.last_upload_ts: float | None = None
        self._current_backoff = retry_min_s

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._uploaded.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="uploader")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=15)
        self._session.close()

    @property
    def queue_size(self) -> int:
        try:
            return len(list(self._outbox.glob("chunk_*.ogg")))
        except OSError:
            return 0

    def _run_loop(self) -> None:
        while self._running:
            chunks = self._pending_chunks()
            if not chunks:
                self._interruptible_sleep(3)
                continue

            for chunk_path in chunks:
                if not self._running:
                    return
                success = self._upload_one(chunk_path)
                if success:
                    self._current_backoff = self._retry_min
                else:
                    # backoff before next attempt
                    jitter = random.uniform(0, self._current_backoff * 0.3)
                    delay = self._current_backoff + jitter
                    log.info("upload_backoff", extra={"delay_s": round(delay, 1)})
                    self._interruptible_sleep(delay)
                    self._current_backoff = min(self._current_backoff * 2, self._retry_max)
                    break  # restart the scan after backoff

    def _pending_chunks(self) -> list[Path]:
        """Return completed .ogg chunks sorted oldest first."""
        try:
            return sorted(self._outbox.glob("chunk_*.ogg"))
        except OSError:
            return []

    def _upload_one(self, path: Path) -> bool:
        start_ts, end_ts = self._parse_timestamps(path)
        if start_ts is None:
            log.warning("bad_chunk_name", extra={"file": path.name})
            # move aside to avoid blocking the queue
            self._move_to_uploaded(path)
            return True

        try:
            with open(path, "rb") as f:
                resp = self._session.post(
                    self._url,
                    data={
                        "point_id": self._point_id,
                        "register_id": self._register_id,
                        "device_id": self._device_id,
                        "start_ts": start_ts,
                        "end_ts": end_ts,
                        "codec": "opus",
                        "sample_rate": str(self._sample_rate),
                        "channels": "1",
                    },
                    files={"chunk_file": (path.name, f, "audio/ogg")},
                    timeout=60,
                )

            if resp.status_code == 200:
                body = resp.json()
                chunk_id = body.get("chunk_id", "?")
                log.info("upload_ok", extra={
                    "file": path.name, "chunk_id": chunk_id, "status": resp.status_code,
                })
                self._move_to_uploaded(path)
                self.uploaded_count += 1
                self.last_upload_ts = time.time()
                return True

            log.warning("upload_http_error", extra={
                "file": path.name, "status": resp.status_code,
                "body": resp.text[:300],
            })
            self.failed_count += 1
            return False

        except requests.RequestException as exc:
            log.warning("upload_network_error", extra={
                "file": path.name, "error": str(exc),
            })
            self.failed_count += 1
            return False

    def _parse_timestamps(self, path: Path) -> tuple[str | None, str | None]:
        m = _TS_PATTERN.search(path.name)
        if not m:
            return None, None
        dt = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        start_ts = dt.strftime("%Y-%m-%dT%H:%M:%S")
        from datetime import timedelta
        end_dt = dt + timedelta(seconds=self._chunk_seconds)
        end_ts = end_dt.strftime("%Y-%m-%dT%H:%M:%S")
        return start_ts, end_ts

    def _move_to_uploaded(self, path: Path) -> None:
        try:
            dest = self._uploaded / path.name
            path.rename(dest)
        except OSError as exc:
            log.warning("move_uploaded_error", extra={"file": path.name, "error": str(exc)})

    def _interruptible_sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(0.5)

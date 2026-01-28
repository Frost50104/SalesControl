"""Spool manager: enforce retention by age and disk usage."""

from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)


class SpoolJanitor:
    """Periodically clean up old/oversized spool data."""

    def __init__(
        self,
        spool_dir: Path,
        max_days: int = 7,
        max_gb: float = 20.0,
        scan_interval_s: float = 300.0,
    ) -> None:
        self._spool = spool_dir
        self._max_age_s = max_days * 86400
        self._max_bytes = int(max_gb * 1024**3)
        self._interval = scan_interval_s
        self._running = False
        self._thread: "import threading; threading.Thread | None" = None  # type: ignore[assignment]

    def start(self) -> None:
        if self._running:
            return
        import threading
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="spool-janitor")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def run_once(self) -> dict[str, int]:
        """Run a single cleanup pass. Returns stats."""
        deleted_age = self._delete_expired()
        deleted_size = self._enforce_size_limit()
        return {"deleted_by_age": deleted_age, "deleted_by_size": deleted_size}

    def total_size_bytes(self) -> int:
        """Total size of all .ogg files in spool tree."""
        total = 0
        try:
            for f in self._spool.rglob("*.ogg"):
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass
        return total

    def total_files(self) -> int:
        try:
            return len(list(self._spool.rglob("*.ogg")))
        except OSError:
            return 0

    def _loop(self) -> None:
        while self._running:
            try:
                stats = self.run_once()
                total = stats["deleted_by_age"] + stats["deleted_by_size"]
                if total > 0:
                    log.info("spool_cleanup", extra=stats)
            except Exception:
                log.exception("spool_cleanup_error")
            self._interruptible_sleep(self._interval)

    def _all_ogg_files_sorted(self) -> list[Path]:
        """All .ogg files in spool, sorted oldest first by name."""
        try:
            return sorted(self._spool.rglob("*.ogg"))
        except OSError:
            return []

    def _delete_expired(self) -> int:
        """Delete files older than max_age_s."""
        cutoff = time.time() - self._max_age_s
        deleted = 0
        for f in self._all_ogg_files_sorted():
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    deleted += 1
                    log.debug("spool_deleted_expired", extra={"file": f.name})
            except OSError:
                pass
        return deleted

    def _enforce_size_limit(self) -> int:
        """Delete oldest files until total size is under limit."""
        files = self._all_ogg_files_sorted()
        total = sum(f.stat().st_size for f in files if f.exists())
        deleted = 0
        for f in files:
            if total <= self._max_bytes:
                break
            try:
                sz = f.stat().st_size
                f.unlink()
                total -= sz
                deleted += 1
                log.debug("spool_deleted_size", extra={"file": f.name, "freed": sz})
            except OSError:
                pass
        return deleted

    def _interruptible_sleep(self, seconds: float) -> None:
        import time as _time
        deadline = _time.monotonic() + seconds
        while self._running and _time.monotonic() < deadline:
            _time.sleep(1)

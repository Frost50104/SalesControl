"""FFmpeg-based chunked audio recorder with OGG/Opus output."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .audio_device import AudioDeviceError, resolve_device

log = logging.getLogger(__name__)


class Recorder:
    """Record audio from ALSA device in chunks using ffmpeg segment muxer."""

    def __init__(
        self,
        audio_device: str,
        outbox_dir: Path,
        chunk_seconds: int = 60,
        opus_bitrate_kbps: int = 24,
        sample_rate: int = 48000,
    ) -> None:
        self._configured_device = audio_device
        self._outbox = outbox_dir
        self._chunk_seconds = chunk_seconds
        self._bitrate = f"{opus_bitrate_kbps}k"
        self._sample_rate = sample_rate
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._running = False
        self._monitor_thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Start the recording process.  Idempotent — safe to call if already running."""
        with self._lock:
            if self._running:
                return
            self._running = True

        self._monitor_thread = threading.Thread(target=self._run_loop, daemon=True, name="recorder")
        self._monitor_thread.start()

    def stop(self) -> None:
        """Gracefully stop recording."""
        with self._lock:
            self._running = False
        self._kill_ffmpeg()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=10)

    def _run_loop(self) -> None:
        """Continuously start ffmpeg; restart on crash/mic-disconnect."""
        reconnect_delay = 2.0
        while self._running:
            try:
                alsa_id = resolve_device(self._configured_device)
            except AudioDeviceError:
                log.error("mic_not_available", extra={"delay": reconnect_delay})
                self._wait(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60.0)
                continue

            reconnect_delay = 2.0
            self._outbox.mkdir(parents=True, exist_ok=True)

            # segment pattern: chunk_20240115_080000.ogg
            segment_pattern = str(self._outbox / "chunk_%Y%m%d_%H%M%S.ogg")

            cmd = [
                "ffmpeg", "-hide_banner", "-nostdin",
                "-f", "alsa",
                "-i", alsa_id,
                "-ac", "1",
                "-ar", str(self._sample_rate),
                "-c:a", "libopus",
                "-b:a", self._bitrate,
                "-vn",
                "-f", "segment",
                "-segment_time", str(self._chunk_seconds),
                "-segment_atclocktime", "1",
                "-strftime", "1",
                "-reset_timestamps", "1",
                segment_pattern,
            ]

            log.info("ffmpeg_start", extra={"cmd": " ".join(cmd)})
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except FileNotFoundError:
                log.error("ffmpeg_not_found")
                self._running = False
                return

            # Monitor stderr in a side thread for logging
            stderr_thread = threading.Thread(
                target=self._read_stderr, args=(self._process,), daemon=True
            )
            stderr_thread.start()

            returncode = self._process.wait()

            if not self._running:
                log.info("ffmpeg_stopped_gracefully", extra={"returncode": returncode})
                return

            log.warning("ffmpeg_exited", extra={"returncode": returncode})
            self._wait(reconnect_delay)

    def _read_stderr(self, proc: subprocess.Popen) -> None:
        """Read ffmpeg stderr and log significant lines."""
        assert proc.stderr is not None
        for raw_line in proc.stderr:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            # Filter noisy lines
            if any(skip in line for skip in ("size=", "frame=", "Press [q]")):
                continue
            level = logging.WARNING if "error" in line.lower() else logging.DEBUG
            log.log(level, "ffmpeg_stderr", extra={"line": line})

    def _kill_ffmpeg(self) -> None:
        proc = self._process
        if proc is None or proc.poll() is not None:
            return
        log.info("ffmpeg_stopping")
        try:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log.warning("ffmpeg_sigkill")
            proc.kill()
            proc.wait(timeout=3)

    def _wait(self, seconds: float) -> None:
        """Interruptible wait."""
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(0.5)

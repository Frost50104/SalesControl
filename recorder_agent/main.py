"""Service orchestrator — ties together recorder, uploader, spool janitor, healthcheck."""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .config import Config, load_config
from .healthcheck import HealthServer
from .logging_setup import setup_logging
from .recorder import Recorder
from .scheduler import is_in_schedule
from .spool import SpoolJanitor
from .uploader import Uploader

log = logging.getLogger(__name__)


class Service:
    """Main service orchestrator."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._shutdown = threading.Event()

        # ensure directories exist
        cfg.outbox_path.mkdir(parents=True, exist_ok=True)
        cfg.uploaded_path.mkdir(parents=True, exist_ok=True)

        self._recorder = Recorder(
            audio_device=cfg.audio_device,
            outbox_dir=cfg.outbox_path,
            chunk_seconds=cfg.chunk_seconds,
            opus_bitrate_kbps=cfg.opus_bitrate_kbps,
            sample_rate=cfg.sample_rate,
        )

        self._uploader = Uploader(
            outbox_dir=cfg.outbox_path,
            uploaded_dir=cfg.uploaded_path,
            ingest_url=cfg.ingest_base_url,
            ingest_token=cfg.ingest_token,
            point_id=cfg.point_id,
            register_id=cfg.register_id,
            device_id=cfg.device_id,
            chunk_seconds=cfg.chunk_seconds,
            sample_rate=cfg.sample_rate,
            retry_min_s=cfg.retry_min_s,
            retry_max_s=cfg.retry_max_s,
        )

        self._janitor = SpoolJanitor(
            spool_dir=cfg.spool_path,
            max_days=cfg.max_spool_days,
            max_gb=cfg.max_spool_gb,
        )

        self._health = HealthServer(
            port=cfg.health_port,
            status_func=self._build_status,
        )

    def run(self) -> None:
        """Start all subsystems and run the main schedule loop."""
        log.info("service_starting", extra={
            "point_id": self.cfg.point_id,
            "schedule": f"{self.cfg.schedule_start}-{self.cfg.schedule_end}",
            "chunk_s": self.cfg.chunk_seconds,
            "bitrate": f"{self.cfg.opus_bitrate_kbps}kbps",
            "spool": str(self.cfg.spool_path),
        })

        # install signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self._handle_signal)

        self._health.start()
        self._uploader.start()
        self._janitor.start()

        try:
            self._schedule_loop()
        finally:
            self._stop_all()

    def _schedule_loop(self) -> None:
        """Main loop: start/stop recording based on time schedule."""
        was_active = False
        while not self._shutdown.is_set():
            active = is_in_schedule(self.cfg.schedule_start, self.cfg.schedule_end)

            if active and not was_active:
                log.info("schedule_recording_start")
                self._recorder.start()
                was_active = True
            elif not active and was_active:
                log.info("schedule_recording_stop")
                self._recorder.stop()
                was_active = False

            self._shutdown.wait(timeout=5)

        # ensure recorder stops on shutdown
        if was_active:
            self._recorder.stop()

    def _stop_all(self) -> None:
        log.info("service_stopping")
        self._recorder.stop()
        self._uploader.stop()
        self._janitor.stop()
        self._health.stop()
        log.info("service_stopped")

    def _handle_signal(self, signum: int, frame: Any) -> None:
        log.info("signal_received", extra={"signal": signal.Signals(signum).name})
        self._shutdown.set()

    def _build_status(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "recording": self._recorder.is_running,
            "in_schedule": is_in_schedule(self.cfg.schedule_start, self.cfg.schedule_end),
            "queue_size": self._uploader.queue_size,
            "uploaded_total": self._uploader.uploaded_count,
            "upload_errors_total": self._uploader.failed_count,
            "last_upload_ts": self._uploader.last_upload_ts,
            "spool_files": self._janitor.total_files(),
            "spool_bytes": self._janitor.total_size_bytes(),
            "point_id": self.cfg.point_id,
        }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="recorder-agent: chunked audio capture & upload")
    parser.add_argument("-c", "--config", default="/etc/recorder-agent/config.yaml",
                        help="Path to config YAML file")
    parser.add_argument("--log-level", default="INFO", help="Log level (DEBUG/INFO/WARNING/ERROR)")
    args = parser.parse_args()

    setup_logging(level=args.log_level)

    try:
        cfg = load_config(args.config)
    except Exception as exc:
        log.error("config_load_failed", extra={"error": str(exc)})
        sys.exit(1)

    svc = Service(cfg)
    svc.run()

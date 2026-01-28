"""Configuration loading from YAML with environment variable overrides."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


_SENTINEL = object()


def _env(key: str, default: Any = _SENTINEL) -> str:
    val = os.environ.get(key)
    if val is not None:
        return val
    if default is not _SENTINEL:
        return default
    raise ValueError(f"Required config key missing: {key}")


@dataclass(frozen=True)
class Config:
    # identifiers
    point_id: str
    register_id: str
    device_id: str

    # ingest
    ingest_base_url: str
    ingest_token: str

    # schedule (HH:MM strings)
    schedule_start: str = "08:00"
    schedule_end: str = "22:00"

    # recording
    chunk_seconds: int = 60
    opus_bitrate_kbps: int = 24
    audio_device: str = ""  # ALSA device, e.g. "hw:1,0"; empty = auto-detect
    sample_rate: int = 48000

    # spool
    spool_dir: str = "/var/lib/recorder-agent/spool"
    outbox_dir: str = ""  # derived from spool_dir if empty
    max_spool_days: int = 7
    max_spool_gb: float = 20.0

    # retry
    retry_min_s: float = 2.0
    retry_max_s: float = 300.0

    # healthcheck
    health_port: int = 8042

    def __post_init__(self) -> None:
        # validate UUIDs
        for fld in ("point_id", "register_id", "device_id"):
            try:
                uuid.UUID(getattr(self, fld))
            except ValueError as exc:
                raise ValueError(f"{fld} must be a valid UUID: {exc}") from exc

        if not self.outbox_dir:
            object.__setattr__(self, "outbox_dir", str(Path(self.spool_dir) / "outbox"))

    @property
    def outbox_path(self) -> Path:
        return Path(self.outbox_dir)

    @property
    def spool_path(self) -> Path:
        return Path(self.spool_dir)

    @property
    def uploaded_path(self) -> Path:
        return Path(self.spool_dir) / "uploaded"


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_config(config_path: str | Path | None = None) -> Config:
    """Load config from YAML file, then override with environment variables."""
    raw: dict[str, Any] = {}
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

    # flatten nested yaml sections into flat keys for the dataclass
    flat: dict[str, Any] = {}
    for section in ("identifiers", "ingest", "schedule", "recording", "spool", "retry", "health"):
        if section in raw and isinstance(raw[section], dict):
            flat.update(raw[section])
    # also accept top-level keys
    for k, v in raw.items():
        if not isinstance(v, dict):
            flat[k] = v

    # environment variable overrides (uppercased key, prefixed RA_)
    env_map = {
        "RA_POINT_ID": "point_id",
        "RA_REGISTER_ID": "register_id",
        "RA_DEVICE_ID": "device_id",
        "RA_INGEST_BASE_URL": "ingest_base_url",
        "RA_INGEST_TOKEN": "ingest_token",
        "RA_SCHEDULE_START": "schedule_start",
        "RA_SCHEDULE_END": "schedule_end",
        "RA_CHUNK_SECONDS": "chunk_seconds",
        "RA_OPUS_BITRATE_KBPS": "opus_bitrate_kbps",
        "RA_AUDIO_DEVICE": "audio_device",
        "RA_SAMPLE_RATE": "sample_rate",
        "RA_SPOOL_DIR": "spool_dir",
        "RA_OUTBOX_DIR": "outbox_dir",
        "RA_MAX_SPOOL_DAYS": "max_spool_days",
        "RA_MAX_SPOOL_GB": "max_spool_gb",
        "RA_RETRY_MIN_S": "retry_min_s",
        "RA_RETRY_MAX_S": "retry_max_s",
        "RA_HEALTH_PORT": "health_port",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            flat[cfg_key] = val

    # type coerce numeric fields
    int_fields = {"chunk_seconds", "opus_bitrate_kbps", "sample_rate", "max_spool_days", "health_port"}
    float_fields = {"max_spool_gb", "retry_min_s", "retry_max_s"}
    for k in int_fields:
        if k in flat:
            flat[k] = int(flat[k])
    for k in float_fields:
        if k in flat:
            flat[k] = float(flat[k])

    return Config(**flat)

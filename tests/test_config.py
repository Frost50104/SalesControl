"""Tests for configuration loading."""

import os
from pathlib import Path

import pytest

from recorder_agent.config import Config, load_config


_VALID_UUID = "00000000-0000-0000-0000-000000000001"


class TestConfigValidation:
    def test_valid_config(self) -> None:
        cfg = Config(
            point_id=_VALID_UUID,
            register_id=_VALID_UUID,
            device_id=_VALID_UUID,
            ingest_base_url="https://audio.example.com",
            ingest_token="token",
        )
        assert cfg.chunk_seconds == 60
        assert cfg.opus_bitrate_kbps == 24

    def test_invalid_uuid(self) -> None:
        with pytest.raises(ValueError, match="point_id"):
            Config(
                point_id="not-a-uuid",
                register_id=_VALID_UUID,
                device_id=_VALID_UUID,
                ingest_base_url="https://audio.example.com",
                ingest_token="token",
            )

    def test_outbox_derived_from_spool(self) -> None:
        cfg = Config(
            point_id=_VALID_UUID,
            register_id=_VALID_UUID,
            device_id=_VALID_UUID,
            ingest_base_url="https://audio.example.com",
            ingest_token="token",
            spool_dir="/tmp/test-spool",
        )
        assert cfg.outbox_dir == "/tmp/test-spool/outbox"

    def test_outbox_explicit(self) -> None:
        cfg = Config(
            point_id=_VALID_UUID,
            register_id=_VALID_UUID,
            device_id=_VALID_UUID,
            ingest_base_url="https://audio.example.com",
            ingest_token="token",
            outbox_dir="/custom/outbox",
        )
        assert cfg.outbox_dir == "/custom/outbox"


class TestLoadConfigFromYAML:
    def test_load_yaml(self, tmp_path: Path) -> None:
        yaml_content = f"""\
identifiers:
  point_id: "{_VALID_UUID}"
  register_id: "{_VALID_UUID}"
  device_id: "{_VALID_UUID}"
ingest:
  ingest_base_url: "https://audio.example.com"
  ingest_token: "secret"
recording:
  chunk_seconds: 30
  opus_bitrate_kbps: 32
"""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml_content)
        cfg = load_config(cfg_file)
        assert cfg.chunk_seconds == 30
        assert cfg.opus_bitrate_kbps == 32

    def test_env_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        yaml_content = f"""\
identifiers:
  point_id: "{_VALID_UUID}"
  register_id: "{_VALID_UUID}"
  device_id: "{_VALID_UUID}"
ingest:
  ingest_base_url: "https://audio.example.com"
  ingest_token: "from-yaml"
"""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml_content)
        monkeypatch.setenv("RA_INGEST_TOKEN", "from-env")
        cfg = load_config(cfg_file)
        assert cfg.ingest_token == "from-env"

    def test_missing_file_with_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RA_POINT_ID", _VALID_UUID)
        monkeypatch.setenv("RA_REGISTER_ID", _VALID_UUID)
        monkeypatch.setenv("RA_DEVICE_ID", _VALID_UUID)
        monkeypatch.setenv("RA_INGEST_BASE_URL", "https://audio.example.com")
        monkeypatch.setenv("RA_INGEST_TOKEN", "env-token")
        cfg = load_config("/nonexistent/config.yaml")
        assert cfg.ingest_token == "env-token"

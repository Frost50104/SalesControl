"""Integration tests for VAD worker."""

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# Skip if database dependencies not available
pytest.importorskip("sqlalchemy")


@pytest.fixture
def mock_vad_segments():
    """Mock VAD results."""
    return [
        (0, 2000),
        (2500, 5000),
        (8000, 12000),
    ]


@pytest.fixture
def test_chunk():
    """Test chunk data."""
    return {
        "chunk_id": uuid4(),
        "device_id": uuid4(),
        "point_id": uuid4(),
        "register_id": uuid4(),
        "start_ts": datetime(2026, 1, 29, 10, 0, 0, tzinfo=timezone.utc),
        "end_ts": datetime(2026, 1, 29, 10, 1, 0, tzinfo=timezone.utc),
        "duration_sec": 60,
        "sample_rate": 48000,
        "channels": 1,
        "file_path": "audio/test/chunk.ogg",
    }


class TestVADModule:
    """Tests for VAD module functions."""

    def test_frames_to_segments_empty(self):
        """Empty input should return empty segments."""
        from vad_worker.vad import frames_to_segments

        result = frames_to_segments([], [], frame_duration_ms=30)
        assert result == []

    def test_frames_to_segments_all_speech(self):
        """All speech frames should create single segment."""
        from vad_worker.vad import frames_to_segments

        frames = [(i * 30, b"\x00" * 960) for i in range(100)]  # 3 seconds
        speech_flags = [True] * 100

        result = frames_to_segments(
            frames, speech_flags, frame_duration_ms=30, min_speech_ms=100, min_silence_ms=300
        )

        assert len(result) == 1
        assert result[0][0] == 0  # Start at 0ms
        assert result[0][1] == 3000  # End at 3000ms

    def test_frames_to_segments_all_silence(self):
        """All silence should return empty segments."""
        from vad_worker.vad import frames_to_segments

        frames = [(i * 30, b"\x00" * 960) for i in range(100)]
        speech_flags = [False] * 100

        result = frames_to_segments(
            frames, speech_flags, frame_duration_ms=30, min_speech_ms=100, min_silence_ms=300
        )

        assert result == []

    def test_frames_to_segments_speech_in_middle(self):
        """Speech in the middle should create single segment."""
        from vad_worker.vad import frames_to_segments

        frames = [(i * 30, b"\x00" * 960) for i in range(100)]
        # 1s silence, 1s speech, 1s silence
        speech_flags = [False] * 33 + [True] * 34 + [False] * 33

        result = frames_to_segments(
            frames, speech_flags, frame_duration_ms=30, min_speech_ms=100, min_silence_ms=300
        )

        assert len(result) == 1
        # Speech starts around 1s (33 * 30ms = 990ms)
        assert 900 <= result[0][0] <= 1100
        # Speech ends around 2s
        assert 1900 <= result[0][1] <= 2100

    def test_frames_to_segments_multiple_speech(self):
        """Multiple speech sections with long silence between."""
        from vad_worker.vad import frames_to_segments

        frames = [(i * 30, b"\x00" * 960) for i in range(200)]
        # Speech at 0-1s, silence 1-4s, speech at 4-5s
        speech_flags = (
            [True] * 33 +   # 0-1s speech
            [False] * 100 + # 1-4s silence (3s > min_silence_ms)
            [True] * 33 +   # 4-5s speech
            [False] * 34    # remaining
        )

        result = frames_to_segments(
            frames, speech_flags, frame_duration_ms=30, min_speech_ms=100, min_silence_ms=300
        )

        assert len(result) == 2


class TestDialogueBuilderIntegration:
    """Integration tests for dialogue builder with mocked database."""

    @pytest.mark.asyncio
    async def test_process_chunk_no_speech(self, test_chunk):
        """Processing chunk with no speech should not create dialogues."""
        from vad_worker import dialogue_builder, repository

        with patch.object(repository, "get_device_dialogue_state", new_callable=AsyncMock) as mock_state:
            with patch.object(repository, "upsert_device_dialogue_state", new_callable=AsyncMock) as mock_upsert:
                mock_state.return_value = None
                mock_session = AsyncMock()

                await dialogue_builder.process_chunk_dialogues(
                    mock_session, test_chunk, []  # No speech segments
                )

                # Should not create any dialogues
                mock_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_chunk_with_speech(self, test_chunk, mock_vad_segments):
        """Processing chunk with speech should create dialogue."""
        from vad_worker import dialogue_builder, repository

        with patch.object(repository, "get_device_dialogue_state", new_callable=AsyncMock) as mock_state:
            with patch.object(repository, "upsert_device_dialogue_state", new_callable=AsyncMock) as mock_upsert:
                with patch.object(repository, "create_dialogue", new_callable=AsyncMock) as mock_create:
                    with patch.object(repository, "add_dialogue_segment", new_callable=AsyncMock) as mock_add_seg:
                        mock_state.return_value = None
                        mock_create.return_value = uuid4()
                        mock_session = AsyncMock()

                        await dialogue_builder.process_chunk_dialogues(
                            mock_session, test_chunk, mock_vad_segments
                        )

                        # Should create dialogue
                        assert mock_create.called
                        # Should add segments
                        assert mock_add_seg.call_count == len(mock_vad_segments)


class TestSettingsValidation:
    """Tests for settings validation."""

    def test_default_settings(self):
        """Default settings should be valid."""
        # Clear cache to get fresh settings
        from vad_worker.settings import Settings

        settings = Settings()
        assert settings.vad_aggressiveness in range(4)
        assert settings.vad_frame_ms in (10, 20, 30)
        assert settings.silence_gap_sec > 0
        assert settings.max_dialogue_sec > 0
        assert settings.batch_size > 0

    def test_settings_from_env(self, monkeypatch):
        """Settings should be loaded from environment."""
        from vad_worker.settings import Settings

        monkeypatch.setenv("VAD_AGGRESSIVENESS", "3")
        monkeypatch.setenv("SILENCE_GAP_SEC", "15.0")
        monkeypatch.setenv("BATCH_SIZE", "20")

        settings = Settings()
        assert settings.vad_aggressiveness == 3
        assert settings.silence_gap_sec == 15.0
        assert settings.batch_size == 20

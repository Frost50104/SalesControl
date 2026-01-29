"""Pytest configuration and fixtures."""

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_segments():
    """Sample speech segments for testing."""
    return [
        (0, 2000),      # 0-2s
        (2500, 5000),   # 2.5-5s (small gap)
        (8000, 12000),  # 8-12s (3s gap)
        (12500, 15000), # 12.5-15s (small gap)
    ]


@pytest.fixture
def chunk_metadata():
    """Sample chunk metadata."""
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

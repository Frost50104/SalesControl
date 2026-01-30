"""Pytest fixtures for asr_worker tests."""

import os
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Set test environment before importing app
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["INTERNAL_TOKEN"] = "test-internal-token"
os.environ["INGEST_INTERNAL_BASE_URL"] = "http://test-ingest:8000"


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio backend."""
    return "asyncio"


@pytest.fixture
def dialogue_ids() -> dict:
    """Generate test UUIDs for dialogue."""
    return {
        "dialogue_id": uuid4(),
        "device_id": uuid4(),
        "point_id": uuid4(),
        "register_id": uuid4(),
    }


@pytest.fixture
def chunk_ids() -> list:
    """Generate test chunk UUIDs."""
    return [uuid4() for _ in range(3)]

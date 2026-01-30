"""Pytest fixtures for ingest_api tests."""

import os
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Set test environment before importing app
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["AUDIO_STORAGE_DIR"] = "/tmp/ingest_api_test"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["INTERNAL_TOKEN"] = "test-internal-token"

from ingest_api.auth import hash_token
from ingest_api.db import get_session
from ingest_api.main import create_app
from ingest_api.models import Base, Device
from ingest_api.settings import get_settings


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio backend."""
    return "asyncio"


@pytest.fixture
async def engine():
    """Create test database engine."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with factory() as session:
        yield session


@pytest.fixture
async def client(engine, tmp_path) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client."""
    # Set storage dir and clear settings cache
    os.environ["AUDIO_STORAGE_DIR"] = str(tmp_path)
    get_settings.cache_clear()

    app = create_app()

    # Override session dependency
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # Cleanup: clear cache again for next test
    get_settings.cache_clear()


@pytest.fixture
def device_token() -> str:
    """Generate test device token."""
    return "test-device-token-12345678"


@pytest.fixture
def device_ids() -> dict:
    """Generate test UUIDs."""
    return {
        "device_id": uuid4(),
        "point_id": uuid4(),
        "register_id": uuid4(),
    }


@pytest.fixture
async def registered_device(
    session: AsyncSession,
    device_ids: dict,
    device_token: str,
) -> Device:
    """Create a registered test device."""
    device = Device(
        device_id=device_ids["device_id"],
        point_id=device_ids["point_id"],
        register_id=device_ids["register_id"],
        token_hash=hash_token(device_token),
        is_enabled=True,
    )
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return device


@pytest.fixture
def internal_token() -> str:
    """Get internal service token."""
    return "test-internal-token"


@pytest.fixture
async def chunk_with_file(
    session: AsyncSession,
    registered_device: Device,
    device_ids: dict,
    tmp_path,
) -> tuple:
    """Create a chunk record with an actual file on disk."""
    from datetime import datetime, timezone
    from ingest_api.models import AudioChunk

    chunk_id = uuid4()
    audio_content = b"OggS" + os.urandom(1000)

    # Create directory structure
    relative_path = f"audio/{device_ids['point_id']}/{device_ids['register_id']}/2026-01-30/10/chunk_20260130_100000_{chunk_id}.ogg"
    full_path = tmp_path / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(audio_content)

    # Create database record
    chunk = AudioChunk(
        chunk_id=chunk_id,
        device_id=device_ids["device_id"],
        point_id=device_ids["point_id"],
        register_id=device_ids["register_id"],
        start_ts=datetime(2026, 1, 30, 10, 0, 0, tzinfo=timezone.utc),
        end_ts=datetime(2026, 1, 30, 10, 1, 0, tzinfo=timezone.utc),
        duration_sec=60,
        codec="opus",
        sample_rate=48000,
        channels=1,
        file_path=relative_path,
        file_size_bytes=len(audio_content),
        status="QUEUED",
    )
    session.add(chunk)
    await session.commit()
    await session.refresh(chunk)

    return chunk, audio_content

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

"""API routes for chunk ingestion and device management."""

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import (
    authenticate_device,
    hash_token,
    verify_admin_token,
)
from .db import get_session
from .models import AudioChunk, Device
from .settings import Settings, get_settings
from .storage import get_chunk_path, save_chunk_file

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Schemas
# =============================================================================


class ChunkUploadResponse(BaseModel):
    """Response for successful chunk upload."""

    status: str = "ok"
    chunk_id: UUID
    stored_path: str
    queued: bool = True


class DeviceCreateRequest(BaseModel):
    """Request to create a new device."""

    point_id: UUID
    register_id: UUID
    device_id: UUID
    token_plain: str = Field(..., min_length=16)


class DeviceResponse(BaseModel):
    """Device info response."""

    device_id: UUID
    point_id: UUID
    register_id: UUID
    is_enabled: bool
    created_at: datetime
    last_seen_at: datetime | None


class DeviceUpdateRequest(BaseModel):
    """Request to update device."""

    is_enabled: bool | None = None


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str


# =============================================================================
# Chunk Upload Endpoint
# =============================================================================


@router.post(
    "/api/v1/chunks",
    response_model=ChunkUploadResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        413: {"model": ErrorResponse, "description": "File too large"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        500: {"model": ErrorResponse, "description": "Internal error"},
    },
)
async def upload_chunk(
    request: Request,
    point_id: UUID = Form(...),
    register_id: UUID = Form(...),
    device_id: UUID = Form(...),
    start_ts: datetime = Form(...),
    end_ts: datetime = Form(...),
    codec: str = Form(...),
    sample_rate: int = Form(...),
    channels: int = Form(...),
    chunk_file: UploadFile = File(...),
    device: Device = Depends(authenticate_device),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ChunkUploadResponse:
    """
    Upload an audio chunk from a recorder device.

    The device must be authenticated via Bearer token.
    """
    # Validate device_id matches authenticated device
    if device_id != device.device_id:
        logger.warning(
            "chunk_upload_device_mismatch",
            extra={
                "claimed_device_id": str(device_id),
                "auth_device_id": str(device.device_id),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="device_id does not match authenticated device",
        )

    # Validate point_id and register_id match device registration
    if point_id != device.point_id or register_id != device.register_id:
        logger.warning(
            "chunk_upload_identity_mismatch",
            extra={
                "claimed_point_id": str(point_id),
                "claimed_register_id": str(register_id),
                "device_point_id": str(device.point_id),
                "device_register_id": str(device.register_id),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="point_id or register_id does not match device registration",
        )

    # Validate timestamps
    if end_ts <= start_ts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_ts must be after start_ts",
        )

    # Read file content with size check
    content = await chunk_file.read()
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_upload_size_bytes} bytes",
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Empty file",
        )

    # Generate chunk ID and path
    chunk_id = uuid4()
    relative_path = get_chunk_path(point_id, register_id, start_ts, chunk_id)

    try:
        # Save file to storage
        full_path, file_size = await save_chunk_file(content, relative_path)

        # Calculate duration
        duration_sec = int((end_ts - start_ts).total_seconds())

        # Create database record
        chunk = AudioChunk(
            chunk_id=chunk_id,
            device_id=device_id,
            point_id=point_id,
            register_id=register_id,
            start_ts=start_ts,
            end_ts=end_ts,
            duration_sec=duration_sec,
            codec=codec,
            sample_rate=sample_rate,
            channels=channels,
            file_path=relative_path,
            file_size_bytes=file_size,
            status="QUEUED",  # Ready for processing
        )
        session.add(chunk)
        await session.commit()

        logger.info(
            "chunk_uploaded",
            extra={
                "chunk_id": str(chunk_id),
                "device_id": str(device_id),
                "point_id": str(point_id),
                "duration_sec": duration_sec,
                "file_size": file_size,
            },
        )

        return ChunkUploadResponse(
            status="ok",
            chunk_id=chunk_id,
            stored_path=relative_path,
            queued=True,
        )

    except Exception as e:
        logger.error(
            "chunk_upload_failed",
            extra={
                "device_id": str(device_id),
                "error": str(e),
            },
        )
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save chunk",
        ) from e


# =============================================================================
# Admin Endpoints
# =============================================================================


@router.post(
    "/api/v1/admin/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_admin_token)],
)
async def create_device(
    req: DeviceCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> DeviceResponse:
    """Create a new device registration."""
    # Check if device already exists
    existing = await session.execute(
        select(Device).where(Device.device_id == req.device_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device already exists",
        )

    device = Device(
        device_id=req.device_id,
        point_id=req.point_id,
        register_id=req.register_id,
        token_hash=hash_token(req.token_plain),
        is_enabled=True,
    )
    session.add(device)
    await session.commit()
    await session.refresh(device)

    logger.info(
        "device_created",
        extra={
            "device_id": str(device.device_id),
            "point_id": str(device.point_id),
        },
    )

    return DeviceResponse(
        device_id=device.device_id,
        point_id=device.point_id,
        register_id=device.register_id,
        is_enabled=device.is_enabled,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
    )


@router.get(
    "/api/v1/admin/devices",
    response_model=list[DeviceResponse],
    dependencies=[Depends(verify_admin_token)],
)
async def list_devices(
    session: AsyncSession = Depends(get_session),
) -> list[DeviceResponse]:
    """List all registered devices."""
    result = await session.execute(
        select(Device).order_by(Device.created_at.desc())
    )
    devices = result.scalars().all()

    return [
        DeviceResponse(
            device_id=d.device_id,
            point_id=d.point_id,
            register_id=d.register_id,
            is_enabled=d.is_enabled,
            created_at=d.created_at,
            last_seen_at=d.last_seen_at,
        )
        for d in devices
    ]


@router.patch(
    "/api/v1/admin/devices/{device_id}",
    response_model=DeviceResponse,
    dependencies=[Depends(verify_admin_token)],
)
async def update_device(
    device_id: UUID,
    req: DeviceUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> DeviceResponse:
    """Update device settings (enable/disable)."""
    result = await session.execute(
        select(Device).where(Device.device_id == device_id)
    )
    device = result.scalar_one_or_none()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    if req.is_enabled is not None:
        device.is_enabled = req.is_enabled

    await session.commit()
    await session.refresh(device)

    logger.info(
        "device_updated",
        extra={
            "device_id": str(device.device_id),
            "is_enabled": device.is_enabled,
        },
    )

    return DeviceResponse(
        device_id=device.device_id,
        point_id=device.point_id,
        register_id=device.register_id,
        is_enabled=device.is_enabled,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
    )


# =============================================================================
# Health Endpoint
# =============================================================================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    db: bool
    storage_writable: bool
    time: datetime


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check service health."""
    from .db import check_db_connection
    from .storage import check_storage_writable

    db_ok = await check_db_connection()
    storage_ok = await check_storage_writable()

    return HealthResponse(
        status="ok" if (db_ok and storage_ok) else "degraded",
        db=db_ok,
        storage_writable=storage_ok,
        time=datetime.now(timezone.utc),
    )

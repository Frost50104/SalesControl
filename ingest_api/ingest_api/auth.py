"""Authentication and authorization."""

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import Device
from .settings import Settings, get_settings

logger = logging.getLogger(__name__)


def hash_token(token: str) -> str:
    """Hash a token using SHA-256."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token() -> str:
    """Generate a secure random token."""
    return secrets.token_urlsafe(32)


async def get_device_by_token(
    session: AsyncSession,
    token: str,
) -> Device | None:
    """Find device by bearer token."""
    token_hash = hash_token(token)
    result = await session.execute(
        select(Device).where(
            Device.token_hash == token_hash,
            Device.is_enabled == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def update_device_last_seen(
    session: AsyncSession,
    device_id: UUID,
) -> None:
    """Update device last_seen_at timestamp."""
    await session.execute(
        update(Device)
        .where(Device.device_id == device_id)
        .values(last_seen_at=datetime.now(timezone.utc))
    )
    await session.commit()


async def authenticate_device(
    authorization: str | None = Header(None, alias="Authorization"),
    session: AsyncSession = Depends(get_session),
) -> Device:
    """
    Dependency to authenticate device by Bearer token.

    Raises HTTPException 401 if authentication fails.
    """
    if not authorization:
        logger.warning("auth_missing_header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not authorization.startswith("Bearer "):
        logger.warning("auth_invalid_scheme")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization scheme",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:]  # Remove "Bearer " prefix
    if not token:
        logger.warning("auth_empty_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    device = await get_device_by_token(session, token)
    if not device:
        logger.warning("auth_invalid_token", extra={"token_prefix": token[:8]})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or disabled device token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last seen asynchronously (don't block response)
    await update_device_last_seen(session, device.device_id)

    logger.debug(
        "auth_success",
        extra={"device_id": str(device.device_id), "point_id": str(device.point_id)},
    )
    return device


def verify_admin_token(
    authorization: str | None = Header(None, alias="Authorization"),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Dependency to verify admin token.

    Raises HTTPException 401 if authentication fails.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization scheme",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:]
    if not secrets.compare_digest(token, settings.admin_token):
        logger.warning("admin_auth_failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug("admin_auth_success")

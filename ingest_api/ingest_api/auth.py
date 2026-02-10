"""Authentication and authorization."""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import Device, User
from .settings import Settings, get_settings

logger = logging.getLogger(__name__)

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer security scheme for JWT
security = HTTPBearer()


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


def verify_internal_token(
    authorization: str | None = Header(None, alias="Authorization"),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Dependency to verify internal service token.

    Used for inter-service communication (e.g., asr_worker fetching chunks).
    Raises HTTPException 401 if authentication fails or token not configured.
    """
    if not settings.internal_token:
        logger.error("internal_token_not_configured")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Internal endpoint not configured",
            headers={"WWW-Authenticate": "Bearer"},
        )

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
    if not secrets.compare_digest(token, settings.internal_token):
        logger.warning("internal_auth_failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug("internal_auth_success")


# ==============================================================================
# Password hashing functions
# ==============================================================================


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


# ==============================================================================
# JWT token functions
# ==============================================================================


def create_access_token(
    data: dict,
    settings: Settings,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=24)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return encoded_jwt


def decode_access_token(token: str, settings: Settings) -> dict | None:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError:
        return None


# ==============================================================================
# User authentication functions
# ==============================================================================


async def get_user_by_username(
    session: AsyncSession,
    username: str,
) -> User | None:
    """Find user by username."""
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def authenticate_user(
    session: AsyncSession,
    username: str,
    password: str,
) -> User | None:
    """Authenticate user by username and password."""
    user = await get_user_by_username(session, username)
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def update_user_last_login(
    session: AsyncSession,
    user_id: UUID,
) -> None:
    """Update user last_login_at timestamp."""
    await session.execute(
        update(User)
        .where(User.user_id == user_id)
        .values(last_login_at=datetime.now(timezone.utc))
    )
    await session.commit()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    """
    Dependency to get current authenticated user from JWT token.

    Raises HTTPException 401 if authentication fails.
    """
    token = credentials.credentials
    payload = decode_access_token(token, settings)

    if payload is None:
        logger.warning("jwt_decode_failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        logger.warning("jwt_missing_sub")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(user_id_str)
    except ValueError:
        logger.warning("jwt_invalid_user_id")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        logger.warning("jwt_user_not_found_or_inactive", extra={"user_id": str(user_id)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug("user_auth_success", extra={"user_id": str(user.user_id)})
    return user


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency to ensure current user is an admin.

    Raises HTTPException 403 if user is not an admin.
    """
    if not current_user.is_admin:
        logger.warning("admin_access_denied", extra={"user_id": str(current_user.user_id)})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user

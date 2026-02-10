"""User management API endpoints."""

import logging
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import (
    authenticate_user,
    create_access_token,
    get_current_admin_user,
    get_current_user,
    hash_password,
    update_user_last_login,
)
from .db import get_session
from .models import User
from .settings import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["users"])


# ==============================================================================
# Pydantic schemas
# ==============================================================================


class LoginRequest(BaseModel):
    """Login request."""

    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6)


class LoginResponse(BaseModel):
    """Login response."""

    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class UserResponse(BaseModel):
    """User response."""

    user_id: UUID
    username: str
    full_name: str
    is_admin: bool
    is_active: bool
    created_at: str
    last_login_at: str | None

    @classmethod
    def from_orm(cls, user: User) -> "UserResponse":
        """Create from ORM model."""
        return cls(
            user_id=user.user_id,
            username=user.username,
            full_name=user.full_name,
            is_admin=user.is_admin,
            is_active=user.is_active,
            created_at=user.created_at.isoformat(),
            last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        )


class CreateUserRequest(BaseModel):
    """Create user request."""

    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=1, max_length=256)
    is_admin: bool = False


class UpdateUserRequest(BaseModel):
    """Update user request."""

    full_name: str | None = Field(None, min_length=1, max_length=256)
    password: str | None = Field(None, min_length=6)
    is_admin: bool | None = None
    is_active: bool | None = None


# ==============================================================================
# Endpoints
# ==============================================================================


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    """
    Login with username and password.

    Returns JWT access token on success.
    """
    user = await authenticate_user(session, request.username, request.password)

    if not user:
        logger.warning("login_failed", extra={"username": request.username})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login timestamp
    await update_user_last_login(session, user.user_id)

    # Create JWT token
    access_token = create_access_token(
        data={"sub": str(user.user_id)},
        settings=settings,
        expires_delta=timedelta(hours=settings.jwt_access_token_expire_hours),
    )

    logger.info("login_success", extra={"user_id": str(user.user_id)})

    return LoginResponse(
        access_token=access_token,
        user=UserResponse.from_orm(user),
    )


@router.get("/users/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Get current authenticated user info."""
    return UserResponse.from_orm(current_user)


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(get_current_admin_user),
) -> list[UserResponse]:
    """List all users (admin only)."""
    result = await session.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [UserResponse.from_orm(user) for user in users]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(get_current_admin_user),
) -> UserResponse:
    """Create a new user (admin only)."""
    # Check if username already exists
    existing = await session.execute(
        select(User).where(User.username == request.username)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )

    # Create new user
    user = User(
        user_id=uuid4(),
        username=request.username,
        password_hash=hash_password(request.password),
        full_name=request.full_name,
        is_admin=request.is_admin,
        is_active=True,
    )

    session.add(user)
    await session.commit()
    await session.refresh(user)

    logger.info(
        "user_created",
        extra={
            "user_id": str(user.user_id),
            "username": user.username,
            "created_by": str(admin.user_id),
        },
    )

    return UserResponse.from_orm(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    request: UpdateUserRequest,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(get_current_admin_user),
) -> UserResponse:
    """Update a user (admin only)."""
    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Update fields
    if request.full_name is not None:
        user.full_name = request.full_name
    if request.password is not None:
        user.password_hash = hash_password(request.password)
    if request.is_admin is not None:
        user.is_admin = request.is_admin
    if request.is_active is not None:
        user.is_active = request.is_active

    await session.commit()
    await session.refresh(user)

    logger.info(
        "user_updated",
        extra={
            "user_id": str(user.user_id),
            "updated_by": str(admin.user_id),
        },
    )

    return UserResponse.from_orm(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(get_current_admin_user),
) -> None:
    """Delete a user (admin only)."""
    # Prevent deleting yourself
    if user_id == admin.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )

    result = await session.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    await session.delete(user)
    await session.commit()

    logger.info(
        "user_deleted",
        extra={
            "user_id": str(user_id),
            "deleted_by": str(admin.user_id),
        },
    )

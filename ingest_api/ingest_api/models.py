"""SQLAlchemy ORM models."""

from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Dialect,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import CHAR, TypeDecorator


class GUID(TypeDecorator):
    """Platform-independent GUID type.

    Uses PostgreSQL's UUID type when available, otherwise uses CHAR(36).
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect: Dialect):
        if value is None:
            return value
        elif dialect.name == "postgresql":
            return value
        else:
            if isinstance(value, PyUUID):
                return str(value)
            return value

    def process_result_value(self, value, dialect: Dialect):
        if value is None:
            return value
        if isinstance(value, PyUUID):
            return value
        return PyUUID(value)


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Device(Base):
    """Registered device that can upload audio chunks."""

    __tablename__ = "devices"

    device_id: Mapped[PyUUID] = mapped_column(GUID(), primary_key=True)
    point_id: Mapped[PyUUID] = mapped_column(GUID(), nullable=False)
    register_id: Mapped[PyUUID] = mapped_column(GUID(), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship to audio chunks
    chunks: Mapped[list["AudioChunk"]] = relationship(
        "AudioChunk", back_populates="device", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Device {self.device_id} point={self.point_id}>"


class AudioChunk(Base):
    """Uploaded audio chunk metadata."""

    __tablename__ = "audio_chunks"

    chunk_id: Mapped[PyUUID] = mapped_column(GUID(), primary_key=True)
    device_id: Mapped[PyUUID] = mapped_column(
        GUID(),
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        nullable=False,
    )
    point_id: Mapped[PyUUID] = mapped_column(GUID(), nullable=False)
    register_id: Mapped[PyUUID] = mapped_column(GUID(), nullable=False)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    codec: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    channels: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="UPLOADED", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship to device
    device: Mapped["Device"] = relationship("Device", back_populates="chunks")

    __table_args__ = (
        Index("ix_audio_chunks_point_start", "point_id", "start_ts"),
        Index("ix_audio_chunks_device_start", "device_id", "start_ts"),
    )

    def __repr__(self) -> str:
        return f"<AudioChunk {self.chunk_id} status={self.status}>"

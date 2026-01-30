"""Tests for API endpoints."""

import os
from io import BytesIO
from uuid import uuid4

import pytest
from httpx import AsyncClient

from ingest_api.models import Device


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    async def test_health_check(self, client: AsyncClient):
        """Health endpoint returns status."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "degraded")
        assert "db" in data
        assert "storage_writable" in data
        assert "time" in data


class TestChunkUpload:
    """Tests for POST /api/v1/chunks endpoint."""

    async def test_upload_chunk_success(
        self,
        client: AsyncClient,
        registered_device: Device,
        device_token: str,
        device_ids: dict,
    ):
        """Successful chunk upload returns 200 with chunk_id."""
        from pathlib import Path

        # Create test audio file
        audio_content = b"OggS" + os.urandom(1000)  # Fake ogg header + random data

        response = await client.post(
            "/api/v1/chunks",
            headers={"Authorization": f"Bearer {device_token}"},
            data={
                "point_id": str(device_ids["point_id"]),
                "register_id": str(device_ids["register_id"]),
                "device_id": str(device_ids["device_id"]),
                "start_ts": "2026-01-28T10:00:00+00:00",
                "end_ts": "2026-01-28T10:01:00+00:00",
                "codec": "opus",
                "sample_rate": "48000",
                "channels": "1",
            },
            files={"chunk_file": ("test.ogg", BytesIO(audio_content), "audio/ogg")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "chunk_id" in data
        assert "stored_path" in data
        assert data["queued"] is True

        # Verify file was saved
        storage_dir = Path(os.environ["AUDIO_STORAGE_DIR"])
        stored_path = data["stored_path"]
        full_path = storage_dir / stored_path
        assert full_path.exists()
        assert full_path.read_bytes() == audio_content

    async def test_upload_chunk_401_no_token(self, client: AsyncClient, device_ids: dict):
        """Missing Authorization header returns 401."""
        response = await client.post(
            "/api/v1/chunks",
            data={
                "point_id": str(device_ids["point_id"]),
                "register_id": str(device_ids["register_id"]),
                "device_id": str(device_ids["device_id"]),
                "start_ts": "2026-01-28T10:00:00+00:00",
                "end_ts": "2026-01-28T10:01:00+00:00",
                "codec": "opus",
                "sample_rate": "48000",
                "channels": "1",
            },
            files={"chunk_file": ("test.ogg", BytesIO(b"test"), "audio/ogg")},
        )

        assert response.status_code == 401
        assert "Missing Authorization header" in response.json()["detail"]

    async def test_upload_chunk_401_invalid_token(
        self,
        client: AsyncClient,
        registered_device: Device,
        device_ids: dict,
    ):
        """Invalid token returns 401."""
        response = await client.post(
            "/api/v1/chunks",
            headers={"Authorization": "Bearer invalid-token"},
            data={
                "point_id": str(device_ids["point_id"]),
                "register_id": str(device_ids["register_id"]),
                "device_id": str(device_ids["device_id"]),
                "start_ts": "2026-01-28T10:00:00+00:00",
                "end_ts": "2026-01-28T10:01:00+00:00",
                "codec": "opus",
                "sample_rate": "48000",
                "channels": "1",
            },
            files={"chunk_file": ("test.ogg", BytesIO(b"test"), "audio/ogg")},
        )

        assert response.status_code == 401

    async def test_upload_chunk_422_invalid_uuid(
        self,
        client: AsyncClient,
        registered_device: Device,
        device_token: str,
    ):
        """Invalid UUID format returns 422."""
        response = await client.post(
            "/api/v1/chunks",
            headers={"Authorization": f"Bearer {device_token}"},
            data={
                "point_id": "not-a-uuid",
                "register_id": "also-not-uuid",
                "device_id": "still-not-uuid",
                "start_ts": "2026-01-28T10:00:00+00:00",
                "end_ts": "2026-01-28T10:01:00+00:00",
                "codec": "opus",
                "sample_rate": "48000",
                "channels": "1",
            },
            files={"chunk_file": ("test.ogg", BytesIO(b"test"), "audio/ogg")},
        )

        assert response.status_code == 422

    async def test_upload_chunk_422_device_mismatch(
        self,
        client: AsyncClient,
        registered_device: Device,
        device_token: str,
        device_ids: dict,
    ):
        """device_id mismatch returns 422."""
        response = await client.post(
            "/api/v1/chunks",
            headers={"Authorization": f"Bearer {device_token}"},
            data={
                "point_id": str(device_ids["point_id"]),
                "register_id": str(device_ids["register_id"]),
                "device_id": str(uuid4()),  # Different device_id
                "start_ts": "2026-01-28T10:00:00+00:00",
                "end_ts": "2026-01-28T10:01:00+00:00",
                "codec": "opus",
                "sample_rate": "48000",
                "channels": "1",
            },
            files={"chunk_file": ("test.ogg", BytesIO(b"test"), "audio/ogg")},
        )

        assert response.status_code == 422
        assert "device_id does not match" in response.json()["detail"]

    async def test_upload_chunk_422_empty_file(
        self,
        client: AsyncClient,
        registered_device: Device,
        device_token: str,
        device_ids: dict,
    ):
        """Empty file returns 422."""
        response = await client.post(
            "/api/v1/chunks",
            headers={"Authorization": f"Bearer {device_token}"},
            data={
                "point_id": str(device_ids["point_id"]),
                "register_id": str(device_ids["register_id"]),
                "device_id": str(device_ids["device_id"]),
                "start_ts": "2026-01-28T10:00:00+00:00",
                "end_ts": "2026-01-28T10:01:00+00:00",
                "codec": "opus",
                "sample_rate": "48000",
                "channels": "1",
            },
            files={"chunk_file": ("test.ogg", BytesIO(b""), "audio/ogg")},
        )

        assert response.status_code == 422
        assert "Empty file" in response.json()["detail"]

    async def test_upload_chunk_422_invalid_timestamps(
        self,
        client: AsyncClient,
        registered_device: Device,
        device_token: str,
        device_ids: dict,
    ):
        """end_ts before start_ts returns 422."""
        response = await client.post(
            "/api/v1/chunks",
            headers={"Authorization": f"Bearer {device_token}"},
            data={
                "point_id": str(device_ids["point_id"]),
                "register_id": str(device_ids["register_id"]),
                "device_id": str(device_ids["device_id"]),
                "start_ts": "2026-01-28T10:01:00+00:00",
                "end_ts": "2026-01-28T10:00:00+00:00",  # Before start
                "codec": "opus",
                "sample_rate": "48000",
                "channels": "1",
            },
            files={"chunk_file": ("test.ogg", BytesIO(b"test"), "audio/ogg")},
        )

        assert response.status_code == 422
        assert "end_ts must be after start_ts" in response.json()["detail"]


class TestAdminEndpoints:
    """Tests for admin device management endpoints."""

    async def test_create_device(self, client: AsyncClient):
        """Admin can create new device."""
        device_id = uuid4()
        point_id = uuid4()
        register_id = uuid4()

        response = await client.post(
            "/api/v1/admin/devices",
            headers={"Authorization": "Bearer test-admin-token"},
            json={
                "device_id": str(device_id),
                "point_id": str(point_id),
                "register_id": str(register_id),
                "token_plain": "device-token-123456789",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["device_id"] == str(device_id)
        assert data["point_id"] == str(point_id)
        assert data["is_enabled"] is True

    async def test_create_device_401_no_admin_token(self, client: AsyncClient):
        """Creating device without admin token returns 401."""
        response = await client.post(
            "/api/v1/admin/devices",
            json={
                "device_id": str(uuid4()),
                "point_id": str(uuid4()),
                "register_id": str(uuid4()),
                "token_plain": "device-token-123456789",
            },
        )

        assert response.status_code == 401

    async def test_list_devices(
        self,
        client: AsyncClient,
        registered_device: Device,
    ):
        """Admin can list devices."""
        response = await client.get(
            "/api/v1/admin/devices",
            headers={"Authorization": "Bearer test-admin-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert any(d["device_id"] == str(registered_device.device_id) for d in data)

    async def test_disable_device(
        self,
        client: AsyncClient,
        registered_device: Device,
    ):
        """Admin can disable device."""
        response = await client.patch(
            f"/api/v1/admin/devices/{registered_device.device_id}",
            headers={"Authorization": "Bearer test-admin-token"},
            json={"is_enabled": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_enabled"] is False

    async def test_update_nonexistent_device(self, client: AsyncClient):
        """Updating nonexistent device returns 404."""
        response = await client.patch(
            f"/api/v1/admin/devices/{uuid4()}",
            headers={"Authorization": "Bearer test-admin-token"},
            json={"is_enabled": False},
        )

        assert response.status_code == 404


class TestInternalChunkDownload:
    """Tests for GET /api/v1/internal/chunks/{chunk_id}/file endpoint."""

    async def test_download_chunk_401_no_token(
        self,
        client: AsyncClient,
        chunk_with_file: tuple,
    ):
        """Missing Authorization header returns 401."""
        chunk, _ = chunk_with_file

        response = await client.get(
            f"/api/v1/internal/chunks/{chunk.chunk_id}/file",
        )

        assert response.status_code == 401
        assert "Missing Authorization header" in response.json()["detail"]

    async def test_download_chunk_401_invalid_token(
        self,
        client: AsyncClient,
        chunk_with_file: tuple,
    ):
        """Invalid internal token returns 401."""
        chunk, _ = chunk_with_file

        response = await client.get(
            f"/api/v1/internal/chunks/{chunk.chunk_id}/file",
            headers={"Authorization": "Bearer wrong-token"},
        )

        assert response.status_code == 401
        assert "Invalid internal token" in response.json()["detail"]

    async def test_download_chunk_200_with_valid_token(
        self,
        client: AsyncClient,
        chunk_with_file: tuple,
        internal_token: str,
    ):
        """Valid token and chunk_id returns 200 with file content."""
        chunk, audio_content = chunk_with_file

        response = await client.get(
            f"/api/v1/internal/chunks/{chunk.chunk_id}/file",
            headers={"Authorization": f"Bearer {internal_token}"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/ogg"
        assert response.content == audio_content

    async def test_download_chunk_404_nonexistent(
        self,
        client: AsyncClient,
        internal_token: str,
    ):
        """Non-existent chunk_id returns 404."""
        response = await client.get(
            f"/api/v1/internal/chunks/{uuid4()}/file",
            headers={"Authorization": f"Bearer {internal_token}"},
        )

        assert response.status_code == 404
        assert "Chunk not found" in response.json()["detail"]

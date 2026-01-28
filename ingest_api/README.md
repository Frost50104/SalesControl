# Ingest API

Audio chunk ingestion service for SalesControl. Receives audio chunks from Raspberry Pi recorder agents and stores them for processing.

## Features

- RESTful API for audio chunk uploads
- Device authentication via Bearer tokens
- PostgreSQL storage for metadata
- File storage for audio chunks
- Admin API for device management
- Health check endpoint

## Requirements

- Python 3.11+
- PostgreSQL 15+
- Redis 7+ (for future queue integration)

## Quick Start

### Development Setup

1. Create virtual environment:
```bash
cd ingest_api
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

2. Set environment variables (copy from .env.example in infra/):
```bash
export DATABASE_URL="postgresql+asyncpg://ingest:ingest@localhost:5432/ingest"
export AUDIO_STORAGE_DIR="/tmp/ingest_api/audio"
export ADMIN_TOKEN="your-secure-admin-token"
```

3. Run database migrations:
```bash
alembic upgrade head
```

4. Start the service:
```bash
python -m ingest_api.main
```

### Docker Setup

See `infra/docker-compose.yml` for full stack deployment.

```bash
cd infra
docker-compose up -d
```

## API Endpoints

### Chunk Upload

```
POST /api/v1/chunks
Authorization: Bearer <device_token>
Content-Type: multipart/form-data

Form fields:
- point_id: UUID
- register_id: UUID
- device_id: UUID
- start_ts: ISO8601 datetime with timezone
- end_ts: ISO8601 datetime with timezone
- codec: string (e.g., "opus")
- sample_rate: integer (e.g., 48000)
- channels: integer (e.g., 1)

File:
- chunk_file: binary audio file

Response 200:
{
  "status": "ok",
  "chunk_id": "<uuid>",
  "stored_path": "<relative path>",
  "queued": true
}
```

### Admin Endpoints

Create device:
```
POST /api/v1/admin/devices
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "point_id": "<uuid>",
  "register_id": "<uuid>",
  "device_id": "<uuid>",
  "token_plain": "<device_token>"
}
```

List devices:
```
GET /api/v1/admin/devices
Authorization: Bearer <admin_token>
```

Update device:
```
PATCH /api/v1/admin/devices/<device_id>
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "is_enabled": false
}
```

### Health Check

```
GET /health

Response:
{
  "status": "ok",
  "db": true,
  "storage_writable": true,
  "time": "2026-01-28T10:00:00Z"
}
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| DATABASE_URL | postgresql+asyncpg://ingest:ingest@localhost:5432/ingest | PostgreSQL connection URL |
| REDIS_URL | redis://localhost:6379/0 | Redis connection URL |
| AUDIO_STORAGE_DIR | /var/lib/ingest_api/audio | Base directory for audio files |
| MAX_UPLOAD_SIZE_BYTES | 10485760 | Maximum upload size (10 MB) |
| ADMIN_TOKEN | changeme-admin-token | Admin API authentication token |
| HOST | 0.0.0.0 | Server bind address |
| PORT | 8000 | Server port |
| LOG_LEVEL | INFO | Logging level |
| CORS_ENABLED | false | Enable CORS middleware |

## Testing

```bash
pip install -e ".[dev]"
pytest -v
```

## File Storage Structure

Audio files are stored in the following structure:
```
<AUDIO_STORAGE_DIR>/
  audio/
    <point_id>/
      <register_id>/
        <YYYY-MM-DD>/
          <HH>/
            chunk_<start_ts>_<chunk_id>.ogg
```

## Database Schema

### devices
| Column | Type | Description |
|--------|------|-------------|
| device_id | UUID | Primary key |
| point_id | UUID | Point identifier |
| register_id | UUID | Register identifier |
| token_hash | TEXT | SHA-256 hash of device token |
| is_enabled | BOOLEAN | Whether device can upload |
| created_at | TIMESTAMPTZ | Registration timestamp |
| last_seen_at | TIMESTAMPTZ | Last upload timestamp |

### audio_chunks
| Column | Type | Description |
|--------|------|-------------|
| chunk_id | UUID | Primary key |
| device_id | UUID | Foreign key to devices |
| point_id | UUID | Point identifier |
| register_id | UUID | Register identifier |
| start_ts | TIMESTAMPTZ | Chunk start time |
| end_ts | TIMESTAMPTZ | Chunk end time |
| duration_sec | INTEGER | Duration in seconds |
| codec | VARCHAR(32) | Audio codec |
| sample_rate | INTEGER | Sample rate in Hz |
| channels | INTEGER | Number of channels |
| file_path | TEXT | Relative file path |
| file_size_bytes | BIGINT | File size |
| status | VARCHAR(32) | UPLOADED/QUEUED/PROCESSING/DONE/ERROR |
| created_at | TIMESTAMPTZ | Upload timestamp |

Indexes:
- `(point_id, start_ts)` - for querying chunks by point and time
- `(device_id, start_ts)` - for querying chunks by device and time

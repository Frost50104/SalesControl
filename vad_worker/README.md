# VAD Worker

Voice Activity Detection (VAD) worker for SalesControl. Processes audio chunks to detect speech segments and builds dialogues from them.

## Features

- **Voice Activity Detection**: Uses webrtcvad for CPU-efficient speech detection
- **Dialogue Building**: Groups speech segments into dialogues based on silence gaps
- **Cross-chunk Continuity**: Handles dialogues that span multiple audio chunks
- **Graceful Shutdown**: Proper signal handling for container orchestration
- **Structured Logging**: JSON-formatted logs for easy parsing

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐
│ ingest_api  │────▶│  PostgreSQL │◀────│  vad_worker  │
│ (uploads)   │     │  (chunks)   │     │  (processes) │
└─────────────┘     └─────────────┘     └──────────────┘
                           │
                    ┌──────┴──────┐
                    │ Audio Files │
                    │ (shared vol)│
                    └─────────────┘
```

## Database Tables

The worker uses these tables (created by ingest_api migrations):

- `audio_chunks` - Input: chunks with status=QUEUED
- `speech_segments` - Output: detected speech timestamps
- `dialogues` - Output: grouped speech into conversations
- `dialogue_segments` - Output: links dialogues to speech segments
- `device_dialogue_state` - Internal: tracks open dialogues per device

## Processing Flow

1. **Poll**: Fetch batch of chunks with `status=QUEUED` (using `FOR UPDATE SKIP LOCKED`)
2. **Lock**: Update status to `PROCESSING`
3. **Load**: Read audio file from shared storage
4. **VAD**: Run webrtcvad to detect speech frames
5. **Segments**: Convert frames to speech segments with smoothing
6. **Dialogues**: Group segments by silence gaps (<12s) and max duration (120s)
7. **Persist**: Save speech_segments, dialogues, dialogue_segments
8. **Complete**: Update chunk status to `DONE` (or `ERROR` on failure)

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://ingest:ingest@localhost:5432/ingest` | PostgreSQL connection string |
| `AUDIO_STORAGE_DIR` | `/data/audio` | Path to audio files |
| `VAD_AGGRESSIVENESS` | `2` | webrtcvad aggressiveness (0-3, higher = more filtering) |
| `VAD_FRAME_MS` | `30` | Frame duration for VAD (10, 20, or 30 ms) |
| `SILENCE_GAP_SEC` | `12.0` | Max silence within a dialogue |
| `MAX_DIALOGUE_SEC` | `120.0` | Max dialogue duration before splitting |
| `POLL_INTERVAL_SEC` | `5.0` | How often to check for new chunks (1-300s) |
| `BATCH_SIZE` | `10` | Chunks to process per batch (1-100) |
| `MAX_RETRIES` | `3` | Retries for file read errors |
| `RETRY_DELAY_SEC` | `2.0` | Initial retry delay (exponential backoff) |
| `STUCK_TIMEOUT_SEC` | `600` | Requeue chunks stuck in PROCESSING longer than this |
| `RECOVERY_INTERVAL_SEC` | `60` | How often to check for stuck chunks |
| `METRICS_LOG_INTERVAL_SEC` | `60` | How often to log metrics summary |
| `LOG_LEVEL` | `INFO` | Logging level |

### Scaling for 50+ devices

Recommended settings for 50 devices with 1-minute chunks:

```bash
POLL_INTERVAL_SEC=5      # Check every 5s
BATCH_SIZE=10            # Process 10 chunks at a time
STUCK_TIMEOUT_SEC=600    # 10 min timeout for recovery
```

With these settings:
- Max 12 DB polls/minute (low load)
- ~50 chunks/min capacity (matches 50 devices)
- Automatic recovery if worker crashes

## Local Development

```bash
# Create virtual environment
cd vad_worker
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run worker (requires PostgreSQL and audio files)
export DATABASE_URL="postgresql+asyncpg://ingest:ingest@localhost:5432/ingest"
export AUDIO_STORAGE_DIR="./test_audio"
python -m vad_worker.main
```

## Docker

Build and run with Docker Compose (from `infra/` directory):

```bash
cd infra
docker compose up -d

# View logs
docker compose logs -f vad-worker

# Check processing status
docker compose exec postgres psql -U ingest -c "
  SELECT status, COUNT(*)
  FROM audio_chunks
  GROUP BY status;
"
```

## Testing

```bash
# Unit tests
pytest tests/test_dialogue_builder.py -v

# Integration tests (requires test database)
pytest tests/test_integration.py -v

# With coverage
pytest --cov=vad_worker --cov-report=html
```

## Verification

After uploading audio chunks via ingest_api, verify processing:

```sql
-- Check chunk processing status
SELECT
    status,
    COUNT(*) as count,
    MAX(created_at) as latest
FROM audio_chunks
GROUP BY status;

-- View detected speech segments
SELECT
    c.chunk_id,
    c.start_ts,
    s.start_ms,
    s.end_ms,
    (s.end_ms - s.start_ms) as duration_ms
FROM speech_segments s
JOIN audio_chunks c ON c.chunk_id = s.chunk_id
ORDER BY c.start_ts, s.start_ms
LIMIT 20;

-- View dialogues
SELECT
    d.dialogue_id,
    d.device_id,
    d.start_ts,
    d.end_ts,
    EXTRACT(EPOCH FROM (d.end_ts - d.start_ts)) as duration_sec,
    COUNT(ds.chunk_id) as segment_count
FROM dialogues d
LEFT JOIN dialogue_segments ds ON ds.dialogue_id = d.dialogue_id
GROUP BY d.dialogue_id
ORDER BY d.start_ts DESC
LIMIT 20;

-- Check device dialogue state (for debugging)
SELECT * FROM device_dialogue_state;
```

## Monitoring

### Metrics Logging

The worker automatically logs metrics every `METRICS_LOG_INTERVAL_SEC`:

```json
{"message": "Metrics: 15 processed, 12.5/min, 1 errors, avg VAD 0.542s", "metrics": {
  "window_sec": 60.0,
  "chunks_processed": 15,
  "chunks_per_min": 12.5,
  "chunks_errors": 1,
  "chunks_requeued": 0,
  "speech_segments_created": 45,
  "dialogues_created": 8,
  "avg_vad_time_sec": 0.542,
  "avg_total_time_sec": 0.891,
  "error_breakdown": {"FileNotFoundError": 1}
}}
```

### Recovery Events

When stuck chunks are recovered:

```json
{"message": "Requeued 3 stuck chunks", "requeued_count": 3, "chunk_ids": ["550e8400-...", ...]}
```

### JSON Log Fields

| Field | Description |
|-------|-------------|
| `chunks_processed` | Successfully processed in window |
| `chunks_per_min` | Processing rate |
| `chunks_errors` | Failed chunks in window |
| `chunks_requeued` | Stuck chunks recovered |
| `avg_vad_time_sec` | Average VAD processing time |
| `error_breakdown` | Errors by type (for debugging) |

### SQL Monitoring Queries

```sql
-- Current queue status
SELECT status, COUNT(*) FROM audio_chunks GROUP BY status;

-- Stuck chunks (should be 0 if recovery works)
SELECT COUNT(*) FROM audio_chunks
WHERE status = 'PROCESSING'
  AND processing_started_at < NOW() - INTERVAL '10 minutes';

-- Error rate last hour
SELECT
  COUNT(*) FILTER (WHERE status = 'ERROR') as errors,
  COUNT(*) FILTER (WHERE status = 'DONE') as done,
  ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'ERROR') /
        NULLIF(COUNT(*), 0), 2) as error_pct
FROM audio_chunks
WHERE created_at > NOW() - INTERVAL '1 hour';

-- Processing latency (avg time in PROCESSING state)
SELECT
  AVG(EXTRACT(EPOCH FROM (NOW() - processing_started_at))) as avg_processing_sec
FROM audio_chunks
WHERE status = 'PROCESSING';
```

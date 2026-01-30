# ASR Worker

Speech recognition worker using faster-whisper (CTranslate2) for CPU-based transcription.

## Architecture

ASR Worker runs on a **separate VPS** from the core system and:
1. Polls PostgreSQL for dialogues with `asr_status='PENDING'`
2. Fetches audio chunks via HTTP from ingest_api internal endpoint
3. Assembles dialogue audio from multiple segments
4. Transcribes using faster-whisper with optional two-pass strategy
5. Saves transcripts to `dialogue_transcripts` table

## Prerequisites

- Python 3.11+
- ffmpeg (for audio processing)
- Network access to:
  - PostgreSQL database (core server)
  - ingest_api internal endpoint (core server)

## Configuration

All configuration via environment variables:

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://user:pass@core-host:5432/ingest` |
| `INGEST_INTERNAL_BASE_URL` | URL to ingest_api | `http://core-host:8000` |
| `INTERNAL_TOKEN` | Token for internal API auth | `your-secret-token` |

### Whisper Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `WHISPER_MODEL_FAST` | `base` | Model for fast pass |
| `WHISPER_MODEL_ACCURATE` | `small` | Model for accurate pass |
| `WHISPER_COMPUTE_TYPE` | `int8` | Quantization type |
| `WHISPER_THREADS` | `8` | CPU threads |
| `WHISPER_CACHE_DIR` | `/models` | Model cache directory |
| `BEAM_SIZE` | `5` | Beam search size |
| `LANGUAGE` | `ru` | Target language |

### Worker Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `POLL_INTERVAL_SEC` | `5.0` | Poll interval when idle |
| `BATCH_SIZE` | `5` | Dialogues per batch |
| `ASR_STUCK_TIMEOUT_SEC` | `600` | Timeout for stuck dialogues |
| `ASR_RECOVERY_INTERVAL_SEC` | `60` | Recovery check interval |
| `METRICS_LOG_INTERVAL_SEC` | `60` | Metrics logging interval |
| `LOG_LEVEL` | `INFO` | Logging level |

### Heuristics Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `AVG_LOGPROB_THRESHOLD` | `-0.7` | Trigger accurate pass below this |
| `MIN_TEXT_LENGTH_RATIO` | `0.5` | Min chars per second |
| `MIN_DURATION_FOR_ACCURATE` | `15.0` | Min seconds for accurate pass |

## Two-Pass Strategy

1. **Fast Pass**: Uses smaller model (base) for quick transcription
2. **Heuristics Check**: Analyzes confidence and quality metrics
3. **Accurate Pass** (if needed): Re-transcribes with larger model (small)

Triggers for accurate pass:
- Low avg_logprob (low confidence)
- Text too short for audio duration
- High "garbage" score in text
- High no_speech_prob with text present

## Deployment

### On Core Server (ingest_api)

Enable internal endpoint by setting `INTERNAL_TOKEN`:

```bash
# In infra/.env
INTERNAL_TOKEN=your-secret-internal-token
```

### On ASR VPS

1. Build the image:
```bash
docker build -t asr-worker .
```

2. Run with environment:
```bash
docker run -d \
  -e DATABASE_URL=postgresql+asyncpg://ingest:ingest@core-host:5432/ingest \
  -e INGEST_INTERNAL_BASE_URL=http://core-host:8000 \
  -e INTERNAL_TOKEN=your-secret-internal-token \
  -e WHISPER_THREADS=4 \
  -v /data/models:/models \
  --name asr-worker \
  asr-worker
```

### Using Docker Compose

See `infra/docker-compose.yml` for the full service definition.

For a separate ASR VPS, create a minimal compose file:

```yaml
version: "3.9"
services:
  asr-worker:
    image: asr-worker:latest
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql+asyncpg://ingest:ingest@core-host:5432/ingest
      - INGEST_INTERNAL_BASE_URL=http://core-host:8000
      - INTERNAL_TOKEN=${INTERNAL_TOKEN}
      - WHISPER_MODEL_FAST=base
      - WHISPER_MODEL_ACCURATE=small
      - WHISPER_COMPUTE_TYPE=int8
      - WHISPER_THREADS=4
    volumes:
      - models:/models
volumes:
  models:
```

## Verification

1. Upload audio chunks from recorder device
2. Wait for VAD worker to create dialogues
3. Check dialogue status:
```sql
SELECT dialogue_id, asr_status, asr_pass, asr_model
FROM dialogues
ORDER BY created_at DESC
LIMIT 10;
```

4. Check transcripts:
```sql
SELECT dt.dialogue_id, dt.language, dt.text, dt.avg_logprob
FROM dialogue_transcripts dt
JOIN dialogues d ON dt.dialogue_id = d.dialogue_id
WHERE d.asr_status = 'DONE'
ORDER BY dt.created_at DESC
LIMIT 10;
```

## Metrics

Logged every minute:
- `dialogues_processed`: Total processed
- `dialogues_per_min`: Throughput
- `dialogues_errors`: Error count
- `fast_passes` / `accurate_passes`: Pass breakdown
- `avg_asr_time_sec`: Average ASR time
- `rtf`: Real-Time Factor (ASR time / audio duration)

RTF < 1.0 means faster than real-time.

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run locally
python -m asr_worker.main
```

## Troubleshooting

### Model Download

Models are downloaded on first use. Pre-download:

```python
from faster_whisper import WhisperModel
WhisperModel("base", device="cpu", download_root="/models")
WhisperModel("small", device="cpu", download_root="/models")
```

### Connection Issues

- Verify PostgreSQL is accessible from ASR VPS
- Verify ingest_api internal endpoint is accessible
- Check firewall rules for ports 5432 (Postgres) and 8000 (ingest_api)

### High RTF

If RTF > 1.0 (slower than real-time):
- Increase `WHISPER_THREADS`
- Use smaller model (`tiny` for fast pass)
- Use `int8` compute type
- Consider GPU deployment

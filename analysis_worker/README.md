# Analysis Worker

LLM-based upsell analysis worker for SalesControl. Analyzes dialogue transcripts to detect and evaluate upselling behavior.

## Overview

The Analysis Worker processes dialogues that have been transcribed by the ASR worker and evaluates:
- Whether an upsell attempt was made (`yes`/`no`/`uncertain`)
- Quality of the upsell attempt (0-3 scale)
- Categories of products offered (coffee_size, dessert, pastry, etc.)
- Presence of a closing question
- Customer reaction (accepted/rejected/unclear)
- Evidence quotes from the transcript
- Brief summary explanation

## Architecture

```
PostgreSQL (dialogues + dialogue_transcripts)
    ↓ (polling: asr_status='DONE', analysis_status='PENDING')
Analysis Worker
    ↓ (prefilter: skip short/empty dialogues)
    ↓ (OpenAI API: Responses API with structured outputs)
    ↓ (save to dialogue_upsell_analysis)
PostgreSQL
```

## Configuration

All configuration via environment variables:

### Required

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (asyncpg format) |
| `OPENAI_API_KEY` | OpenAI API key (never logged) |

### OpenAI Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_MODEL` | `gpt-4o-mini` | Model to use (recommended for cost/quality) |
| `OPENAI_TIMEOUT_SEC` | `60.0` | API request timeout |
| `OPENAI_MAX_RETRIES` | `3` | Max retry attempts |
| `OPENAI_BASE_DELAY_SEC` | `1.0` | Base delay for exponential backoff |

### Prefilter Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PREFILTER_ENABLED` | `true` | Enable/disable prefilter |
| `PREFILTER_MIN_TEXT_LEN` | `10` | Skip transcripts shorter than this |
| `PREFILTER_MIN_DURATION_SEC` | `6.0` | Dialogues shorter than this need markers |
| `PREFILTER_UPSELL_MARKERS` | `еще,также,...` | Comma-separated upsell markers |

### Worker Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `POLL_INTERVAL_SEC` | `5.0` | Interval between polling when idle |
| `BATCH_SIZE` | `10` | Max dialogues per batch |
| `ANALYSIS_STUCK_TIMEOUT_SEC` | `600` | Requeue PROCESSING dialogues after this |
| `ANALYSIS_RECOVERY_INTERVAL_SEC` | `60` | Interval for stuck recovery check |
| `METRICS_LOG_INTERVAL_SEC` | `60` | Interval for metrics logging |
| `LOG_LEVEL` | `INFO` | Logging level |

## Setting up OPENAI_API_KEY

### Option 1: Environment file (.env)

Create a `.env` file in the infra directory (never commit this file):

```bash
OPENAI_API_KEY=sk-your-key-here
```

### Option 2: Docker secrets (recommended for production)

```bash
echo "sk-your-key-here" | docker secret create openai_api_key -
```

Then reference in docker-compose:

```yaml
secrets:
  openai_api_key:
    external: true

services:
  analysis-worker:
    secrets:
      - openai_api_key
    environment:
      - OPENAI_API_KEY_FILE=/run/secrets/openai_api_key
```

### Option 3: Direct environment variable

```bash
export OPENAI_API_KEY=sk-your-key-here
docker-compose up -d analysis-worker
```

## Choosing OPENAI_MODEL

Recommended models by use case:

| Model | Cost | Quality | Speed | Best for |
|-------|------|---------|-------|----------|
| `gpt-4o-mini` | $ | Good | Fast | Production (default) |
| `gpt-4o` | $$$ | Excellent | Medium | High-stakes analysis |
| `gpt-4-turbo` | $$ | Very Good | Medium | Balanced |

For Russian language analysis, `gpt-4o-mini` provides good quality at low cost.

## Verification

### Check dialogue_transcripts exist

```sql
SELECT COUNT(*) FROM dialogue_transcripts;
SELECT dialogue_id, text, created_at
FROM dialogue_transcripts
ORDER BY created_at DESC
LIMIT 5;
```

### Check analysis worker is writing results

```sql
-- Check analysis statuses
SELECT analysis_status, COUNT(*)
FROM dialogues
WHERE asr_status = 'DONE'
GROUP BY analysis_status;

-- Check recent analyses
SELECT
    dua.dialogue_id,
    dua.attempted,
    dua.quality_score,
    dua.categories,
    dua.summary,
    dua.created_at
FROM dialogue_upsell_analysis dua
ORDER BY dua.created_at DESC
LIMIT 10;
```

### Check analytics endpoint

```bash
# Daily aggregates
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:8000/api/v1/analytics/daily?date=2026-01-30"

# Dialogue list
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:8000/api/v1/analytics/dialogues?date=2026-01-30&min_quality=2"
```

## Running Locally

```bash
cd analysis_worker

# Install dependencies
pip install -e ".[dev]"

# Set environment
export DATABASE_URL=postgresql+asyncpg://ingest:ingest@localhost:5432/ingest
export OPENAI_API_KEY=sk-your-key-here

# Run worker
python -m analysis_worker.main
```

## Running Tests

```bash
cd analysis_worker
pip install -e ".[dev]"
pytest tests/ -v
```

## Docker

Build and run:

```bash
docker build -t analysis-worker .
docker run --rm \
  -e DATABASE_URL=postgresql+asyncpg://... \
  -e OPENAI_API_KEY=sk-... \
  analysis-worker
```

## Metrics

The worker logs metrics every minute:

```json
{
  "dialogues_processed": 42,
  "processed_per_min": 7.0,
  "dialogues_skipped": 5,
  "dialogues_errors": 1,
  "llm_calls": 42,
  "avg_llm_latency_sec": 1.234,
  "avg_quality_score": 1.85,
  "attempted_breakdown": {"yes": 25, "no": 12, "uncertain": 5}
}
```

## Troubleshooting

### "OPENAI_API_KEY not configured"

Set the `OPENAI_API_KEY` environment variable.

### "Structured outputs not supported"

The worker automatically falls back to JSON mode if the model doesn't support structured outputs. This is logged as a warning.

### High error rate

Check the `error_breakdown` in metrics. Common issues:
- `RateLimitError`: Reduce `BATCH_SIZE` or increase `OPENAI_BASE_DELAY_SEC`
- `ValidationError`: Model returning invalid JSON (report if persistent)
- `APIConnectionError`: Network issues

### Dialogues stuck in PROCESSING

The recovery loop automatically requeues stuck dialogues after `ANALYSIS_STUCK_TIMEOUT_SEC`. Check logs for "Recovered X stuck dialogues".

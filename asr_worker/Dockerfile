# ASR Worker Dockerfile
# Python 3.11 + ffmpeg for audio processing
FROM python:3.11-slim

# Install ffmpeg and other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Copy application code
COPY asr_worker/ ./asr_worker/

# Create directories
RUN mkdir -p /tmp/asr_worker/chunks /models

# Create non-root user
RUN useradd -m -u 1000 worker && \
    chown -R worker:worker /app /tmp/asr_worker /models
USER worker

# Environment defaults
ENV AUDIO_TMP_DIR=/tmp/asr_worker
ENV WHISPER_CACHE_DIR=/models

# Default command
CMD ["python", "-m", "asr_worker.main"]

# VAD Worker Dockerfile
FROM python:3.11-slim

# Install ffmpeg and build tools (gcc needed for webrtcvad)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gcc \
    libc-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy application code first (needed for pip install)
COPY pyproject.toml .
COPY vad_worker/ ./vad_worker/

# Install dependencies
RUN pip install --no-cache-dir .

# Create non-root user
RUN useradd -m -u 1000 worker && chown -R worker:worker /app
USER worker

# Default command
CMD ["python", "-m", "vad_worker.main"]

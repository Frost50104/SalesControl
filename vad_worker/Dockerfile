# VAD Worker Dockerfile
FROM python:3.11-slim

# Install ffmpeg for audio processing (required by pydub)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# Copy application code
COPY vad_worker/ ./vad_worker/

# Create non-root user
RUN useradd -m -u 1000 worker && chown -R worker:worker /app
USER worker

# Default command
CMD ["python", "-m", "vad_worker.main"]

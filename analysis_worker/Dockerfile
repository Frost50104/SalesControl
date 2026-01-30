# Analysis Worker Dockerfile
# Python 3.11 - lightweight, no ffmpeg needed (text-only processing)
FROM python:3.11-slim

WORKDIR /app

# Copy application code
COPY pyproject.toml .
COPY analysis_worker/ ./analysis_worker/

# Install dependencies
RUN pip install --no-cache-dir .

# Create non-root user
RUN useradd -m -u 1000 worker && \
    chown -R worker:worker /app
USER worker

# Default command
CMD ["python", "-m", "analysis_worker.main"]

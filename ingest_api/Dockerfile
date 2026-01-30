FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Copy dependency files first for better caching
COPY pyproject.toml README.md ./

# Install dependencies
RUN pip install --no-cache-dir .

# Copy application code
COPY ingest_api/ ./ingest_api/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Create storage directory
RUN mkdir -p /var/lib/ingest_api/audio && chown -R appuser:appuser /var/lib/ingest_api

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["python", "-m", "ingest_api.main"]

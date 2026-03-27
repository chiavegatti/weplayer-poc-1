# ─── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

# Install FFmpeg and system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/
COPY static/ ./static/

# Create storage dir
RUN mkdir -p /app/storage/weplayer/videos

# ─── Runtime ──────────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_URL=sqlite:////app/data/weplayer.db \
    STORAGE_DIR=/app/storage/weplayer \
    DEBUG=false

EXPOSE 8000

# Persistent volumes
VOLUME ["/app/data", "/app/storage"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ==============================================================================
# CleanNotes PrintFlow POS (B2B Server) — Hardened Multi-Stage Production Dockerfile
# Self-contained inside apps/shopkeeper-web/
# Security: Non-root user (appuser:10001), minimal slim image, zero build tools in final
# ==============================================================================

# Stage 1: Build dependencies & compile binary wheels
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Hardened, production-ready runtime
FROM python:3.12-slim AS runner

WORKDIR /app

# Install minimal shared runtime libraries for PyMuPDF and headless OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source code (server + static assets)
COPY --chown=appuser:appgroup server /app/server
COPY --chown=appuser:appgroup public /app/public

# Create persistent data directory for SQLite WAL
RUN mkdir -p /app/server/data && \
    chown -R appuser:appgroup /app/server/data

# Environment configuration
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8001 \
    DOCUMORPH_ENV=production \
    DOCUMORPH_B2B_DB=/app/server/data/b2b.db

# Drop root privileges
USER appuser

EXPOSE 8001

# Healthcheck probe for Cloud Run / Docker container orchestration
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8001/api/health || exit 1

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8001"]

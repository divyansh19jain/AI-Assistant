# syntax=docker/dockerfile:1
# Production image for the FastAPI backend.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# psycopg[binary] and pymupdf ship manylinux wheels, so no compiler/libpq is needed.
# curl is only used by the container HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Drop any host virtualenv that slipped past .dockerignore, create the writable PDF
# output dir, and run as a non-root user.
RUN rm -rf .venv \
    && mkdir -p app/pdf/generated_pdfs \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Single worker keeps startup seeding race-free (each worker runs the lifespan
# seed/cache warm). Scale out with replicas behind a proxy rather than --workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# Trading AI SaaS V3 — FastAPI application image
# Python 3.11-slim keeps the layer small; libpq-dev is required at build time
# by psycopg2-binary's C extension.

FROM python:3.11-slim

# Keeps Python from writing .pyc files and buffers stdout/stderr immediately
# so container logs are never delayed.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install OS-level build deps in one layer, then clean up in the same RUN
# so the apt cache is never committed to the image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first so Docker can cache this layer independently of
# source-code changes — pip install only re-runs when requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source after dependencies so code edits don't bust the
# expensive pip-install cache layer.
COPY . .

EXPOSE 8000

# Run with 2 workers in the container. Scale horizontally (more replicas)
# rather than vertically (more workers per container) so each container's
# asyncpg pool stays predictable.
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info"]

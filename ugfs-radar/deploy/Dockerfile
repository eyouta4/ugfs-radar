FROM python:3.11-slim AS base

# Dépendances système (psycopg2 + lxml feedparser, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install requirements (couche cache séparée)
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# Code source
COPY src ./src
COPY scripts ./scripts
COPY data ./data

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000

# Healthcheck (fonctionne avec uvicorn)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Par défaut on démarre l'API. Le worker scheduler est démarré
# via un autre service (cf. railway.toml).
CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT}"]

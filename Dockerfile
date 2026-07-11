# GRIDIX control-plane image (API + scheduler share this image; entrypoint differs).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/api

WORKDIR /app

# Install dependencies first for layer caching.
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.110" "uvicorn[standard]>=0.29" "sqlalchemy[asyncio]>=2.0" "asyncpg>=0.29" \
    "alembic>=1.13" "pydantic>=2.6" "pydantic-settings>=2.2" "redis>=5.0" "loguru>=0.7" \
    "python-multipart>=0.0.9" "prometheus-client>=0.20"

COPY alembic.ini ./
COPY alembic ./alembic
COPY api ./api
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 gridix
USER gridix

EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["api"]

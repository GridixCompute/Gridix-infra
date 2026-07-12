# GRIDIX control-plane image (API + scheduler share this image; entrypoint differs).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/api

WORKDIR /app

# Install the control-plane package and its dependencies straight from pyproject — the
# single source of truth, so the image can never drift from the declared dependency set
# (a hand-maintained pip list previously omitted cryptography and httpx).
COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY api ./api
# Optional extras (e.g. EXTRAS="[s3]" to bundle the aioboto3 S3 backend). Default: none.
ARG EXTRAS=""
# Install the app, then upgrade the bundled build tooling to non-vulnerable versions so the
# image passes the Trivy HIGH/CRITICAL gate (wheel / jaraco.context ship with fixable CVEs).
RUN pip install --no-cache-dir ".${EXTRAS}" \
    && pip install --no-cache-dir --upgrade pip setuptools "wheel>=0.46.2" "jaraco.context>=6.1.0"

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Run as an unprivileged user; pre-create the blob dir it owns so the mounted volume
# initializes with writable ownership (the process is non-root by design).
RUN useradd --create-home --uid 10001 gridix \
    && mkdir -p /data/blobs \
    && chown -R gridix:gridix /data/blobs
USER gridix

EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["api"]

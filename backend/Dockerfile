FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system meetai && useradd --system --gid meetai --create-home meetai
WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --upgrade pip && pip install .

# The local-storage fallback (used when S3 is not configured) must be writable
# by the unprivileged meetai user. NOTE: Render's filesystem is ephemeral, so
# recordings saved here are lost on redeploy/restart — durable uploads require
# S3-compatible storage (AWS S3 / Cloudflare R2 / Backblaze B2).
RUN mkdir -p /app/local_storage && chown -R meetai:meetai /app/local_storage

USER meetai
EXPOSE 8000
# Migrations are idempotent (fresh-install safe), so running them at boot is
# cheap and lets the container provision a brand-new database on first deploy.
# Retry a few times first: the DB (e.g. a free tier that powers off when idle)
# may not be reachable during the very first seconds after deploy.
CMD ["sh", "-c", "i=0; until alembic upgrade head; do i=$((i+1)); [ $i -ge 10 ] && break; echo 'database not ready, retrying in 5s'; sleep 5; done; uvicorn app.main:app --host 0.0.0.0 --port 8000"]


# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MeetAI is a tenant-safe meeting intelligence system that converts audio/video recordings into immutable raw transcripts, reproducible cleaned chunks, semantic search evidence, and cited answers. The system is designed to support future browser-based meeting bots while providing a stable web platform for ingest and retrieval.

## Architecture

### Monorepo Structure

```
D:/MeetRAG/
├── backend/          # FastAPI with Celery workers
│   ├── app/
│   │   ├── api/       # REST API endpoints (auth, meetings, search, admin)
│   │   ├── models/    # SQLAlchemy ORM entities and enums
│   │   ├── schemas/   # Pydantic request/response models
│   │   ├── services/  # Core business logic (cleaning, chunking, embedding, retrieval, answering)
│   │   ├── workers/   # Celery task definitions
│   │   ├── core/      # Configuration, security, logging, middleware
│   │   └── db/        # Session management and alembic
├── frontend/          # Next.js 15 React application
│   └── app/           # App router with pages for upload, meetings, search, login, admin
├── docker-compose.yml # Production + local dev stack (including LocalStack for S3)
└── docs/              # Production guidelines
```

### Technology Stack

**Backend:**
- FastAPI + uvicorn (API)
- Celery + redis (distributed task queue)
- SQLAlchemy + Alembic (ORM + migrations)
- MySQL 8.4 (database)
- Qdrant (vector store)
- boto3 (S3)
- structlog (structured logging)
- JWT authentication with password hashing
- ORJSON for performance

**Frontend:**
- Next.js 15 (React app router)
- TypeScript
- React Query for data fetching
- Lucide React icons

### Data Pipeline

The system processes meetings through four staged idempotent Celery tasks:

1. **Transcribe** (JobStage.TRANSCRIBE) - Downloads recording, calls Groq Whisper API for transcription
2. **Clean** (JobStage.CLEAN) - Standardizes transcript formats, speaker attribution
3. **Chunk** (JobStage.CHUNK) - Generates semantic chunks with source segment references
4. **Embed & Index** (JobStage.EMBED_INDEX) - Embeds chunks via OpenRouter, creates Qdrant vectors

Each stage is versioned, retryable, and preserves raw transcript immutability. Reprocessing deactivates vectors and regenerates artifacts.

### Security Model

- JWT access tokens (15-minute TTL) derive tenant ownership from verified claims
- Opaque refresh tokens rotated and stored as SHA-256 digests
- API queries never trust client-supplied tenant IDs
- Raw transcript updates/deletes blocked by ORM hooks and MySQL triggers
- Production requires: TLS, private networking, KMS encryption, Secrets Manager, restricted CORS, `ALLOW_PUBLIC_SIGNUP=false`

### Tenant Isolation

All data (meetings, transcription, chunks, vectors, searches) has `tenant_id` foreign keys. Vector retrieval validates against MySQL before returning points. Search queries and answers are audit-tracked. Legal deletion requires tenant-erasure workflow, not individual row mutation.

## Development Commands

### Backend (CD into `backend/`)
```bash
# Install development dependencies
python -m pip install -e ".[dev]"

# Run code quality checks
ruff check app tests
mypy app

# Run tests
pytest  # Async tests with --asyncio-mode=auto

# Run database migrations
alembic upgrade head
alembic downgrade -1
alembic edit <revision>  # Edit existing migration

# Run with live reload
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Start Celery worker for pipeline queues
celery -A app.workers.celery_app:celery_app worker --loglevel=INFO --queues=pipeline,dead_letter

# Run shell with db session
poetry run python -c "from app.db.sync_session import SyncSessionLocal; from app.models import Meeting; print(SyncSessionLocal().query(Meeting).count())"
```

### Frontend (CD into `frontend/`)
```bash
# Install dependencies
npm install

# Type checking
npm run typecheck  # tsc --noEmit --incremental false

# Linting
npm run lint  # eslint .

# Build for production
npm run build

# Run with hot reload
npm run dev

# Check everything before commit
npm run check  # typecheck && lint
```

### Full Stack (from root)
```bash
# Start all services with local Qdrant
docker compose --profile local-qdrant up --build

# Start only API, worker, MySQL, Redis, LocalStack
docker compose up --build

# Stop services
docker compose down -v

# Load demo seed data
DATABASE_URL="mysql+asyncmy://meetai:password@localhost:3307/meetai" alembic upgrade head && python -c "from tests.conftest import seed_test_data; seed_test_data()"
```

## Configuration

All configuration via `.env` file (not committed). Key defaults:

- `GROQ_API_KEY`, `OPENROUTER_API_KEY` - External service keys (blank in `.env`)
- `SECRET_KEY` - Development default, must change for production
- `QDRANT_URL` - Cloud by default (`http://localhost:6333` for local)
- `aws_endpoint_url` - LocalStack for local dev (`http://localhost:4566`)
- Model versions: `groq_stt_model`, `cleaning_version`, `chunking_version`, `openrouter_embedding_model`
- Pipeline settings: `chunk_target_tokens`, `retrieval_top_k`, `retrieval_score_threshold`

See `backend/app/core/config.py` for all `Settings` fields.

## Key Migration Notes

- MySQL indexes with utf8mb4 can exceed 3072 bytes; ensure composite unique indexes are under this limit
- 使用本地时间 Cron: 没有时区 ff
- Raw transcript immutability and audit invariants are never broken by writes, only deleted
- Prod 用户体验: disable `/docs` endpoint and app health checks ingestion exposure

## Common Pitfalls

1. **Model version mismatches**: Chunking/cleaning/answer prompts must be upgraded in lockstep; changing `cleaning_version` requires versioned task versions; see STAGE_VERSION in `workers/tasks.py`

2. **Vector reindexing**: Only deactivates existing vectors; never mutates raw content. Full reindex requires a reprocessing run with new version sentinel.

3. **Tenant boundaries**: Always pass `tenant_id` from auth claims; never accept from request body. The `deps.py` dependency injection enforces this via `get_current_user`.

4. **Async/sync session mixing**: Storage operations (boto3) are sync but custom S3 client interface is async; ensure you import `app.services.storage.internal_s3_client()` (returns sync client wrapped via `asyncio.to_thread`) not raw boto3.

5. **Encoding**: MySQL utf8mb4 requires strict limit on index expressions; recording object keys are truncated to <512 chars to fit the composite unique index.

6. **JWT token expiration**: Access tokens expire in 15 min; refresh cookie is 30 days. Frontend must handle refresh token flow for long-lived sessions.

7. **Qdrant local vs cloud**: Default `docker compose.yml` connects to Qdrant cloud; local dev uses `docker compose --profile local-qdrant up`. Check `QDRANT_URL` matches expectation.

8. **LocalStack CORS**: LocalStack automatically adds browser CORS rules for containers accessing `http://localhost:4566`. Local dev can upload directly; production should remove `AWS_ENDPOINT_URL` to use native S3.

9. **Celery dead letters**: Worker restarts preserve job state; dead-lettered jobs require manual investigation or `/admin/jobs/{id}/replay` endpoint. Jobs are idempotent by design.

10. **Embedding bounds**: OpenRouter embedding is 384-dim; ensure `qdrant_collection` uses this dimension; batch size is 32 in `tasks.py/_run_embed_index`.

## Extension Compatibility

The ingestion pipeline already supports provider-agnostic recording metadata (`source`, `external_meeting_id`). Future meeting bots should call the same `/api/v1/meetings/{id}/ingest` endpoint using a service identity with `ALLOW_PUBLIC_SIGNUP=false`. Bot coordination and permission handling should live in separate packages.

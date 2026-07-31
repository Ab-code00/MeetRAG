# MeetAI

**Tenant-safe meeting intelligence** — Turn recordings into immutable transcripts, semantic search, and grounded answers with citations.

MeetAI is a production-ready platform that ingests audio/video recordings, transcribes them via Groq Whisper, stores the raw transcript as an immutable source of truth, deterministically cleans and chunks the text, generates 384-dim embeddings via OpenRouter, indexes them in Qdrant for metadata-filtered vector search, and answers user questions grounded in retrieved evidence. Every stage is async, idempotent, retryable, and observable.

---

## Table of Contents

- [Architecture overview](#architecture-overview)
- [Technology stack](#technology-stack)
- [Repository structure](#repository-structure)
- [Data pipeline](#data-pipeline)
  - [1. Upload & ingest](#1-upload--ingest)
  - [2. Transcribe](#2-transcribe)
  - [3. Clean](#3-clean)
  - [4. Chunk](#4-chunk)
  - [5. Embed & index](#5-embed--index)
- [API endpoints](#api-endpoints)
- [Database model](#database-model)
- [Security model](#security-model)
- [Tenant isolation](#tenant-isolation)
- [Local development](#local-development)
  - [Prerequisites](#prerequisites)
  - [Quick start with Docker](#quick-start-with-docker)
  - [Manual setup](#manual-setup)
- [Configuration](#configuration)
- [Development commands](#development-commands)
- [Testing](#testing)
- [Production deployment](#production-deployment)
- [Observability](#observability)
- [FAQ / Common pitfalls](#faq--common-pitfalls)

---

## Architecture overview

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Browser     │────▶│  FastAPI API  │────▶│  Celery Workers   │
│  (Next.js)   │     │  (:8000)     │     │  (pipeline queue) │
└─────────────┘     └──────┬───────┘     └────────┬─────────┘
                           │                      │
                           ▼                      ▼
                    ┌──────────────┐     ┌──────────────────┐
                    │  PostgreSQL   │     │  Qdrant           │
                    │  (SQLAlchemy) │     │  (Vector Store)   │
                    │  System of    │     │  Retrieval only   │
                    │  record       │     │                   │
                    └──────────────┘     └──────────────────┘
                           │                      ▲
                           ▼                      │
                    ┌──────────────┐     ┌──────────────────┐
                    │  Redis        │     │  S3 (LocalStack)  │
                    │  (Celery      │     │  Recording store  │
                    │   broker+     │     │                  │
                    │   backend)    │     └──────────────────┘
                    └──────────────┘
```

Two key architectural principles:

1. **MySQL is the system of record.** Raw transcripts, cleaned chunks, jobs, search queries, and answers all live in SQL with full lineage. Qdrant is **only** for fast vector retrieval — every Qdrant point maps back to a MySQL row and is revalidated before use.
2. **Raw transcripts are immutable.** SQLAlchemy ORM hooks (`before_update`, `before_delete`) and MySQL triggers both reject any mutation of `transcripts_raw` or `transcript_segments_raw`. Legal deletion requires a complete tenant erasure workflow.

---

## Technology stack

| Layer | Technology | Purpose |
|---|---|---|
| **API** | FastAPI + Uvicorn (ORJSON responses) | REST endpoints, health checks, Prometheus metrics |
| **Workers** | Celery 5.x + Redis | Async, idempotent, retryable pipeline stages |
| **Database** | MySQL 8.4 (utf8mb4) + SQLAlchemy 2.0 + Alembic | System of record, migrations |
| **Vector store** | Qdrant (384-dim, Cosine distance, `meeting_chunks` collection) | Metadata-filtered semantic retrieval |
| **Storage** | AWS S3 (LocalStack for dev, boto3 SDK) | Recording file storage, presigned upload URLs |
| **STT** | Groq (`whisper-large-v3`) | Speech-to-text transcription |
| **Embeddings** | OpenRouter (`sentence-transformers/all-minilm-l6-v2`, 384-dim) | Text embedding generation |
| **LLM** | OpenRouter (`openai/gpt-oss-120b:free`) | Grounded answer generation with citations |
| **Frontend** | Next.js 15 (App Router), TypeScript, React Query, Lucide icons | Web UI for upload, search, Q&A, admin |
| **Auth** | JWT (HS256, 15-min access) + opaque refresh tokens (SHA-256, 30-day) | Tenant-safe authentication |
| **Logging** | structlog (JSON, correlation IDs) | Structured observability |
| **Metrics** | Prometheus client | HTTP request count/latency |

---

## Repository structure

```
D:/MeetRAG/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app entry point, lifespan, routes, health checks
│   │   ├── core/
│   │   │   ├── config.py           # Pydantic Settings (all env vars)
│   │   │   ├── security.py         # JWT create/decode, password hashing, refresh tokens
│   │   │   ├── logging.py          # structlog JSON configuration
│   │   │   └── middleware.py       # CorrelationMiddleware, Prometheus metrics
│   │   ├── db/
│   │   │   ├── base.py             # SQLAlchemy Base, UUIDPrimaryKeyMixin, TimestampMixin
│   │   │   ├── session.py          # AsyncSession factory (asyncmy)
│   │   │   └── sync_session.py     # SyncSession factory (pymysql, for Celery workers)
│   │   ├── models/
│   │   │   ├── entities.py         # 14 ORM models (Tenant, User, Meeting, Recording, etc.)
│   │   │   ├── enums.py            # UserRole, MeetingStatus, JobStage, JobStatus, RecordingStatus
│   │   │   └── __init__.py         # Re-export all models
│   │   ├── schemas/
│   │   │   ├── auth.py             # Register/Login/Refresh/Token/User schemas
│   │   │   ├── meetings.py         # Create/Upload/Transcript/Job/Reprocess schemas
│   │   │   └── search.py           # Search/Ask/Filters/Citation schemas
│   │   ├── api/
│   │   │   ├── router.py           # Aggregates all route groups
│   │   │   ├── deps.py             # AuthContext, DbSession, role-based dependency injection
│   │   │   └── routes/
│   │   │       ├── auth.py         # POST /auth/register, /login, /refresh, /logout, GET /me
│   │   │       ├── meetings.py     # CRUD, upload presigned URL, transcript, jobs, reprocess
│   │   │       ├── search.py       # POST /search, /ask
│   │   │       └── admin.py        # GET /admin/jobs, POST /admin/jobs/{id}/retry
│   │   ├── services/
│   │   │   ├── transcription.py    # Groq Whisper integration, segment parsing, S3 download
│   │   │   ├── cleaner.py          # Deterministic regex-based text cleaning
│   │   │   ├── chunker.py          # Speaker-turn-aware semantic chunking with overlap
│   │   │   ├── openrouter.py       # Embeddings API + LLM completion via OpenRouter
│   │   │   ├── retrieval.py        # Semantic search: embed -> Qdrant -> MySQL revalidate
│   │   │   ├── answering.py        # Grounded answer generation with citation extraction
│   │   │   ├── vector_store.py     # Qdrant client, collection, upsert, search, deactivate
│   │   │   ├── vector_store_stub.py # No-op stub for local dev without Qdrant
│   │   │   ├── storage.py          # S3 presigned URLs, download, object key generation
│   │   │   └── audit.py            # Structured audit log helper
│   │   └── workers/
│   │       ├── celery_app.py       # Celery app config (broker, queues, serialization)
│   │       └── tasks.py            # Pipeline stages: transcribe -> clean -> chunk -> embed_index
│   ├── alembic/
│   │   ├── versions/
│   │   │   └── 20260718_0001_initial.py   # Initial schema + MySQL immutability triggers
│   │   ├── env.py                  # Alembic env configuration
│   │   └── script.py.mako          # Migration template
│   ├── tests/
│   │   ├── test_cleaner.py         # Deterministic cleaning tests
│   │   ├── test_chunker.py         # Lineage, overlap, time range tests
│   │   ├── test_transcription.py   # Segment parsing tests
│   │   └── test_security.py        # Password hash + JWT roundtrip tests
│   ├── Dockerfile                  # Python 3.11 slim runtime
│   └── pyproject.toml              # Dependencies, ruff, mypy, pytest config
├── frontend/
│   ├── app/
│   │   ├── layout.tsx              # Root layout (Inter font, AppProviders, styles)
│   │   ├── page.tsx                # Dashboard: meetings list with summary strip
│   │   ├── styles.css              # Full design system (~600 lines CSS)
│   │   ├── login/page.tsx          # AuthForm in login mode
│   │   ├── register/page.tsx       # AuthForm in register mode
│   │   ├── upload/page.tsx         # File upload form with progress bar
│   │   ├── meetings/
│   │   │   └── [id]/page.tsx       # Meeting detail, raw/clean toggle, reprocess
│   │   ├── search/page.tsx         # Ask a question / Search evidence with citations
│   │   └── admin/
│   │       └── jobs/page.tsx       # Job inspector with manual retry
│   ├── components/
│   │   ├── app-providers.tsx       # React Query client setup
│   │   ├── app-shell.tsx           # Sidebar layout, mobile nav, auth guard
│   │   ├── auth-form.tsx           # Login/register form (workspace + credentials)
│   │   ├── status-pill.tsx         # Color-coded status badges
│   │   └── ui.tsx                  # PageHeader, EmptyState, formatTime
│   ├── lib/
│   │   ├── api.ts                  # API client (auto-refresh, retry, error handling)
│   │   └── types.ts                # MeetingStatus, Meeting, SearchResult types
│   ├── Dockerfile                  # Next.js standalone build
│   ├── next.config.ts              # Standalone output, strict mode
│   └── package.json                # React 19, Next.js 15, React Query 5, Lucide
├── docker-compose.yml              # Full stack: mysql, redis, qdrant, localstack, api, worker, frontend
├── Makefile                        # setup, up, down, logs, migrate, test, lint
├── docs/
│   └── production.md               # AWS deployment, alerts, data lifecycle
└── infra/
    └── localstack/
        └── init/
            └── 01-create-bucket.sh  # Creates S3 bucket + CORS on LocalStack startup
```

---

## Data pipeline

The system processes meetings through four staged, versioned, idempotent Celery tasks:

```
upload ──▶ TRANSCRIBE ──▶ CLEAN ──▶ CHUNK ──▶ EMBED_INDEX ──▶ READY
  │           │            │          │             │
  │       (Groq        (deterministic  (speaker-turn  (OpenRouter
  │        Whisper)     regex cleanup)  chunking)     embeddings + Qdrant)
  │                                                     │
  ▼                                                     ▼
S3 /meetai-recordings/                            Qdrant /meeting_chunks
tenants/{tid}/meetings/{mid}/{rid}/{filename}      (384-dim, Cosine)
```

### 1. Upload & Ingest

- Client calls `POST /api/v1/meetings` to create a meeting and get a presigned S3 upload URL.
- Client uploads the file directly to S3 via the presigned URL.
- Client calls `POST /api/v1/meetings/{id}/recordings/{id}/complete` to verify the upload.
- On completion, the API enqueues the pipeline starting at `TRANSCRIBE`.

**Key details:**
- Idempotency-Key header prevents duplicate meeting creation.
- S3 object keys follow `tenants/{tenant_id}/meetings/{meeting_id}/{recording_id}/{safe_filename}`.
- `source` and `external_meeting_id` fields are provider-agnostic for future meeting bot integration.

### 2. Transcribe

- Downloads the recording from S3 to a temp directory.
- Calls Groq `whisper-large-v3` with `verbose_json` response format and segment-level timestamps.
- Stores the full raw transcript in `transcripts_raw` and individual segments in `transcript_segments_raw`.
- Both tables are **immutable**: SQLAlchemy `before_update`/`before_delete` hooks AND MySQL triggers reject mutations.
- Idempotent: if a transcript already exists for `(meeting_id, stt_model)`, it returns the existing one.

### 3. Clean

The cleaning layer is **not summarization**. It deterministically normalizes transcript text to make it retrieval-friendly while preserving all meaning.

**Cleaning rules (all regex-based):**
- Remove noise markers: `[inaudible]`, `[crosstalk]`, `[noise]`, `[music]`, etc.
- Remove filler words: `um`, `uh`, `erm`, `hmm`, `you know`, `I mean`
- Collapse repeated fragments (e.g., "we should should deploy deploy" → "we should deploy")
- Normalize whitespace and punctuation
- Repair broken sentence boundaries (ensure trailing period)
- Preserve names, numbers, dates, technical terms

The cleaning version (`cleaning_version`) is configurable via `CLEANING_VERSION` env var.

### 4. Chunk

Conversation-aware chunking, not naive fixed splitting.

**Chunking strategy:**
- Chunk by speaker turns and topic continuity (natural boundaries at sentence endings when speaker changes).
- Target: 500–900 tokens per chunk (configurable via `CHUNK_TARGET_TOKENS` and `CHUNK_MAX_TOKENS`).
- 15% overlap between adjacent chunks (`CHUNK_OVERLAP_RATIO`) to prevent boundary information loss.
- Each chunk preserves: `start_ms`, `end_ms`, `speaker_set`, `source_segment_ids`, `source_text`.
- Chunks produce two rows: `transcript_chunks` (source text) and `transcript_chunks_clean` (cleaned + text_for_embedding with metadata context prepended).
- On reprocessing, existing chunks are marked `is_active = False`.

### 5. Embed & Index

- Constructs `text_for_embedding` by prepending metadata context: `"Meeting: {title} | Date: {date} | Speakers: {speakers}\n\n{cleaned_text}"`.
- Generates 384-dim embeddings via OpenRouter `sentence-transformers/all-minilm-l6-v2`.
- Upserts vectors into Qdrant `meeting_chunks` collection (Cosine distance) with rich payload metadata.
- Batch size: 32 embeddings per request.
- On reprocessing, deactivates old Qdrant points (`is_active = False`) before upserting new ones.
- Creates/updates `qdrant_documents` table rows for lineage tracking.

---

## API endpoints

All endpoints are prefixed with `/api/v1`.

### Authentication

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Create workspace + owner account (disabled in production via `ALLOW_PUBLIC_SIGNUP`) |
| POST | `/auth/login` | Sign in with email + workspace slug |
| POST | `/auth/refresh` | Rotate refresh token (cookie or body) |
| POST | `/auth/logout` | Revoke refresh token |
| GET | `/auth/me` | Current user profile |

### Meetings

| Method | Path | Description |
|---|---|---|
| POST | `/meetings` | Create meeting + get presigned upload URL |
| GET | `/meetings` | List meetings (paginated, filterable by status) |
| GET | `/meetings/{id}` | Meeting detail with recordings |
| GET | `/meetings/{id}/transcript` | Raw + cleaned chunks with segments |
| POST | `/meetings/{id}/recordings/{id}/complete` | Verify upload complete, enqueue pipeline |
| GET | `/meetings/{id}/jobs` | Pipeline job history for meeting |
| POST | `/meetings/{id}/reprocess` | Admin: reprocess from a given stage |

### Knowledge

| Method | Path | Description |
|---|---|---|
| POST | `/search` | Semantic search with metadata filters |
| POST | `/ask` | Grounded Q&A with citations |

### Admin

| Method | Path | Description |
|---|---|---|
| GET | `/admin/jobs` | Inspect pipeline jobs (filterable by status/stage) |
| POST | `/admin/jobs/{id}/retry` | Manually retry a failed job |

### Health & Metrics

| Method | Path | Description |
|---|---|---|
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe (checks MySQL, Redis, Qdrant, S3) |
| GET | `/metrics` | Prometheus metrics |

---

## Database model

14 tables form the system of record:

| Table | Purpose | Key columns |
|---|---|---|
| `tenants` | Multi-tenant organizations | `slug` (unique), `is_active` |
| `users` | User accounts | `tenant_id`, `email` (unique per tenant), `password_hash`, `role` (MEMBER/ADMIN/OWNER) |
| `refresh_tokens` | Opaque refresh token store | `token_hash` (SHA-256, unique), `expires_at`, `revoked_at` |
| `meetings` | Meeting records | `tenant_id`, `title`, `status` (PENDING→READY→FAILED), `source`, `duration_ms` |
| `recordings` | File references | `bucket` (63 chars), `object_key` (512 chars), `checksum_sha256`, `status` |
| `transcripts_raw` | **Immutable** raw transcript text | `meeting_id`, `stt_model`, `raw_text`, full provider response |
| `transcript_segments_raw` | **Immutable** per-segment data | `ordinal`, `start_ms`, `end_ms`, `speaker`, `text`, `confidence` |
| `transcript_chunks` | Generated chunks (versioned) | `chunk_strategy_version`, `is_active`, `speaker_set`, `source_segment_ids` |
| `transcript_chunks_clean` | Cleaned chunk text | `cleaning_version`, `cleaned_text`, `text_for_embedding`, `content_hash` |
| `qdrant_documents` | Vector lineage mapping | `qdrant_point_id`, `embedding_model`, `content_hash`, `is_active` |
| `processing_jobs` | Pipeline job tracking | `stage`, `status`, `idempotency_key`, `celery_task_id`, `retry_count`, `latency_ms` |
| `search_queries` | Audit trail for searches | `query_text`, `filters`, `result_chunk_ids`, `latency_ms` |
| `answer_generations` | Audit trail for answers | `question`, `answer`, `citations_json`, `input_tokens`, `output_tokens` |
| `audit_logs` | Immutable activity log | `action`, `resource_type`, `resource_id`, `ip_address`, `correlation_id` |

**Key constraints:**
- Raw transcript tables: `before_update` + `before_delete` ORM hooks AND MySQL triggers enforce immutability.
- Composite unique indexes stay under MySQL's 3072-byte utf8mb4 limit (e.g., `recordings(bucket, object_key)` at 63+512 chars).
- All tenant-scoped tables have `tenant_id` FK + indexes on common query patterns.

---

## Security model

### Authentication flow

1. **Registration/Login:** User provides credentials. Server returns a short-lived access token (15-min TTL) and sets an httpOnly refresh cookie (30-day TTL).
2. **Access token:** HS256 JWT with claims: `sub` (user_id), `tid` (tenant_id), `role`, `type`, `jti`, `iat`, `exp`, `iss`, `aud`.
3. **Refresh token:** Opaque, URL-safe, stored as SHA-256 digest. Rotated on every use (old token revoked, new token issued).
4. **Frontend auto-refresh:** The API client (`frontend/lib/api.ts`) automatically catches 401 responses, calls `/auth/refresh`, and retries the original request.

### Key rules

- **Never trust client-supplied tenant IDs.** API queries derive `tenant_id` from the verified JWT claims via the `get_current_user` dependency (`deps.py`).
- **Password hashing:** Uses `pwdlib` with Argon2 (recommended algorithm).
- **CSRF protection:** Refresh tokens are httpOnly+SameSite=Lax cookies; access tokens stored in `sessionStorage` (cleared on tab close).
- **Public signup:** Controlled by `ALLOW_PUBLIC_SIGNUP` env var (must be `false` in production).
- **Role-based access:** `require_roles()` dependency enforces ADMIN/OWNER access for reprocessing and admin endpoints.

---

## Tenant isolation

Every data row (meetings, transcripts, chunks, vectors, search queries, answers, audit logs) carries a `tenant_id` foreign key. The isolation strategy:

1. **API layer:** `get_current_user` dependency injects `AuthContext` with `tenant_id` from the verified JWT.
2. **Query layer:** All SQL queries filter by `tenant_id`. No endpoint accepts `tenant_id` from the request body.
3. **Vector layer:** Qdrant searches apply a `tenant_id` payload filter before similarity search. Retrieved points are re-validated against MySQL for the correct tenant before returning.
4. **Deletion:** Legal tenant erasure removes the complete tenant dataset rather than mutating individual rows. Immutable raw transcript rows are handled through a separate workflow.

---

## Local development

### Prerequisites

- Docker Desktop with Compose v2 (recommended) OR:
  - Python 3.11–3.12
  - Node.js 20+
  - MySQL 8.4
  - Redis 7+
  - (Optional) Local Qdrant instance

### Quick start with Docker

```bash
# Copy environment template
cp .env.example .env
# Edit .env to add your API keys

# Start full stack (API, worker, MySQL, Redis, LocalStack)
docker compose up --build

# To include local Qdrant instead of cloud:
docker compose --profile local-qdrant up --build

# Run migrations
docker compose run --rm api alembic upgrade head

# Open UI at http://localhost:3000
# API docs at http://localhost:8000/docs
```

### Manual setup

```bash
# Backend
cd backend
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Worker (separate terminal)
celery -A app.workers.celery_app:celery_app worker --loglevel=INFO --queues=pipeline,dead_letter

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

### Important: Local development without Docker services

- For **Qdrant**: The vector store stub at `backend/app/services/vector_store_stub.py` provides no-op implementations for all Qdrant operations. Import it if you don't have Qdrant running locally.
- For **S3**: LocalStack provides a free S3-compatible API. Ensure `AWS_ENDPOINT_URL=http://localhost:4566` is in your `.env`.
- For **transcription**: A valid `GROQ_API_KEY` is required. Without it, the transcription stage will fail with a clear error message.

---

## Configuration

All configuration is via environment variables loaded from `.env` (see `.env.example`).

### Core

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development` or `production` |
| `SECRET_KEY` | `development-only-change-me` | JWT signing key (min 16 chars; **must change in production**) |
| `ALLOW_PUBLIC_SIGNUP` | `true` | Allow new workspace registration |
| `LOG_LEVEL` | `INFO` | Logging level |

### Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `mysql+asyncmy://meetai:password@mysql:3306/meetai` | Async SQLAlchemy connection |
| `DATABASE_URL_SYNC` | `mysql+pymysql://meetai:password@mysql:3306/meetai` | Sync connection (Celery workers) |

### Redis / Celery

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | Connection for health checks |
| `CELERY_BROKER_URL` | `redis://redis:6379/1` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/2` | Celery result backend |

### AWS S3

| Variable | Default | Description |
|---|---|---|
| `AWS_S3_BUCKET` | `meetai-recordings` | S3 bucket name |
| `AWS_ENDPOINT_URL` | `http://localhost:4566` | Leave blank for production AWS |
| `AWS_PUBLIC_ENDPOINT_URL` | `http://localhost:4566` | Public-facing endpoint (browser uploads) |

### Groq

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | (blank) | Required for transcription |
| `GROQ_STT_MODEL` | `whisper-large-v3` | STT model |

### OpenRouter

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | (blank) | Required for embeddings + LLM |
| `OPENROUTER_EMBEDDING_MODEL` | `sentence-transformers/all-minilm-l6-v2` | 384-dim embedding model |
| `OPENROUTER_LLM_MODEL` | `openai/gpt-oss-120b:free` | Answer generation model |

### Qdrant

| Variable | Default | Description |
|---|---|---|
| `QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint |
| `QDRANT_API_KEY` | (blank) | Qdrant API key |
| `QDRANT_COLLECTION` | `meeting_chunks` | Collection name |
| `EMBEDDING_DIMENSION` | `384` | Must match the model output dimension |

### Pipeline settings

| Variable | Default | Description |
|---|---|---|
| `CLEANING_VERSION` | `clean-v1` | Version sentinel for cleaning |
| `CHUNKING_VERSION` | `speaker-semantic-v1` | Version sentinel for chunking |
| `CHUNK_TARGET_TOKENS` | `700` | Target tokens per chunk |
| `CHUNK_MAX_TOKENS` | `900` | Max tokens per chunk |
| `CHUNK_OVERLAP_RATIO` | `0.15` | Overlap ratio between chunks |
| `RETRIEVAL_TOP_K` | `8` | Default top-K for search |
| `RETRIEVAL_SCORE_THRESHOLD` | `0.3` | Minimum similarity score |

---

## Development commands

### Backend

```bash
cd backend

# Install with dev dependencies
python -m pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check app tests

# Type check
mypy app

# Run migrations
alembic upgrade head
alembic downgrade -1
alembic history

# Run API with hot reload
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Start Celery worker
celery -A app.workers.celery_app:celery_app worker \
  --loglevel=INFO --queues=pipeline,dead_letter
```

### Frontend

```bash
cd frontend

# Install
npm install

# Development
npm run dev

# Type check
npm run typecheck

# Lint
npm run lint

# Full check (typecheck + lint)
npm run check

# Production build
npm run build
```

### Docker / Make

```bash
# Copy .env template
make setup

# Start all services
make up

# View logs
make logs

# Run migrations
make migrate

# Run backend tests
make test

# Run lint
make lint

# Stop services
make down
```

---

## Testing

### Backend tests

Located in `backend/tests/`:

| Test file | What it tests |
|---|---|
| `test_cleaner.py` | Deterministic regex cleaning (noise removal, filler removal, repeated fragments) |
| `test_chunker.py` | Segment lineage preservation, time range, speaker set, overlap injection |
| `test_security.py` | Password hash roundtrip, JWT creation/decoding, tenant boundary in claims |
| `test_transcription.py` | Segment draft parsing from Groq payload, fallback for unsegmented transcripts |

```bash
cd backend
pytest                           # All tests (asyncio-mode=auto)
pytest -v                        # Verbose
pytest tests/test_cleaner.py     # Single file
pytest -k "chunker"              # Keyword match
```

### Frontend testing

```bash
cd frontend
npm run typecheck   # TypeScript compilation check
npm run lint        # ESLint
```

---

## Production deployment

See `docs/production.md` for full details.

### AWS topology

- **API + Workers**: Separate ECS Fargate services with independent autoscaling.
- **Networking**: ECS tasks, RDS MySQL, ElastiCache Redis, and Qdrant in **private subnets**. Only ALB is public.
- **Storage**: S3 Gateway endpoints + ECS task roles (no static AWS credentials).
- **Secrets**: AWS Secrets Manager for Groq, OpenRouter, JWT secret, database, Qdrant API key.
- **Encryption**: RDS encryption, S3 SSE-AES256, TLS at ALB.
- **Database**: Multi-AZ RDS, automated backups, point-in-time recovery, deletion protection.

### Key production settings

```env
APP_ENV=production
ALLOW_PUBLIC_SIGNUP=false
SECRET_KEY=<random-32+-chars>
# Remove AWS_ENDPOINT_URL and AWS_PUBLIC_ENDPOINT_URL for native S3
```

### Required alerts

- API error rate & p95 latency
- Celery queue depth & dead-lettered jobs
- Stage failure rate & processing latency
- Qdrant availability & disk usage
- Groq & OpenRouter rate limiting
- Retrievals with no evidence
- Answers rejected for missing citations

---

## Observability

### Structured logging

All logs are JSON via structlog with:
- `correlation_id` (propagated from HTTP headers through Celery tasks)
- `timestamp` (ISO 8601 UTC)
- `event` name
- Structured context (meeting_id, tenant_id, stage, latency_ms, retry_count)

### Prometheus metrics

- `meetai_http_requests_total` — counter by method, path, status
- `meetai_http_request_duration_seconds` — histogram by method, path

Exported at `GET /metrics`.

### Pipeline tracking

Every job has:
- `idempotency_key`: `{meeting_id}:{stage}:{version}:{run_id}`
- `correlation_id`: links across all stages
- `celery_task_id`: for Celery-level tracking
- `retry_count`, `latency_ms`, `failure_reason`

Audit logs record all search queries, answer generations, and admin actions.

---

## FAQ / Common pitfalls

### 1. Model version mismatches

Changing `cleaning_version`, `chunking_version`, or embedding model requires versioned task idempotency keys. The `STAGE_VERSION` dict in `tasks.py` maps each stage to its version function. Upgrade prompts and version sentinels in lockstep.

### 2. Vector reindexing

Reprocessing deactivates old Qdrant points (`is_active = false`) rather than deleting them. A full reindex requires a reprocessing run with a new version sentinel. Raw content is never mutated.

### 3. Tenant boundaries

Always pass `tenant_id` from auth claims. The `deps.py` `get_current_user` dependency enforces this. Never accept `tenant_id` from request body.

### 4. Async/sync session mixing

Storage operations (boto3) are sync. The Celery workers use sync SQLAlchemy sessions (`SyncSessionLocal` from `sync_session.py`). The FastAPI endpoints use async sessions (`AsyncSessionLocal` from `session.py`).

### 5. MySQL utf8mb4 index limits

Composite unique indexes on varchar columns can exceed MySQL's 3072-byte utf8mb4 index limit. Recording object keys are truncated to <512 chars. Bucket names are limited to 63 chars (S3 constraint).

### 6. Encoding

All affected columns use `utf8mb4` collation. The unique index on `recordings(bucket, object_key)` stays within limits due to the 63+512 char caps.

### 7. JWT token refresh flow

Access tokens expire in 15 minutes. The frontend API client (`api.ts`) automatically catches 401 responses, calls `/auth/refresh`, and retries. The refresh cookie is httpOnly, Secure (in production), SameSite=Lax, and scoped to `/api/v1/auth`.

### 8. Celery dead letters

Dead-lettered jobs (exceeded `max_retries`) require manual investigation or the `/admin/jobs/{id}/retry` endpoint. Exponential backoff: 30s × 2^retries (capped at 900s).

### 9. Embedding dimension validation

The embedding model outputs 384-dim vectors. The service validates every vector's dimension. Both Qdrant collection config and `EMBEDDING_DIMENSION` must match. Batch size is 32 in `_run_embed_index`.

### 10. Extension compatibility

The ingestion pipeline supports provider-agnostic recording metadata (`source`, `external_meeting_id`). Future meeting bots should call the same `/api/v1/meetings/{id}/ingest` endpoint using a service identity. Bot coordination and permission handling should live in separate packages.

---

## License

Internal project. Not open-sourced.

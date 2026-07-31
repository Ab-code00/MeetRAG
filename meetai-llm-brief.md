# MeetAI — Crisp Full-Context Brief for Another LLM

## What MeetAI is
MeetAI is a production-ready AI meeting intelligence platform that turns meeting recordings into searchable, traceable knowledge. It ingests audio/video recordings, transcribes them, stores the raw transcript as the source of truth, cleans and chunks the transcript, generates embeddings, indexes them in Qdrant, and answers user questions with grounded citations.

## Locked stack
- STT: `openai/whisper-large-v3`
- LLM: `openai/gpt-oss-120b:free`
- Embeddings: `sentence-transformers/all-minilm-l6-v2`
- Embedding dimension: `384`
- LLM/embedding access: OpenRouter
- RDBMS: MySQL
- Vector DB: Qdrant
- Backend: FastAPI (Python)
- Frontend: Next.js
- Workers/queue: Python workers + Redis/Celery or Dramatiq
- Storage: AWS S3
- Deployment: Docker locally, AWS EC2/ECS in production

## Core product goal
Turn recorded meetings into:
- searchable transcript knowledge,
- metadata-filtered semantic retrieval,
- grounded Q&A with source evidence,
- production-safe reprocessing and observability.

## Non-negotiable architecture rules
1. Raw transcript is immutable and always stored in MySQL.
2. Never embed the full raw transcript directly.
3. Only embed cleaned, chunked, metadata-enriched text.
4. Every derived artifact is versioned: cleaning version, chunking version, embedding model, prompt version.
5. Every stage must be async, idempotent, retryable, and observable.
6. Every answer must cite source chunks and timestamps.
7. Every retrieval must be tenant-scoped before similarity search.
8. Every Qdrant point must map back to a MySQL chunk row.

## Main pipeline
1. User uploads or imports a recording.
2. File is stored in S3.
3. STT worker transcribes audio using `openai/whisper-large-v3`.
4. Raw transcript and raw transcript segments are saved in MySQL.
5. Cleaner worker removes filler/noise and normalizes transcript text without summarizing it.
6. Chunker groups cleaned text into speaker-turn-aware semantic chunks.
7. Embed worker generates 384-dim embeddings using `sentence-transformers/all-minilm-l6-v2`.
8. Embeddings are upserted into Qdrant with rich payload metadata.
9. Search API retrieves relevant chunks using metadata filters + vector search.
10. Answer API uses retrieved evidence only and generates grounded answers with citations using `openai/gpt-oss-120b:free`.

## Why raw transcript is stored separately
Raw transcript is the immutable source of truth. It allows:
- safe reprocessing when cleaning/chunking logic changes,
- debugging STT quality,
- auditability,
- regenerating embeddings without retranscribing audio,
- preventing loss of information due to aggressive cleanup.

## Cleaning strategy
The cleaning layer is not summarization. Its purpose is to make transcript text retrieval-friendly while preserving meaning.

Cleaning rules:
- remove filler words,
- collapse repeated fragments,
- remove noise markers like `[inaudible]`, `[crosstalk]`,
- normalize whitespace and punctuation,
- repair broken sentence boundaries,
- preserve names, numbers, decisions, dates, technical terms.

Optional: use the LLM on small chunks only to rewrite into cleaner prose, but never summarize or invent content.

## Chunking strategy
Chunking must be conversation-aware, not naive fixed splitting.

Chunking rules:
- chunk by speaker turns and topic continuity,
- target roughly 500–900 tokens per chunk,
- add 10–20% overlap between chunks,
- preserve `start_ms`, `end_ms`, `speaker_set`, `source_segment_ids`,
- version the chunking strategy.

Goal: each chunk should be semantically coherent and independently retrievable.

## Embedding strategy
- Use `sentence-transformers/all-minilm-l6-v2` through OpenRouter.
- Validate that every embedding vector has dimension `384`.
- Build `text_for_embedding` by prepending short metadata context before the cleaned text.
- Never embed the raw whole meeting.
- Store the vector in Qdrant and the lineage row in MySQL.

## Qdrant design
Collection name: `meeting_chunks`

Vector config:
- size: `384`
- distance: `Cosine`

Important payload fields:
- `tenant_id`
- `meeting_id`
- `chunk_id`
- `clean_chunk_id`
- `meeting_title`
- `meeting_date`
- `start_ms`
- `end_ms`
- `speaker_set`
- `project`
- `department`
- `chunk_strategy_version`
- `cleaning_version`
- `embedding_model`
- `is_active`

Use payload indexes for frequent filters like tenant, meeting, date, speaker, and activity status.

## Retrieval design
Retrieval is metadata-first, then semantic similarity.

Flow:
1. Parse user query.
2. Extract filters if possible: tenant, meeting, speaker, date, project.
3. Apply Qdrant payload filters first.
4. Generate query embedding.
5. Search Qdrant for top-k chunks.
6. Assemble only the retrieved evidence into LLM context.
7. Generate answer only from that evidence.

Rules:
- no tenant filter bypass,
- no answer without evidence,
- no hallucinated answer if retrieval is weak,
- return chunk IDs and timestamps with answers.

## Grounded answering design
The LLM is not the knowledge store. Qdrant + MySQL are the knowledge store.

The answering model should:
- answer only from retrieved chunks,
- refuse or express uncertainty when evidence is insufficient,
- cite chunk IDs, meeting IDs, and timestamps,
- never fabricate details not present in the transcript.

## MySQL data model
Core tables:
- `meetings`
- `recordings`
- `transcripts_raw`
- `transcript_segments_raw`
- `transcript_chunks`
- `transcript_chunks_clean`
- `qdrant_documents`
- `processing_jobs`
- `search_queries`
- `answer_generations`

Purpose:
- MySQL is the system of record for meetings, jobs, transcript lineage, and auditability.
- Qdrant is only for vector retrieval, not primary truth.

## Job orchestration rules
All processing stages must be queue-based and replayable.

Suggested stage flow:
- `PENDING`
- `TRANSCRIBING`
- `TRANSCRIBED`
- `CLEANING`
- `CLEANED`
- `CHUNKING`
- `CHUNKED`
- `EMBEDDING`
- `INDEXING`
- `READY`
- `FAILED`

Requirements:
- idempotency key per stage,
- retries with backoff,
- partial failure handling,
- manual retry endpoint,
- dead-letter support,
- correlation IDs and structured logs.

## API responsibilities
Main APIs:
- upload/import recording,
- meeting detail and status,
- transcript view,
- reprocess meeting,
- semantic search,
- ask grounded question,
- admin job inspection/retry.

## Frontend responsibilities
Main UI surfaces:
- upload flow,
- meeting list,
- meeting detail,
- transcript viewer,
- search UI,
- ask UI,
- job status monitor,
- admin reprocess screen.

Important UX requirements:
- show raw vs cleaned transcript,
- show source chunk evidence,
- jump to timestamp,
- show processing state,
- expose failure reasons.

## Security and compliance requirements
- tenant isolation is mandatory,
- auth via JWT/OAuth,
- role-based access control,
- encryption in transit and at rest,
- audit logs for transcript/search/answer access,
- private network access for MySQL and Qdrant,
- data retention and deletion workflows.

## Observability requirements
Track:
- upload success rate,
- transcription latency,
- cleaning latency,
- chunking latency,
- embedding latency,
- indexing latency,
- query latency,
- answer latency,
- failures by stage,
- token usage,
- cost per meeting.

Every request and job should have:
- correlation ID,
- structured logs,
- model name,
- latency,
- retry count,
- failure reason if any.

## Claude Code agent team
Keep the agent set small and high-value.

1. Research Agent
- researches docs, blogs, Reddit, GitHub, and external implementation patterns.

2. Inspector / Orchestrator Agent
- reviews all work, checks alignment with architecture, approves/rejects outputs, prevents drift.

3. Coding Agent A
- backend, MySQL schema, ingestion, STT, cleaning, chunking, worker orchestration.

4. Coding Agent B
- embeddings, Qdrant, retrieval APIs, grounded answer APIs, frontend integration.

5. Test Agent
- real-world testing, regression, failure injection, tenant isolation checks, reprocessing validation.

## Build order
1. Set up MySQL schema and migrations.
2. Build upload flow + S3 storage.
3. Build STT worker + raw transcript persistence.
4. Build deterministic cleaner.
5. Build chunker.
6. Build embeddings integration.
7. Build Qdrant indexing.
8. Build retrieval API.
9. Build grounded answer API.
10. Build frontend views.
11. Add retries, reprocessing, observability, auth, and admin tools.
12. Add evaluation harness and production hardening.

## Milestones
### Milestone 1
Upload, transcription, raw transcript storage.

### Milestone 2
Cleaning, chunking, clean transcript inspection.

### Milestone 3
Embeddings, Qdrant indexing, semantic search.

### Milestone 4
Grounded Q&A with citations.

### Milestone 5
Production hardening: retries, observability, security, testing, deployment.

## Acceptance criteria
- Raw transcript is stored and immutable.
- Cleaned chunks are reproducible and versioned.
- Embeddings are regenerated without retranscription.
- Qdrant retrieval is metadata-filtered and tenant-safe.
- Search returns chunk-level evidence.
- Answers are grounded and cited.
- Failed jobs are replayable.
- Reprocessing deactivates stale vectors.
- Logs, metrics, and costs are observable.

## Final instruction to another LLM
When working on MeetAI, do not redesign the architecture unless explicitly asked. Assume the stack and system rules are fixed. Optimize for correctness, traceability, and production reliability. Do not suggest embedding raw full transcripts. Do not use the LLM as the source of truth. Treat MySQL as the system of record and Qdrant as the retrieval engine. Keep all outputs aligned with the locked models, data flow, and constraints described above.

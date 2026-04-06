# AI Shorts Engine Backend

FastAPI control plane and worker runtime for `M0-M2` of the AI Shorts Engine v1.

## Run

```bash
cp .env.example .env
make dev-up
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Run the worker in a separate shell:

```bash
uv run python worker.py
```

## Current Scope

- App skeleton and settings
- Async SQLAlchemy setup
- Alembic migrations through `M2` candidate ranking
- `health`, `uploads`, `brand-profiles`, `source-videos`, and `jobs` endpoints
- `platform-accounts` endpoints
- Read APIs for `transcript-segments`, `transcript-words`, and `candidate-clips`
- Filesystem/MinIO-backed storage abstraction
- Local direct-upload route for the filesystem backend: `PUT /api/v1/uploads/{id}/content`
- DB-polled worker runtime for `intake -> ingest -> transcript -> feature_extract -> ranking`
- Dev auth stub with role headers
- SQLite-backed API/worker regression tests for `upload -> source_video -> job -> intake/ingest/transcript/feature_extract/ranking`
- Filesystem-backed upload flow for local development via `PUT /api/v1/uploads/{upload_id}/content`
- Pluggable storage backend contract with `filesystem` default and `minio` option
- First-class idempotency for current write paths: `jobs`, `resolve-intake-review`, and `upload complete`
- Retryable outbox failures with backoff plus terminal failure propagation into `stage_run` / `job`
- Real `ffmpeg`-based ingest for normalized audio and proxy generation
- Transcript provider abstraction with `Groq -> OpenAI -> Stub` fallback order
- Deterministic feature extraction and ranked `candidate_set/candidate_clip` persistence
- Opt-in Postgres migration smoke test for the `upload -> ranking` worker flow

## Dev Auth

By default, local development uses header-based auth.

- `X-Actor-Id`
- `X-Actor-Role`

If omitted, the app falls back to the configured default dev actor.

## Local Services

- Postgres: `localhost:5432`
- MinIO API: `localhost:9000`
- MinIO console: `localhost:9001`

## Notes

- The filesystem storage backend is intended for local development and tests.
- Production-style direct object upload still belongs behind presigned object-storage URLs.
- The Postgres smoke test requires `ffmpeg` in the test environment because it generates a sample source video.

## Storage Backends

Local development defaults to `STORAGE_BACKEND=filesystem`, which makes upload sessions return an app-local upload URL:

1. `POST /api/v1/uploads`
2. `PUT /api/v1/uploads/{upload_id}/content`
3. `POST /api/v1/uploads/{upload_id}/complete`

If you switch to `STORAGE_BACKEND=minio`, the upload session returns a presigned object-storage URL instead.

## ASR Providers

Transcription uses the normalized provider chain configured via environment:

- `ASR_PROVIDER_PRIMARY`
- `ASR_PROVIDER_FALLBACK`
- `GROQ_API_KEY`
- `OPENAI_API_KEY`

For offline development and tests, set `ASR_PROVIDER_PRIMARY=stub`.

## Postgres Migration Smoke

Use an explicitly disposable Postgres database and pass it through `POSTGRES_TEST_DATABASE_URL`.
The test fixture resets the `public` schema before running Alembic migrations, so do not point it at any non-test database.
Use a database name that clearly includes a disposable token such as `_test`, `_smoke`, `_tmp`, or `_sandbox`.

```bash
POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_shorts_engine_test uv run pytest tests/test_postgres_migration_smoke.py -m postgres -q
```

Or via `make`:

```bash
POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_shorts_engine_test make test-postgres-smoke
```

Behavior notes:

- if `POSTGRES_TEST_DATABASE_URL` is absent, the Postgres smoke test is skipped explicitly;
- the test never falls back to SQLite;
- Docker or `docker compose` can be used to provide Postgres externally, but pytest does not invoke Docker itself.

## Audit

The current implementation gap log and closure plan live in [gap-audit.md](gap-audit.md).

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

`.env.example` defaults to `ASR_PROVIDER_PRIMARY=stub`, so the local pipeline is runnable without Groq/OpenAI secrets.
To switch to a cloud ASR provider, set `ASR_PROVIDER_PRIMARY` and the matching API key in `.env`.
For a concise macOS-specific setup, see [macos-runbook.md](macos-runbook.md).

Run the worker in a separate shell:

```bash
uv run python worker.py
```

## Current Scope

- App skeleton and settings
- Async SQLAlchemy setup
- Alembic migrations through the pre-`M3` eval harness gate
- `health`, `uploads`, `brand-profiles`, `source-videos`, and `jobs` endpoints
- `platform-accounts` endpoints
- Read APIs for `transcript-segments`, `transcript-words`, and `candidate-clips`
- `GET /source-videos/{id}` detail response with role-keyed artifacts and provenance
- `GET /jobs/{id}` detail response with current config snapshot, stage summary, output counts, and current approval-state projection
- Filesystem/MinIO-backed storage abstraction
- Local direct-upload route for the filesystem backend: `PUT /api/v1/uploads/{id}/content`
- DB-polled worker runtime for `intake -> ingest -> transcript -> feature_extract -> ranking`
- Dev auth stub with role headers
- SQLite-backed API/worker regression tests for `upload -> source_video -> job -> intake/ingest/transcript/feature_extract/ranking`
- Filesystem-backed upload flow for local development via `PUT /api/v1/uploads/{upload_id}/content`
- Pluggable storage backend contract with `filesystem` default and `minio` option
- First-class idempotency for current write paths: `jobs`, `resolve-intake-review`, and `upload complete`
- Retryable outbox failures with backoff plus terminal failure propagation into `stage_run` / `job`
- Lease-heartbeat ownership checks for `stage_run` + `outbox_event` renewal
- Real `ffmpeg`-based ingest for normalized audio and proxy generation
- Transcript provider abstraction with `Groq -> OpenAI -> Stub` fallback order
- Deterministic feature extraction and ranked `candidate_set/candidate_clip` persistence
- Internal offline eval harness with persisted benchmark comparison artifacts
- Internal offline reference-intelligence lane for canonical shorts, with manifest-driven analysis, local-first frame sampling, OCR evidence, and preset bundle generation
- Opt-in Postgres migration smoke test for the `upload -> ranking` worker flow

## Auth Modes

By default, local development uses `AUTH_MODE=development_header`.

- `X-Actor-Id`
- `X-Actor-Role`

If omitted, the app falls back to the configured default dev actor.

The backend now also supports a bridge `AUTH_MODE=session_cookie` mode for non-dev verification.
It validates a pre-issued, signed session cookie and maps the cookie claims into the existing route-level RBAC guards.
This is intentionally narrower than the full `OIDC + httpOnly Secure session cookie` contract:

- the backend verifies a signed session envelope;
- full login, redirect, session issuance, rotation, and revocation remain outside this slice;
- worker JWT verification is available as a separate internal dependency for future internal-only HTTP surfaces.

Required session-cookie settings:

- `AUTH_SESSION_COOKIE_NAME`
- `AUTH_SESSION_SECRET`
- `AUTH_SESSION_ISSUER`

When `AUTH_MODE=session_cookie`:

- missing, malformed, expired, or bad-signature cookies return `401 unauthorized`;
- authenticated actors with insufficient role still return `403 forbidden`.

## Local Services

- Postgres: `localhost:5432`
- Disposable smoke DB in the same container: `ai_shorts_engine_test`
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

The checked-in local example already defaults to `ASR_PROVIDER_PRIMARY=stub`.
To use cloud ASR instead, set `ASR_PROVIDER_PRIMARY=groq` or `openai` and provide the matching API key.

## Postgres Migration Smoke

Use an explicitly disposable Postgres database and pass it through `POSTGRES_TEST_DATABASE_URL`.
The test fixture resets the `public` schema before running Alembic migrations, so do not point it at any non-test database.
Use a database name that clearly includes a disposable token such as `_test`, `_smoke`, `_tmp`, or `_sandbox`.
The local `docker compose` stack now bootstraps `ai_shorts_engine_test` inside the existing Postgres container so the smoke path can run without provisioning a second service.

```bash
POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_shorts_engine_test uv run pytest tests/test_postgres_migration_smoke.py -m postgres -q
```

Or via `make`:

```bash
make test-postgres-smoke
```

Or run the full pre-`M3` database-backed gate against the local disposable database:

```bash
make test-pre-m3-gates
```

Behavior notes:

- if `POSTGRES_TEST_DATABASE_URL` is absent, the Postgres smoke test is skipped explicitly;
- the test never falls back to SQLite;
- the local smoke fixture now waits briefly for disposable Postgres readiness and disables SSL automatically for localhost disposable URLs;
- Docker or `docker compose` can be used to provide Postgres externally, but pytest does not invoke Docker itself.
- if your `postgres_data` volume already existed before the disposable test DB bootstrap script was added, run `make dev-down` and then `make dev-up` once so `ai_shorts_engine_test` is created.

## Eval Harness

The offline benchmark runner is internal-only in v1 and persists a comparison artifact through `artifact_object`.

```bash
EVAL_SET_ID=<uuid> PROMPT_VERSION=v1 SCORING_POLICY_VERSION=v1 make eval-benchmark
```

The eval gate is satisfied only when:

- the eval set is frozen;
- a `benchmark_run` exists for the active `prompt_version` and `scoring_policy_version`;
- that run has persisted `benchmark_result` rows and a comparison artifact.

## Stage A Proof Harness

Stage A is now implemented as a separate `proof-harness` API surface.
It is deliberately narrower than the future `M3/M4` review and render APIs: its only job is to run a blinded shortlist-quality comparison loop across `engine`, `manual`, and `vizard`.

Workflow:

1. Create a frozen eval set and add source videos with holdout metadata such as `channel_series` and `content_pattern`.
2. Snapshot the current engine top-8 shortlist from a job.
3. Import fixed top-8 baseline shortlists for `manual` and `vizard`.
4. Create a blinded review session, record reviewer decisions for all three batches, then emit a persisted proof comparison artifact.

Pilot operation rules are frozen in [pilot-review-protocol.md](pilot-review-protocol.md).
Holdout is the only stop/go basis; dev runs are operational feedback only.

Implemented endpoints:

- `POST /api/v1/proof-harness/eval-sets`
- `POST /api/v1/proof-harness/eval-sets/{eval_set_id}/members`
- `POST /api/v1/proof-harness/jobs/{job_id}/engine-shortlist`
- `POST /api/v1/proof-harness/source-videos/{source_video_id}/baseline-shortlists`
- `POST /api/v1/proof-harness/review-sessions`
- `POST /api/v1/proof-harness/review-sessions/{proof_review_session_id}/complete`
- `POST /api/v1/proof-harness/comparison-runs`

Artifacts written through the same `artifact_object` plane:

- neutral per-candidate preview excerpt payloads
- per-shortlist manifests
- per-run proof comparison payloads

## Reference Intelligence Lane

Canonical reference shorts now have a separate offline lane under `../experiments/autoresearch`.
It is intentionally outside the production API/worker runtime and is meant to generate manual presets, not mutate production defaults.
The lane is local-first and frames-first: use deterministic metadata/scene/OCR extraction first, then optionally classify sampled frame packs with an external multimodal provider.
Do not analyze every frame or run a whole-video multimodal pass.

Reference collection contract:

- `references/<collection>/manifest.json|csv`
- `references/<collection>/videos/...`
- optional manifest-declared sidecars for subtitles or transcripts

Outputs:

- `reference_manifest.lock.json`
- `reference_sampling_map.json`
- `reference_ocr_report.json`
- `reference_style_report.json`
- `reference_clusters.json`
- `preset_bundle.json`
- `comparison_report.json` when both benchmark payloads already exist

Run from `backend/`:

```bash
REFERENCE_COLLECTION_DIR=../references/my-pack OUTPUT_DIR=../references/my-pack/outputs PRESET_NAME=my-pack-v1 PROMPT_VERSION=v1 SCORING_POLICY_VERSION=v1 make reference-intelligence
```

Optional OCR/VLM switches are passed through the same target:

```bash
REFERENCE_COLLECTION_DIR=../references/my-pack OUTPUT_DIR=../references/my-pack/outputs PRESET_NAME=my-pack-v1 PROMPT_VERSION=v1 SCORING_POLICY_VERSION=v1 OCR_PROVIDER=auto VLM_PROVIDER=openai VLM_MODEL=<vision-model> OPENAI_API_KEY=<key> make reference-intelligence
```

To emit a comparison report when both benchmark payloads already exist:

```bash
REFERENCE_COLLECTION_DIR=../references/my-pack OUTPUT_DIR=../references/my-pack/outputs PRESET_NAME=my-pack-v1 PROMPT_VERSION=v1 SCORING_POLICY_VERSION=preset-my-pack-v1 BASELINE_BENCHMARK_PATH=../tmp/baseline.json CANDIDATE_BENCHMARK_PATH=../tmp/candidate.json make reference-intelligence-benchmark
```

Safety rules:

- reference videos are analysis-only and never reused as footage
- new presets do not change production behavior automatically; any preset that affects ranking-adjacent policy or render/edit hints must be compared against a frozen eval set and backed by a persisted comparison artifact before explicit human enablement
- external multimodal output is advisory only and does not become a source of truth for runtime ranking or evaluation

See `../experiments/autoresearch/README.md` for the collection layout and manifest contract.

## Audit

The current implementation gap log and closure plan live in [gap-audit.md](gap-audit.md).

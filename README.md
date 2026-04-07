# AI Shorts Engine v1

AI Shorts Engine v1 is an internal production engine for turning one owned long-form spoken video into a small batch of publish-ready short clips.

The current implementation is not a generic content-generation app and not a trend-hunting recommendation engine. Its core job is:

- ingest one owned source video
- normalize and transcribe it
- extract deterministic media and transcript features
- generate and rank candidate short clips
- gate any ranking changes through offline benchmarks
- prepare, but not yet ship, packaging intelligence for better short-form opening hooks and preset selection

## What The Project Is

At a system level the repo contains two lanes:

1. Production system-of-record in `backend/`
2. Offline experimentation lane in `experiments/autoresearch/`

The production lane owns the real job pipeline:

- `upload -> ingest -> transcript -> feature_extract -> ranking`
- persisted jobs, stage runs, artifacts, outbox events, candidate clips, transcript revisions, eval sets, and benchmark runs
- approval-gated operating model

The experimentation lane is intentionally outside the production worker graph. It analyzes canonical reference shorts as analysis-only inputs and synthesizes preset recommendations and benchmark-ready comparison artifacts. It does not mutate production defaults automatically.

## Current Stage

The project is effectively at the end of `M2 / pre-M3`.

Implemented and verified:

- `M0 Foundation`
  - FastAPI app bootstrap
  - SQLAlchemy models and Alembic migrations
  - auth/RBAC for dev and session-cookie bridge mode
  - DB-backed state machine and durable outbox primitives
- `M1 Intake + Transcription`
  - upload flow
  - source video intake
  - job creation
  - ingest worker with real `ffmpeg` normalization
  - transcript provider abstraction with fallback chain
- `M2 Candidate Engine`
  - feature extraction worker
  - candidate generation and ranking
  - candidate/transcript read APIs
  - offline eval harness with persisted benchmark artifacts
- Offline reference intelligence lane
  - manifest locking
  - deterministic frame sampling
  - optional OCR
  - optional sampled-frame VLM classification
  - cluster and preset synthesis
  - benchmark-gated comparison semantics

Not started as a production lane:

- `M3 Preview + Render`
- `M4 QA + Approval + Delivery`
- `M5 Feedback + Ops`

Important nuance:

- the repo already contains planning and gating for pre-`M3`
- the render lane itself is not the current source of truth yet
- reference analysis is meant to improve packaging intelligence before render/preset activation, not to bypass milestone order

## What Changed In The Latest Slice

The latest bounded implementation hardened the offline reference analysis contract around the first `0-4s` of a short.

New behavior:

- `reference_style_report.json` now includes `opening_packaging`
- opening packaging is backed by opening-only evidence, not whole-video rollups
- unresolved visual semantics now stay `null` instead of pretending certainty
- explicit evidence records exist per opening label with:
  - `value`
  - `status`
  - `source`
  - `confidence`
  - `evidence_refs`
- degraded probe/provider paths now emit warnings instead of failing silently
- benchmark comparison now rejects candidate payloads whose `prompt_version` or `scoring_policy_version` do not match the preset bundle recommendation

This keeps the lane offline-first and safer to evaluate before any `M3` work starts.

## Current Verified Snapshot

At the moment the repository is in a strong engineering-prep state, not a pilot-complete state.

Verified locally on this branch:

- focused `reference_intelligence + eval_harness` pytest path is green
- the offline reference CLI parses and boots correctly
- comparison semantics enforce preset-to-candidate version compatibility
- opening-window packaging artifacts are emitted with evidence and warning records

Still true right now:

- there is no real canonical reference collection checked into `references/`
- the project is therefore still in `Mode A` for reference intelligence
- the offline lane is implementation-ready, but not yet validated on real reference shorts

## High-Level Architecture

### Production lane

- `FastAPI` modular monolith as control plane
- async SQLAlchemy persistence
- Alembic migrations
- DB-polled worker runtime
- filesystem or MinIO-compatible storage
- benchmark/eval artifacts persisted in the same control plane

Main production flow:

1. Register upload
2. Complete immutable source artifact
3. Create `SourceVideo`
4. Create `Job`
5. Run `intake`
6. Run `ingest`
7. Run `transcript`
8. Run `feature_extract`
9. Run `ranking`
10. Expose ranked candidates and transcripts for review

### Offline reference lane

The reference lane exists to learn packaging priors from canonical shorts without contaminating production runtime decisions.

Current flow:

1. Load `references/<collection>/manifest.json|csv`
2. Lock manifest and sidecar hashes
3. Extract deterministic probe data with `ffprobe` and `ffmpeg`
4. Build opening/body/high-change/end frame packs
5. Optionally run OCR on sampled frames
6. Optionally run a sampled-frame OpenAI vision pass
7. Aggregate evidence into reference reports, clusters, and preset bundles
8. Optionally compare ranking-adjacent bundles against frozen benchmark artifacts

Hard rules:

- reference shorts are analysis-only
- they cannot be reused as production footage or B-roll
- OpenAI VLM is opt-in and advisory only
- whole-video VLM analysis is out of scope
- production ranking/eval does not take external provider output as source of truth

## Repo Structure

```text
backend/
  app/
    api, models, services, core
  alembic/
  tests/
  worker.py
  Makefile

experiments/
  autoresearch/
    reference_intelligence.py
    sampling.py
    ocr.py
    synthesis.py
    taxonomy.py
    vlm_openai.py

references/
  README.md
  <collection>/

research-dossier.md
specification.md
db-schema.md
api-contract.md
worker-contracts.md
implementation-backlog.md
```

## What Already Works

### Backend/runtime

- health endpoint and app bootstrap
- upload session flow
- source video registration
- job creation with idempotency
- stage orchestration with durable outbox
- `ffmpeg` ingest normalization
- transcription revision persistence
- deterministic feature extraction
- ranked candidate clip persistence
- transcript and candidate read APIs
- offline benchmark runner and pre-`M3` gate checks

### Reference analysis

- manifest validation for JSON and CSV
- file and sidecar integrity locking
- duration and technical probe extraction
- cut-density proxy and scene-boundary sampling
- silence and black-range probing
- opening/body/high-change/end frame sampling
- OCR summary over sampled frames
- opening-window packaging contract with evidence records
- cluster and preset bundle synthesis
- benchmark-gated comparison artifact generation

## What Is Still Unproven

This is the most important realism section in the repo.

The project has real pre-`M3` foundations, but several things are still not proven on real canonical references or real render outputs.

Still unproven:

- OCR quality on stylized burned subtitles
- sampled-frame VLM quality on real reference packs
- crop/reframe behavior quality
- clip-level motion reasoning
- effect taxonomy quality on real references
- render quality and retention impact because `M3` has not started
- packaging conclusions on a real canonical reference dataset because no real collection is in the repo yet

Current reference lane status is therefore:

- implementation-ready
- contract-hardened
- safe to run in a controlled manner
- not yet empirically validated on a real canonical pack

## Milestone Status

| Milestone | Status | Notes |
| --- | --- | --- |
| `M0 Foundation` | Done | Control plane, schema, auth, orchestration primitives are in place |
| `M1 Intake + Transcription` | Done | Owned source intake and transcript persistence are implemented |
| `M2 Candidate Engine` | Done | Feature extraction, ranking, eval harness, and read APIs are working |
| `Pre-M3 Gate` | Working | Benchmark gate exists and Stage A proof harness now supports frozen eval sets, blinded `engine/manual/vizard` shortlist review, and persisted stop/go comparison artifacts; render should still wait for active benchmark evidence and disposable Postgres smoke |
| `M3 Preview + Render` | Not started as production lane | Preferred direction remains `Vizard-first + FFmpeg fallback` |
| `M4 QA + Approval + Delivery` | Not started | Approval and QA model are specified, not yet implemented end-to-end |
| `M5 Feedback + Ops` | Not started | Analytics and operations surfaces remain future work |

## Prerequisites

- Python `>=3.11,<3.13`
- `uv`
- `ffmpeg`
- `ffprobe`
- Docker Desktop or compatible Docker runtime for local Postgres/MinIO stack

Optional:

- `tesseract` for OCR fallback
- `paddleocr` environment for better OCR
- OpenAI API key only for opt-in sampled-frame VLM analysis

## Local Setup

From `backend/`:

```bash
cp .env.example .env
make dev-up
uv sync
uv run alembic upgrade head
```

`backend/.env.example` now defaults to the `stub` ASR provider so the local pipeline can boot without cloud credentials.
To use Groq or OpenAI transcription, set `ASR_PROVIDER_PRIMARY` and the matching API key in `.env`.
For a narrow machine-specific setup on macOS, see [backend/macos-runbook.md](backend/macos-runbook.md).

Run the API:

```bash
make api
```

Run the worker in a separate shell:

```bash
make worker
```

Default local auth mode is header-based development auth.

Useful headers:

- `X-Actor-Id`
- `X-Actor-Role`

## Local Services

Default local endpoints:

- Postgres: `localhost:5432`
- disposable smoke DB: `ai_shorts_engine_test`
- MinIO API: `localhost:9000`
- MinIO console: `localhost:9001`

## Common Commands

From `backend/`:

```bash
make migrate
make test
make test-postgres-smoke
make test-pre-m3-gates
```

Run offline benchmark:

```bash
EVAL_SET_ID=<uuid> PROMPT_VERSION=v1 SCORING_POLICY_VERSION=v1 make eval-benchmark
```

## Reference Intelligence Usage

Reference collection contract:

```text
references/<collection>/
  manifest.json or manifest.csv
  videos/
    ...
  optional sidecars declared in manifest
```

Required manifest fields:

- `reference_id`
- `file_name`
- `channel_or_source`
- `theme`
- `language`

Optional manifest fields:

- `platform`
- `notes`
- `style_family`
- `why_reference`
- `subtitle_file`
- `transcript_file`
- `hook_text`
- `cta_text`

Run the offline analysis from `backend/`:

```bash
REFERENCE_COLLECTION_DIR=../references/my-pack OUTPUT_DIR=../references/my-pack/outputs PRESET_NAME=my-pack-v1 PROMPT_VERSION=v1 SCORING_POLICY_VERSION=v1 make reference-intelligence
```

Enable OCR/VLM only when you actually need them:

```bash
REFERENCE_COLLECTION_DIR=../references/my-pack OUTPUT_DIR=../references/my-pack/outputs PRESET_NAME=my-pack-v1 PROMPT_VERSION=v1 SCORING_POLICY_VERSION=v1 OCR_PROVIDER=auto VLM_PROVIDER=openai VLM_MODEL=<vision-model> OPENAI_API_KEY=<key> make reference-intelligence
```

Generate a benchmark-gated comparison report only when both benchmark payloads already exist:

```bash
REFERENCE_COLLECTION_DIR=../references/my-pack OUTPUT_DIR=../references/my-pack/outputs PRESET_NAME=my-pack-v1 PROMPT_VERSION=v1 SCORING_POLICY_VERSION=preset-my-pack-v1 BASELINE_BENCHMARK_PATH=../tmp/baseline.json CANDIDATE_BENCHMARK_PATH=../tmp/candidate.json make reference-intelligence-benchmark
```

Generated artifacts:

- `reference_manifest.lock.json`
- `reference_sampling_map.json`
- `reference_ocr_report.json`
- `reference_style_report.json`
- `reference_clusters.json`
- `preset_bundle.json`
- `comparison_report.json` when comparison inputs are provided

## Safety And Decision Rules

- production runtime stays in `backend/`
- `experiments/autoresearch` does not get imported into production runtime
- no uncontrolled self-learning
- no automatic mutation of production ranking or render policies
- no whole-video multimodal analysis in v1
- no synthetic claims of success without a real reference pack
- any ranking-adjacent preset must be benchmarked against a frozen eval set before any human enablement decision

## Testing And Verification

Focused checks already used in this repo:

```bash
uv run pytest tests/test_reference_intelligence.py tests/test_eval_harness.py -q
uv run python ..\experiments\autoresearch\reference_intelligence.py --help
```

For the full disposable Postgres smoke path:

```bash
POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_shorts_engine_test uv run pytest tests/test_postgres_migration_smoke.py -m postgres -q
```

## Where The Project Is Going Next

The next bounded step should not be a broad rewrite.

Recommended next sequence:

1. Validate the pre-`M3` gate on the active prompt/scoring pair in disposable Postgres if not already done for the exact candidate version you want to advance.
2. Add a real canonical reference collection under `references/` and run controlled offline analysis.
3. Review OCR and VLM artifact quality on real references.
4. Decide whether taxonomy/prompt/schema need another bounded hardening pass.
5. Only after benchmark evidence and reference evidence are good enough, start `M3` preview/render implementation.

Do not do next:

- broad production/runtime migration of the experiments lane
- render activation based on synthetic data
- aggressive taxonomy hardcoding before real references exist
- policy enablement without benchmark and human review

## Key Documents

- [research-dossier.md](./research-dossier.md)
- [specification.md](./specification.md)
- [db-schema.md](./db-schema.md)
- [api-contract.md](./api-contract.md)
- [worker-contracts.md](./worker-contracts.md)
- [implementation-backlog.md](./implementation-backlog.md)
- [backend/README.md](./backend/README.md)
- [backend/gap-audit.md](./backend/gap-audit.md)
- [experiments/autoresearch/README.md](./experiments/autoresearch/README.md)

## Short Answer

If you need the one-paragraph version:

This repo is an internal AI-assisted short-video production engine with a working pre-render core. It already ingests owned long videos, transcribes them, extracts deterministic signals, ranks candidate shorts, and enforces offline benchmark gates. In parallel, it now has a contract-hardened offline reference-analysis lane for learning packaging priors from canonical shorts, especially for the first `3-4s`. The project is at the end of `M2 / pre-M3`: solid foundations exist, but render, QA, approval, and delivery are still ahead, and reference intelligence still needs validation on a real canonical dataset before it should influence downstream presets.

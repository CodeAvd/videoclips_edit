# macOS Runbook

This runbook is intentionally narrow: it covers the fastest way to work with this repo on macOS without guessing through the broader project docs.

## Prerequisites

- Python `3.11` or `3.12`
- `uv`
- `ffmpeg` and `ffprobe`
- Docker Desktop only if you want the full backend stack with local Postgres

Example Homebrew install:

```bash
brew install uv ffmpeg
```

## Track A: Offline Reference Lane Only

Use this when you want the analysis lane under `experiments/autoresearch` and do not need the API or worker runtime.

```bash
cd backend
uv sync
uv run python ../experiments/autoresearch/reference_intelligence.py --help
```

Run a real collection:

```bash
cd backend
REFERENCE_COLLECTION_DIR=../references/my-pack \
OUTPUT_DIR=../references/my-pack/outputs \
PRESET_NAME=my-pack-v1 \
PROMPT_VERSION=v1 \
SCORING_POLICY_VERSION=v1 \
make reference-intelligence
```

Optional OCR/VLM:

```bash
cd backend
REFERENCE_COLLECTION_DIR=../references/my-pack \
OUTPUT_DIR=../references/my-pack/outputs \
PRESET_NAME=my-pack-v1 \
PROMPT_VERSION=v1 \
SCORING_POLICY_VERSION=v1 \
OCR_PROVIDER=auto \
VLM_PROVIDER=openai \
VLM_MODEL=<vision-model> \
OPENAI_API_KEY=<key> \
make reference-intelligence
```

## Track B: Full Backend Local Run

Use this when you want API + worker + database-backed flow.

1. Start Docker Desktop.
2. From `backend/`, create a local env file and keep the default stub ASR unless you explicitly want cloud transcription.

```bash
cd backend
cp .env.example .env
make dev-up
uv sync
uv run alembic upgrade head
make api
```

Run the worker in a second shell:

```bash
cd backend
make worker
```

The checked-in `.env.example` is local-safe by default:

- `ASR_PROVIDER_PRIMARY=stub`
- `ASR_PROVIDER_FALLBACK=`

To switch to cloud ASR, update `.env` explicitly, for example:

```dotenv
ASR_PROVIDER_PRIMARY=groq
ASR_PROVIDER_FALLBACK=openai
GROQ_API_KEY=...
OPENAI_API_KEY=...
```

## Useful Checks

```bash
cd backend
uv run pytest tests/test_health.py tests/test_auth_rbac.py tests/test_uploads_api.py -q
uv run pytest tests/test_reference_intelligence.py -q
```

If Docker is not installed, the offline reference lane and SQLite-backed tests still work, but `make dev-up` and Postgres smoke paths will not.

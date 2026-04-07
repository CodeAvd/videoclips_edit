.PHONY: dev-up dev-down migrate api worker test test-postgres-smoke test-pre-m3-gates eval-benchmark reference-intelligence reference-intelligence-benchmark

export POSTGRES_TEST_DATABASE_URL ?= postgresql+asyncpg://postgres:postgres@localhost:5432/ai_shorts_engine_test

dev-up:
	docker compose up -d

dev-down:
	docker compose down -v

migrate:
	uv run alembic upgrade head

api:
	uv run uvicorn app.main:app --reload

worker:
	uv run python worker.py

test:
	uv run pytest

test-postgres-smoke:
	uv run pytest tests/test_postgres_migration_smoke.py -m postgres -q

test-pre-m3-gates:
	uv run pytest tests/test_postgres_migration_smoke.py tests/test_eval_harness.py -m postgres -q

eval-benchmark:
	uv run python -m app.services.eval_harness --eval-set-id $(EVAL_SET_ID) --prompt-version $(PROMPT_VERSION) --scoring-policy-version $(SCORING_POLICY_VERSION)

reference-intelligence:
	uv run python ../experiments/autoresearch/reference_intelligence.py --collection-dir $(REFERENCE_COLLECTION_DIR) $(if $(OUTPUT_DIR),--output-dir $(OUTPUT_DIR),) $(if $(PRESET_NAME),--preset-name $(PRESET_NAME),) --prompt-version $(PROMPT_VERSION) --scoring-policy-version $(SCORING_POLICY_VERSION) $(if $(FFPROBE_BIN),--ffprobe-bin $(FFPROBE_BIN),) $(if $(FFMPEG_BIN),--ffmpeg-bin $(FFMPEG_BIN),) $(if $(OCR_PROVIDER),--ocr-provider $(OCR_PROVIDER),) $(if $(TESSERACT_BIN),--tesseract-bin $(TESSERACT_BIN),) $(if $(VLM_PROVIDER),--vlm-provider $(VLM_PROVIDER),) $(if $(VLM_MODEL),--vlm-model $(VLM_MODEL),) $(if $(OPENAI_API_KEY),--openai-api-key $(OPENAI_API_KEY),)

reference-intelligence-benchmark:
	uv run python ../experiments/autoresearch/reference_intelligence.py --collection-dir $(REFERENCE_COLLECTION_DIR) $(if $(OUTPUT_DIR),--output-dir $(OUTPUT_DIR),) $(if $(PRESET_NAME),--preset-name $(PRESET_NAME),) --prompt-version $(PROMPT_VERSION) --scoring-policy-version $(SCORING_POLICY_VERSION) --baseline-benchmark $(BASELINE_BENCHMARK_PATH) --candidate-benchmark $(CANDIDATE_BENCHMARK_PATH) $(if $(FFPROBE_BIN),--ffprobe-bin $(FFPROBE_BIN),) $(if $(FFMPEG_BIN),--ffmpeg-bin $(FFMPEG_BIN),) $(if $(OCR_PROVIDER),--ocr-provider $(OCR_PROVIDER),) $(if $(TESSERACT_BIN),--tesseract-bin $(TESSERACT_BIN),) $(if $(VLM_PROVIDER),--vlm-provider $(VLM_PROVIDER),) $(if $(VLM_MODEL),--vlm-model $(VLM_MODEL),) $(if $(OPENAI_API_KEY),--openai-api-key $(OPENAI_API_KEY),)

.PHONY: dev-up dev-down migrate api worker test test-postgres-smoke test-pre-m3-gates eval-benchmark

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

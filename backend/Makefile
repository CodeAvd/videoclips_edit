.PHONY: dev-up dev-down migrate api worker test test-postgres-smoke

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

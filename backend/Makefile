.PHONY: dev-up dev-down migrate api worker test

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

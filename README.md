# Project Workspace

## Project

- Slug: ai-shorts-engine
- Date: 2026-04-04

## Files

- `research-dossier.md`
- `specification.md`
- `db-schema.md`
- `api-contract.md`
- `worker-contracts.md`
- `implementation-backlog.md`
- `backend/pyproject.toml`
- `backend/app/main.py`
- `backend/alembic/versions/0001_m0_m1_baseline.py`
- `backend/alembic/versions/0002_idempotency_outbox_reliability.py`
- `backend/alembic/versions/0003_m2_smart_clipping.py`
- `backend/gap-audit.md`
- `prompt-pack.md`
- `notes.md`
- `experiments/autoresearch/README.md`

## Workflow

1. Read `research-dossier.md` end to end before changing the stack.
2. Use `specification.md` as the implementation contract.
3. Use `db-schema.md` for SQLAlchemy and Alembic design.
4. Use `api-contract.md` for route and Pydantic contract work.
5. Use `worker-contracts.md` for orchestration, queue, and worker behavior.
6. Use `implementation-backlog.md` as the milestone and issue sequence.
7. Use `backend/` as the executable implementation for `M0-M2`.
8. Keep `experiments/autoresearch/` offline and out of the production worker graph.
9. Treat any parent-workspace ops or research packs as optional external references, not repo-local dependencies.

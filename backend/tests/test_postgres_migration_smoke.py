import pytest

from flow_helpers import run_job_pipeline_smoke

pytestmark = pytest.mark.postgres


async def test_postgres_migration_smoke(
    postgres_client,
    actor_headers,
    postgres_session_factory,
    storage_root,
    monkeypatch,
) -> None:
    await run_job_pipeline_smoke(
        client=postgres_client,
        actor_headers=actor_headers,
        session_factory=postgres_session_factory,
        storage_root=storage_root,
        monkeypatch=monkeypatch,
    )

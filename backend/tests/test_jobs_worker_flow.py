from flow_helpers import run_job_pipeline_smoke


async def test_job_dedupe_and_worker_stub_pipeline(client, actor_headers, session_factory, storage_root, monkeypatch) -> None:
    await run_job_pipeline_smoke(
        client=client,
        actor_headers=actor_headers,
        session_factory=session_factory,
        storage_root=storage_root,
        monkeypatch=monkeypatch,
    )

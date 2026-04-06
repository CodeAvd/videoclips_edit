from uuid import UUID

import pytest
from sqlalchemy import inspect, select

from app.core.errors import AppError
from app.models.enums import ArtifactKind, CandidateLabelValue, EvalSetStatus
from app.models.job import ArtifactObject, BenchmarkResult
from app.services import eval_harness
from app.services.storage import get_storage_service
from flow_helpers import create_uploaded_source_video, run_job_pipeline_smoke


async def test_eval_tables_exist_in_metadata(session_factory) -> None:
    engine = session_factory.kw["bind"]
    async with engine.begin() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    for table_name in ("eval_set", "eval_set_member", "candidate_label", "benchmark_run", "benchmark_result"):
        assert table_name in table_names


async def test_run_benchmark_persists_comparison_artifact_and_results(
    client,
    actor_headers,
    session_factory,
    storage_root,
    monkeypatch,
) -> None:
    context = await run_job_pipeline_smoke(
        client=client,
        actor_headers=actor_headers,
        session_factory=session_factory,
        storage_root=storage_root,
        monkeypatch=monkeypatch,
    )
    source_video_id = UUID(str(context["source_video_id"]))
    candidate_items = context["candidate_items"]

    async with session_factory() as session:
        eval_set = await eval_harness.create_eval_set(
            session,
            name="Pre-M3 Frozen Benchmark",
            status=EvalSetStatus.frozen,
        )
        await eval_harness.add_eval_set_member(
            session,
            eval_set_id=eval_set.id,
            source_video_id=source_video_id,
        )
        await eval_harness.store_candidate_label(
            session,
            eval_set_id=eval_set.id,
            source_video_id=source_video_id,
            start_ms=candidate_items[0]["start_ms"],
            end_ms=candidate_items[0]["end_ms"],
            label=CandidateLabelValue.accept,
            actor_ref="reviewer-1",
            notes="Known-good benchmark window.",
        )
        await eval_harness.store_candidate_label(
            session,
            eval_set_id=eval_set.id,
            source_video_id=source_video_id,
            start_ms=candidate_items[-1]["start_ms"],
            end_ms=candidate_items[-1]["end_ms"],
            label=CandidateLabelValue.reject,
            actor_ref="reviewer-1",
            notes="Low-priority window that should stay out of the top-5.",
        )
        await session.commit()
        eval_set_id = eval_set.id

    async with session_factory() as session:
        benchmark_run = await eval_harness.run_benchmark(
            session,
            eval_set_id=eval_set_id,
            prompt_version="v1",
            scoring_policy_version="v1",
        )
        verified_run = await eval_harness.assert_pre_m3_benchmark_ready(
            session,
            eval_set_id=eval_set_id,
            prompt_version="v1",
            scoring_policy_version="v1",
        )
        results = (
            await session.execute(
                select(BenchmarkResult).where(BenchmarkResult.benchmark_run_id == benchmark_run.id)
            )
        ).scalars().all()
        artifact = await session.get(ArtifactObject, benchmark_run.artifact_id)
        await session.commit()

    assert verified_run.id == benchmark_run.id
    assert artifact is not None
    assert artifact.storage_key == f"benchmarks/{benchmark_run.id}/comparison.json"
    assert artifact.metadata_jsonb["artifact_type"] == "benchmark_comparison"
    payload = get_storage_service().read_json(storage_key=artifact.storage_key)
    assert payload["benchmark_run_id"] == str(benchmark_run.id)
    assert payload["sources"][0]["source_video_id"] == str(source_video_id)
    assert {result.metric_name for result in results} == {
        eval_harness.BENCHMARK_METRIC_ACCEPT_TOP_5,
        eval_harness.BENCHMARK_METRIC_ACCEPT_TOP_10,
        eval_harness.BENCHMARK_METRIC_REJECT_TOP_5,
    }


async def test_pre_m3_benchmark_gate_requires_comparison_artifact(session_factory) -> None:
    async with session_factory() as session:
        eval_set = await eval_harness.create_eval_set(
            session,
            name="Incomplete Benchmark",
            status=EvalSetStatus.frozen,
        )
        await eval_harness.create_benchmark_run(
            session,
            eval_set_id=eval_set.id,
            prompt_version="v1",
            scoring_policy_version="v1",
            artifact_id=None,
        )
        await session.commit()
        eval_set_id = eval_set.id

    async with session_factory() as session:
        with pytest.raises(AppError) as exc_info:
            await eval_harness.assert_pre_m3_benchmark_ready(
                session,
                eval_set_id=eval_set_id,
                prompt_version="v1",
                scoring_policy_version="v1",
            )

    assert exc_info.value.code == "benchmark_gate_unmet"


async def test_run_benchmark_rejects_non_frozen_eval_set(session_factory) -> None:
    async with session_factory() as session:
        eval_set = await eval_harness.create_eval_set(
            session,
            name="Draft Benchmark",
            status=EvalSetStatus.draft,
        )
        await session.commit()

        with pytest.raises(AppError) as exc_info:
            await eval_harness.run_benchmark(
                session,
                eval_set_id=eval_set.id,
                prompt_version="v1",
                scoring_policy_version="v1",
            )

    assert exc_info.value.code == "eval_set_not_frozen"


async def test_run_benchmark_rejects_empty_eval_set(session_factory) -> None:
    async with session_factory() as session:
        eval_set = await eval_harness.create_eval_set(
            session,
            name="Empty Frozen Benchmark",
            status=EvalSetStatus.frozen,
        )
        await session.commit()

        with pytest.raises(AppError) as exc_info:
            await eval_harness.run_benchmark(
                session,
                eval_set_id=eval_set.id,
                prompt_version="v1",
                scoring_policy_version="v1",
            )

    assert exc_info.value.code == "eval_set_empty"


async def test_run_benchmark_requires_labels_for_each_member(
    client,
    actor_headers,
    session_factory,
    storage_root,
    monkeypatch,
) -> None:
    context = await run_job_pipeline_smoke(
        client=client,
        actor_headers=actor_headers,
        session_factory=session_factory,
        storage_root=storage_root,
        monkeypatch=monkeypatch,
    )
    source_video_id = UUID(str(context["source_video_id"]))

    async with session_factory() as session:
        eval_set = await eval_harness.create_eval_set(
            session,
            name="Frozen Without Labels",
            status=EvalSetStatus.frozen,
        )
        await eval_harness.add_eval_set_member(
            session,
            eval_set_id=eval_set.id,
            source_video_id=source_video_id,
        )
        await session.commit()

        with pytest.raises(AppError) as exc_info:
            await eval_harness.run_benchmark(
                session,
                eval_set_id=eval_set.id,
                prompt_version="v1",
                scoring_policy_version="v1",
            )

    assert exc_info.value.code == "benchmark_labels_missing"


async def test_run_benchmark_requires_eligible_job(
    client,
    actor_headers,
    session_factory,
) -> None:
    _, source_video_id = await create_uploaded_source_video(client, actor_headers)
    source_video_uuid = UUID(source_video_id)

    async with session_factory() as session:
        eval_set = await eval_harness.create_eval_set(
            session,
            name="Frozen Without Job",
            status=EvalSetStatus.frozen,
        )
        await eval_harness.add_eval_set_member(
            session,
            eval_set_id=eval_set.id,
            source_video_id=source_video_uuid,
        )
        await eval_harness.store_candidate_label(
            session,
            eval_set_id=eval_set.id,
            source_video_id=source_video_uuid,
            start_ms=0,
            end_ms=1000,
            label=CandidateLabelValue.accept,
            actor_ref="reviewer-1",
            notes="Benchmark anchor.",
        )
        await session.commit()

        with pytest.raises(AppError) as exc_info:
            await eval_harness.run_benchmark(
                session,
                eval_set_id=eval_set.id,
                prompt_version="v1",
                scoring_policy_version="v1",
            )

    assert exc_info.value.code == "benchmark_job_missing"


async def test_pre_m3_benchmark_gate_requires_persisted_results(session_factory) -> None:
    async with session_factory() as session:
        eval_set = await eval_harness.create_eval_set(
            session,
            name="Benchmark Without Results",
            status=EvalSetStatus.frozen,
        )
        artifact = ArtifactObject(
            storage_key="benchmarks/mock/comparison.json",
            kind=ArtifactKind.stage_artifact,
            sha256="deadbeef",
            size_bytes=128,
            mime_type="application/json",
            metadata_jsonb={"artifact_type": "benchmark_comparison"},
        )
        session.add(artifact)
        await session.flush()
        await eval_harness.create_benchmark_run(
            session,
            eval_set_id=eval_set.id,
            prompt_version="v1",
            scoring_policy_version="v1",
            artifact_id=artifact.id,
        )
        await session.commit()
        eval_set_id = eval_set.id

    async with session_factory() as session:
        with pytest.raises(AppError) as exc_info:
            await eval_harness.assert_pre_m3_benchmark_ready(
                session,
                eval_set_id=eval_set_id,
                prompt_version="v1",
                scoring_policy_version="v1",
            )

    assert exc_info.value.code == "benchmark_gate_unmet"


@pytest.mark.postgres
async def test_postgres_migration_creates_eval_tables(postgres_session_factory) -> None:
    engine = postgres_session_factory.kw["bind"]
    async with engine.begin() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    for table_name in ("eval_set", "eval_set_member", "candidate_label", "benchmark_run", "benchmark_result"):
        assert table_name in table_names

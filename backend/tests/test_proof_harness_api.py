import json
from uuid import UUID

import pytest
from sqlalchemy import inspect, select

from app.models.enums import ProofShortlistSystem
from app.models.job import ArtifactObject, ProofComparisonResult, ProofReviewBatch
from app.services.storage import get_storage_service
from flow_helpers import run_job_pipeline_smoke


async def test_proof_harness_tables_exist_in_metadata(session_factory) -> None:
    engine = session_factory.kw["bind"]
    async with engine.begin() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    for table_name in (
        "proof_shortlist",
        "proof_shortlist_candidate",
        "proof_review_session",
        "proof_review_batch",
        "proof_review_decision",
        "proof_review_preference",
        "proof_comparison_run",
        "proof_comparison_result",
    ):
        assert table_names
        assert table_name in table_names


async def test_stage_a_proof_harness_flow(
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
    assert len(context["candidate_items"]) >= 8

    reviewer_headers = {
        "X-Actor-Id": "reviewer-1",
        "X-Actor-Role": "reviewer",
    }

    eval_set_response = await client.post(
        "/api/v1/proof-harness/eval-sets",
        headers=actor_headers,
        json={"name": "Stage A Holdout", "status": "frozen"},
    )
    assert eval_set_response.status_code == 200
    eval_set_id = eval_set_response.json()["id"]

    member_response = await client.post(
        f"/api/v1/proof-harness/eval-sets/{eval_set_id}/members",
        headers=actor_headers,
        json={
            "source_video_id": context["source_video_id"],
            "metadata_jsonb": {
                "split": "holdout",
                "channel_series": "channel-alpha",
                "content_pattern": "single-speaker-explainer",
            },
        },
    )
    assert member_response.status_code == 200

    engine_shortlist_response = await client.post(
        f"/api/v1/proof-harness/jobs/{context['job_id']}/engine-shortlist",
        headers=actor_headers,
        json={"eval_set_id": eval_set_id},
    )
    assert engine_shortlist_response.status_code == 200
    engine_shortlist = engine_shortlist_response.json()
    assert engine_shortlist["system_name"] == "engine"
    assert engine_shortlist["candidate_count"] == 8
    assert len(engine_shortlist["candidates"]) == 8

    candidate_windows = context["candidate_items"][:8]
    manual_shortlist_response = await client.post(
        f"/api/v1/proof-harness/source-videos/{context['source_video_id']}/baseline-shortlists",
        headers=actor_headers,
        json={
            "system_name": "manual",
            "eval_set_id": eval_set_id,
            "generation_time_seconds": 1500,
            "metadata_jsonb": {"workflow": "manual-first-pass"},
            "candidates": [
                {
                    "start_ms": item["start_ms"],
                    "end_ms": item["end_ms"],
                    "rationale_jsonb": {"source": "manual"},
                    "metadata_jsonb": {"operator_notes": f"manual-{index}"},
                }
                for index, item in enumerate(candidate_windows, start=1)
            ],
        },
    )
    assert manual_shortlist_response.status_code == 200

    vizard_shortlist_response = await client.post(
        f"/api/v1/proof-harness/source-videos/{context['source_video_id']}/baseline-shortlists",
        headers=actor_headers,
        json={
            "system_name": "vizard",
            "eval_set_id": eval_set_id,
            "generation_time_seconds": 540,
            "metadata_jsonb": {"workflow": "vizard-fixed"},
            "candidates": [
                {
                    "start_ms": item["start_ms"],
                    "end_ms": item["end_ms"],
                    "rationale_jsonb": {"source": "vizard"},
                    "metadata_jsonb": {"provider_clip_id": f"vz-{index}"},
                }
                for index, item in enumerate(candidate_windows, start=1)
            ],
        },
    )
    assert vizard_shortlist_response.status_code == 200

    list_shortlists_response = await client.get(
        f"/api/v1/proof-harness/source-videos/{context['source_video_id']}/shortlists",
        headers=actor_headers,
    )
    assert list_shortlists_response.status_code == 200
    shortlists = list_shortlists_response.json()["items"]
    assert {item["system_name"] for item in shortlists} == {"engine", "manual", "vizard"}
    assert all(len(item["candidates"]) == 8 for item in shortlists)

    review_session_response = await client.post(
        "/api/v1/proof-harness/review-sessions",
        headers=reviewer_headers,
        json={
            "eval_set_id": eval_set_id,
            "source_video_id": context["source_video_id"],
            "is_audit": False,
            "time_budget_seconds": 600,
        },
    )
    assert review_session_response.status_code == 200
    review_session = review_session_response.json()
    review_session_id = review_session["id"]
    assert review_session["status"] == "in_progress"
    assert {batch["batch_code"] for batch in review_session["batches"]} == {"A", "B", "C"}
    assert all(len(batch["candidates"]) == 8 for batch in review_session["batches"])
    assert all("system_name" not in batch for batch in review_session["batches"])
    assert "reviewer_actor_ref" not in review_session
    assert "is_audit" not in review_session
    serialized_review_session = json.dumps(review_session)
    assert "manual" not in serialized_review_session
    assert "vizard" not in serialized_review_session
    assert "engine" not in serialized_review_session

    async with session_factory() as session:
        batch_rows = (
            await session.execute(
                select(ProofReviewBatch).where(ProofReviewBatch.proof_review_session_id == UUID(review_session_id))
            )
        ).scalars().all()

    batch_code_by_system = {row.system_name.value: row.batch_code for row in batch_rows}
    system_by_batch_code = {row.batch_code: row.system_name for row in batch_rows}

    batch_reviews = []
    for batch in review_session["batches"]:
        system_name = system_by_batch_code[batch["batch_code"]]
        candidate_decisions = []
        for index, candidate in enumerate(batch["candidates"], start=1):
            if system_name == ProofShortlistSystem.engine:
                if index <= 4:
                    candidate_decisions.append(
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "approve",
                            "rationale_helpful": index != 4,
                        }
                    )
                elif index == 5:
                    candidate_decisions.append(
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "reject",
                            "reject_reason_code": "duplicate_angle",
                            "rationale_helpful": True,
                        }
                    )
                else:
                    candidate_decisions.append(
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "reject",
                            "reject_reason_code": "weak_opening",
                            "rationale_helpful": False,
                        }
                    )
            elif system_name == ProofShortlistSystem.manual:
                if index <= 2:
                    candidate_decisions.append(
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "approve",
                            "rationale_helpful": index == 1,
                        }
                    )
                else:
                    candidate_decisions.append(
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "reject",
                            "reject_reason_code": "needs_context",
                            "rationale_helpful": False,
                        }
                    )
            else:
                if index == 1:
                    candidate_decisions.append(
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "approve",
                            "rationale_helpful": False,
                        }
                    )
                elif index <= 3:
                    candidate_decisions.append(
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "reject",
                            "reject_reason_code": "duplicate_angle",
                            "rationale_helpful": False,
                        }
                    )
                else:
                    candidate_decisions.append(
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "reject",
                            "reject_reason_code": "off_topic_or_low_signal",
                            "rationale_helpful": False,
                        }
                    )

        elapsed_review_seconds = 420 if system_name == ProofShortlistSystem.engine else 540 if system_name == ProofShortlistSystem.manual else 390
        batch_reviews.append(
            {
                "batch_code": batch["batch_code"],
                "elapsed_review_seconds": elapsed_review_seconds,
                "candidate_decisions": candidate_decisions,
            }
        )

    complete_session_response = await client.post(
        f"/api/v1/proof-harness/review-sessions/{review_session_id}/complete",
        headers=reviewer_headers,
        json={
            "batch_reviews": batch_reviews,
            "batch_preference_ranking": [
                batch_code_by_system["engine"],
                batch_code_by_system["manual"],
                batch_code_by_system["vizard"],
            ],
        },
    )
    assert complete_session_response.status_code == 200
    completed_session = complete_session_response.json()
    assert completed_session["status"] == "completed"

    comparison_run_response = await client.post(
        "/api/v1/proof-harness/comparison-runs",
        headers=actor_headers,
        json={"eval_set_id": eval_set_id},
    )
    assert comparison_run_response.status_code == 200
    comparison_run = comparison_run_response.json()
    assert comparison_run["payload"]["artifact_type"] == "proof_comparison"
    assert comparison_run["payload"]["source_count"] == 1
    assert comparison_run["payload"]["source_level_wins"]["approved_clip_win_source_count"] == 1
    assert comparison_run["payload"]["source_level_wins"]["batch_preference_win_source_count"] == 1
    assert comparison_run["payload"]["system_aggregate"]["engine"]["median_approved_clips_per_video"] == 4.0

    async with session_factory() as session:
        results = (
            await session.execute(
                select(ProofComparisonResult).where(
                    ProofComparisonResult.proof_comparison_run_id == UUID(comparison_run["id"])
                )
            )
        ).scalars().all()
        artifact = await session.get(ArtifactObject, UUID(comparison_run["artifact_id"]))

    assert artifact is not None
    assert artifact.storage_key.endswith("/comparison.json")
    assert len(results) == 21
    assert comparison_run["payload"]["judgment_basis"] == "holdout_only"
    assert comparison_run["payload"]["development_results_count_as_stop_go_evidence"] is False


async def test_reviewer_payloads_are_blinded_and_shortlist_operator_route_is_restricted(
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
    reviewer_headers = {
        "X-Actor-Id": "reviewer-1",
        "X-Actor-Role": "reviewer",
    }

    eval_set_response = await client.post(
        "/api/v1/proof-harness/eval-sets",
        headers=actor_headers,
        json={"name": "Blinding Audit Holdout", "status": "frozen"},
    )
    eval_set_id = eval_set_response.json()["id"]
    await client.post(
        f"/api/v1/proof-harness/eval-sets/{eval_set_id}/members",
        headers=actor_headers,
        json={
            "source_video_id": context["source_video_id"],
            "metadata_jsonb": {
                "split": "holdout",
                "channel_series": "channel-alpha",
                "content_pattern": "single-speaker-explainer",
            },
        },
    )
    await client.post(
        f"/api/v1/proof-harness/jobs/{context['job_id']}/engine-shortlist",
        headers=actor_headers,
        json={"eval_set_id": eval_set_id},
    )
    candidate_windows = context["candidate_items"][:8]
    await client.post(
        f"/api/v1/proof-harness/source-videos/{context['source_video_id']}/baseline-shortlists",
        headers=actor_headers,
        json={
            "system_name": "manual",
            "eval_set_id": eval_set_id,
            "metadata_jsonb": {"workflow": "manual-first-pass"},
            "candidates": [
                {
                    "start_ms": item["start_ms"],
                    "end_ms": item["end_ms"],
                    "rationale_jsonb": {"source": "manual"},
                    "metadata_jsonb": {"operator_notes": f"manual-{index}"},
                }
                for index, item in enumerate(candidate_windows, start=1)
            ],
        },
    )
    await client.post(
        f"/api/v1/proof-harness/source-videos/{context['source_video_id']}/baseline-shortlists",
        headers=actor_headers,
        json={
            "system_name": "vizard",
            "eval_set_id": eval_set_id,
            "metadata_jsonb": {"workflow": "vizard-fixed"},
            "candidates": [
                {
                    "start_ms": item["start_ms"],
                    "end_ms": item["end_ms"],
                    "rationale_jsonb": {"source": "vizard"},
                    "metadata_jsonb": {"provider_clip_id": f"vz-{index}"},
                }
                for index, item in enumerate(candidate_windows, start=1)
            ],
        },
    )

    shortlist_response = await client.get(
        f"/api/v1/proof-harness/source-videos/{context['source_video_id']}/shortlists",
        headers=reviewer_headers,
    )
    assert shortlist_response.status_code == 403

    review_session_response = await client.post(
        "/api/v1/proof-harness/review-sessions",
        headers=reviewer_headers,
        json={
            "eval_set_id": eval_set_id,
            "source_video_id": context["source_video_id"],
            "time_budget_seconds": 600,
        },
    )
    assert review_session_response.status_code == 200
    payload = review_session_response.json()
    serialized = json.dumps(payload)
    for forbidden_token in (
        "manual",
        "vizard",
        "engine",
        "workflow",
        "provider_clip_id",
        "operator_notes",
        "metadata_jsonb",
        "rationale_jsonb",
        "duplicate_group",
        "topic_cluster",
        "length_bucket",
        "final_score",
        "reviewer_actor_ref",
        "is_audit",
    ):
        assert forbidden_token not in serialized

    preview_storage_key = payload["batches"][0]["candidates"][0]["preview_storage_key"]
    preview_payload = get_storage_service().read_json(storage_key=preview_storage_key)
    serialized_preview = json.dumps(preview_payload)
    for forbidden_token in (
        "system_name",
        "system_name_internal",
        "manual",
        "vizard",
        "engine",
        "rationale_jsonb",
    ):
        assert forbidden_token not in serialized_preview
    assert preview_payload["render_policy"]["system_of_origin_visible"] is False
    assert preview_payload["preview_window"]["start_ms"] == payload["batches"][0]["candidates"][0]["start_ms"]


async def test_baseline_import_rejects_non_8_candidate_payloads(
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
    eval_set_response = await client.post(
        "/api/v1/proof-harness/eval-sets",
        headers=actor_headers,
        json={"name": "Negative Baseline Count", "status": "frozen"},
    )
    eval_set_id = eval_set_response.json()["id"]
    await client.post(
        f"/api/v1/proof-harness/eval-sets/{eval_set_id}/members",
        headers=actor_headers,
        json={
            "source_video_id": context["source_video_id"],
            "metadata_jsonb": {"split": "dev", "channel_series": "alpha", "content_pattern": "explainer"},
        },
    )

    candidate_windows = context["candidate_items"]
    for invalid_count in (7, 9):
        response = await client.post(
            f"/api/v1/proof-harness/source-videos/{context['source_video_id']}/baseline-shortlists",
            headers=actor_headers,
            json={
                "system_name": "manual",
                "eval_set_id": eval_set_id,
                "candidates": [
                    {
                        "start_ms": item["start_ms"],
                        "end_ms": item["end_ms"],
                    }
                    for item in candidate_windows[:invalid_count]
                ],
            },
        )
        assert response.status_code == 422


async def test_review_completion_requires_exactly_8_decisions_per_batch(
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
    reviewer_headers = {
        "X-Actor-Id": "reviewer-1",
        "X-Actor-Role": "reviewer",
    }
    eval_set_response = await client.post(
        "/api/v1/proof-harness/eval-sets",
        headers=actor_headers,
        json={"name": "Negative Review Count", "status": "frozen"},
    )
    eval_set_id = eval_set_response.json()["id"]
    await client.post(
        f"/api/v1/proof-harness/eval-sets/{eval_set_id}/members",
        headers=actor_headers,
        json={
            "source_video_id": context["source_video_id"],
            "metadata_jsonb": {"split": "dev", "channel_series": "alpha", "content_pattern": "explainer"},
        },
    )
    await client.post(
        f"/api/v1/proof-harness/jobs/{context['job_id']}/engine-shortlist",
        headers=actor_headers,
        json={"eval_set_id": eval_set_id},
    )
    candidate_windows = context["candidate_items"][:8]
    for system_name in ("manual", "vizard"):
        await client.post(
            f"/api/v1/proof-harness/source-videos/{context['source_video_id']}/baseline-shortlists",
            headers=actor_headers,
            json={
                "system_name": system_name,
                "eval_set_id": eval_set_id,
                "candidates": [
                    {
                        "start_ms": item["start_ms"],
                        "end_ms": item["end_ms"],
                    }
                    for item in candidate_windows
                ],
            },
        )

    review_session_response = await client.post(
        "/api/v1/proof-harness/review-sessions",
        headers=reviewer_headers,
        json={
            "eval_set_id": eval_set_id,
            "source_video_id": context["source_video_id"],
        },
    )
    review_session = review_session_response.json()
    first_batch = review_session["batches"][0]
    response = await client.post(
        f"/api/v1/proof-harness/review-sessions/{review_session['id']}/complete",
        headers=reviewer_headers,
        json={
            "batch_reviews": [
                {
                    "batch_code": first_batch["batch_code"],
                    "elapsed_review_seconds": 300,
                    "candidate_decisions": [
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "approve",
                            "rationale_helpful": True,
                        }
                        for candidate in first_batch["candidates"][:7]
                    ],
                },
                {
                    "batch_code": "B",
                    "elapsed_review_seconds": 300,
                    "candidate_decisions": [
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "approve",
                            "rationale_helpful": True,
                        }
                        for candidate in review_session["batches"][1]["candidates"]
                    ],
                },
                {
                    "batch_code": "C",
                    "elapsed_review_seconds": 300,
                    "candidate_decisions": [
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "approve",
                            "rationale_helpful": True,
                        }
                        for candidate in review_session["batches"][2]["candidates"]
                    ],
                },
            ],
            "batch_preference_ranking": ["A", "B", "C"],
        },
    )
    assert response.status_code == 422


async def test_comparison_run_requires_frozen_eval_set(
    client,
    actor_headers,
) -> None:
    eval_set_response = await client.post(
        "/api/v1/proof-harness/eval-sets",
        headers=actor_headers,
        json={"name": "Draft Eval Set", "status": "draft"},
    )
    response = await client.post(
        "/api/v1/proof-harness/comparison-runs",
        headers=actor_headers,
        json={"eval_set_id": eval_set_response.json()["id"]},
    )
    assert response.status_code == 409


async def test_audit_review_requires_completed_primary_review_and_independent_reviewer(
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
    eval_set_response = await client.post(
        "/api/v1/proof-harness/eval-sets",
        headers=actor_headers,
        json={"name": "Audit Guard Eval Set", "status": "frozen"},
    )
    eval_set_id = eval_set_response.json()["id"]
    await client.post(
        f"/api/v1/proof-harness/eval-sets/{eval_set_id}/members",
        headers=actor_headers,
        json={
            "source_video_id": context["source_video_id"],
            "metadata_jsonb": {"split": "holdout", "channel_series": "alpha", "content_pattern": "explainer"},
        },
    )
    await client.post(
        f"/api/v1/proof-harness/jobs/{context['job_id']}/engine-shortlist",
        headers=actor_headers,
        json={"eval_set_id": eval_set_id},
    )
    candidate_windows = context["candidate_items"][:8]
    for system_name in ("manual", "vizard"):
        await client.post(
            f"/api/v1/proof-harness/source-videos/{context['source_video_id']}/baseline-shortlists",
            headers=actor_headers,
            json={
                "system_name": system_name,
                "eval_set_id": eval_set_id,
                "candidates": [
                    {
                        "start_ms": item["start_ms"],
                        "end_ms": item["end_ms"],
                    }
                    for item in candidate_windows
                ],
            },
        )

    primary_reviewer_headers = {
        "X-Actor-Id": "reviewer-primary",
        "X-Actor-Role": "reviewer",
    }
    response = await client.post(
        "/api/v1/proof-harness/review-sessions",
        headers=primary_reviewer_headers,
        json={
            "eval_set_id": eval_set_id,
            "source_video_id": context["source_video_id"],
            "is_audit": True,
        },
    )
    assert response.status_code == 409

    primary_review_session_response = await client.post(
        "/api/v1/proof-harness/review-sessions",
        headers=primary_reviewer_headers,
        json={
            "eval_set_id": eval_set_id,
            "source_video_id": context["source_video_id"],
        },
    )
    primary_review_session = primary_review_session_response.json()
    response = await client.post(
        "/api/v1/proof-harness/review-sessions",
        headers=primary_reviewer_headers,
        json={
            "eval_set_id": eval_set_id,
            "source_video_id": context["source_video_id"],
            "is_audit": True,
        },
    )
    assert response.status_code == 409

    complete_response = await client.post(
        f"/api/v1/proof-harness/review-sessions/{primary_review_session['id']}/complete",
        headers=primary_reviewer_headers,
        json={
            "batch_reviews": [
                {
                    "batch_code": batch["batch_code"],
                    "elapsed_review_seconds": 300,
                    "candidate_decisions": [
                        {
                            "proof_shortlist_candidate_id": candidate["id"],
                            "decision": "approve",
                            "rationale_helpful": True,
                        }
                        for candidate in batch["candidates"]
                    ],
                }
                for batch in primary_review_session["batches"]
            ],
            "batch_preference_ranking": ["A", "B", "C"],
        },
    )
    assert complete_response.status_code == 200

    audit_reviewer_headers = {
        "X-Actor-Id": "reviewer-audit",
        "X-Actor-Role": "reviewer",
    }
    audit_session_response = await client.post(
        "/api/v1/proof-harness/review-sessions",
        headers=audit_reviewer_headers,
        json={
            "eval_set_id": eval_set_id,
            "source_video_id": context["source_video_id"],
            "is_audit": True,
        },
    )
    assert audit_session_response.status_code == 200


@pytest.mark.postgres
async def test_postgres_migration_creates_proof_harness_tables(postgres_session_factory) -> None:
    engine = postgres_session_factory.kw["bind"]
    async with engine.begin() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    for table_name in (
        "proof_shortlist",
        "proof_shortlist_candidate",
        "proof_review_session",
        "proof_review_batch",
        "proof_review_decision",
        "proof_review_preference",
        "proof_comparison_run",
        "proof_comparison_result",
    ):
        assert table_name in table_names

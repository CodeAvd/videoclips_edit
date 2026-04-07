from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import median
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.enums import (
    ArtifactKind,
    EvalSetStatus,
    ProofDecisionValue,
    ProofRejectReasonCode,
    ProofReviewStatus,
    ProofShortlistSystem,
    SourceVideoArtifactRole,
)
from app.models.job import (
    ArtifactObject,
    CandidateClip,
    CandidateSet,
    EvalSet,
    EvalSetMember,
    Job,
    ProofComparisonResult,
    ProofComparisonRun,
    ProofReviewBatch,
    ProofReviewDecision,
    ProofReviewPreference,
    ProofReviewSession,
    ProofShortlist,
    ProofShortlistCandidate,
    TranscriptSegment,
)
from app.services.source_video_artifacts import get_preferred_video_artifact, get_source_video_artifact
from app.services.storage import get_storage_service
from app.services.worker_runtime import get_current_transcript_revision, list_transcript_segments


PROOF_SHORTLIST_SIZE = 8
PROOF_BATCH_CODES = ("A", "B", "C")
PROOF_PROTOCOL_VERSION = "stage_a_v1"
PROOF_REVIEW_TIME_BUDGET_SECONDS = 600
JUNK_REJECT_REASONS = {
    ProofRejectReasonCode.weak_opening,
    ProofRejectReasonCode.late_or_missing_payoff,
    ProofRejectReasonCode.needs_context,
    ProofRejectReasonCode.fragmented_cut,
    ProofRejectReasonCode.off_topic_or_low_signal,
    ProofRejectReasonCode.review_timeout,
}
PROOF_COMPARISON_METRICS = (
    "approved_clips",
    "junk_rate",
    "duplicate_angle_rate",
    "reviewer_time_seconds",
    "rationale_helpful_rate_on_approved",
    "batch_preference_rank",
    "batch_preference_win",
)


@dataclass(slots=True)
class SystemReviewMetrics:
    approved_clips: int
    junk_rate: float
    duplicate_angle_rate: float
    reviewer_time_seconds: float
    rationale_helpful_rate_on_approved: float
    batch_preference_rank: int
    batch_preference_win: float
    approved_rationale_helpful_count: int


def windows_overlap(*, start_ms: int, end_ms: int, other_start_ms: int, other_end_ms: int) -> bool:
    return start_ms < other_end_ms and other_start_ms < end_ms


def coerce_float(value: Any) -> float:
    return float(value) if value is not None else 0.0


def truncate_excerpt(text: str, *, limit: int = 360) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


async def write_json_artifact(
    session: AsyncSession,
    *,
    storage_key: str,
    payload: dict | list,
    metadata_jsonb: dict,
) -> ArtifactObject:
    storage = get_storage_service()
    stored = storage.write_json(storage_key=storage_key, payload=payload)
    artifact = ArtifactObject(
        storage_key=storage_key,
        kind=ArtifactKind.stage_artifact,
        sha256=stored.sha256 or "",
        size_bytes=stored.size_bytes,
        mime_type=stored.content_type or "application/json",
        metadata_jsonb=metadata_jsonb | {"storage_backend": stored.backend},
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def create_eval_set(
    session: AsyncSession,
    *,
    name: str,
    status: EvalSetStatus = EvalSetStatus.draft,
) -> EvalSet:
    eval_set = EvalSet(name=name, status=status)
    session.add(eval_set)
    await session.flush()
    return eval_set


async def get_eval_set(session: AsyncSession, *, eval_set_id: UUID) -> EvalSet:
    eval_set = await session.get(EvalSet, eval_set_id)
    if eval_set is None:
        raise AppError(code="eval_set_not_found", message="Eval set not found.", http_status=404)
    return eval_set


async def add_eval_set_member(
    session: AsyncSession,
    *,
    eval_set_id: UUID,
    source_video_id: UUID,
    metadata_jsonb: dict | None = None,
) -> EvalSetMember:
    existing = await session.get(EvalSetMember, {"eval_set_id": eval_set_id, "source_video_id": source_video_id})
    if existing is not None:
        existing.metadata_jsonb = metadata_jsonb or existing.metadata_jsonb
        await session.flush()
        return existing

    member = EvalSetMember(
        eval_set_id=eval_set_id,
        source_video_id=source_video_id,
        metadata_jsonb=metadata_jsonb or {},
    )
    session.add(member)
    await session.flush()
    return member


async def list_eval_set_members(session: AsyncSession, *, eval_set_id: UUID) -> list[EvalSetMember]:
    result = await session.execute(
        select(EvalSetMember)
        .where(EvalSetMember.eval_set_id == eval_set_id)
        .order_by(EvalSetMember.created_at.asc())
    )
    return list(result.scalars().all())


async def ensure_eval_set_membership(session: AsyncSession, *, eval_set_id: UUID, source_video_id: UUID) -> EvalSetMember:
    member = await session.get(EvalSetMember, {"eval_set_id": eval_set_id, "source_video_id": source_video_id})
    if member is None:
        raise AppError(
            code="eval_set_member_missing",
            message="Source video is not a member of the requested eval set.",
            http_status=409,
        )
    return member


async def get_latest_transcribed_job_for_source_video(session: AsyncSession, *, source_video_id: UUID) -> Job:
    result = await session.execute(
        select(Job)
        .where(Job.source_video_id == source_video_id)
        .order_by(Job.created_at.desc())
    )
    for job in result.scalars().all():
        try:
            await get_current_transcript_revision(session, job_id=job.id)
            return job
        except AppError:
            continue
    raise AppError(
        code="proof_job_missing",
        message="No job with a current transcript exists for the requested source video.",
        http_status=409,
    )


async def get_current_candidate_set(session: AsyncSession, *, job_id: UUID) -> CandidateSet:
    result = await session.execute(
        select(CandidateSet)
        .where(CandidateSet.job_id == job_id, CandidateSet.is_current.is_(True))
        .order_by(CandidateSet.version_no.desc())
        .limit(1)
    )
    candidate_set = result.scalars().first()
    if candidate_set is None:
        raise AppError(code="candidate_set_not_found", message="Current candidate set not found.", http_status=404)
    return candidate_set


async def list_current_candidate_clips(session: AsyncSession, *, candidate_set_id: UUID) -> list[CandidateClip]:
    result = await session.execute(
        select(CandidateClip)
        .where(CandidateClip.candidate_set_id == candidate_set_id)
        .order_by(CandidateClip.rank_no.asc())
    )
    return list(result.scalars().all())


async def get_source_video_proxy_artifacts(session: AsyncSession, *, source_video_id: UUID) -> tuple[ArtifactObject, ArtifactObject | None]:
    try:
        proxy_artifact = await get_source_video_artifact(
            session,
            source_video_id=source_video_id,
            role=SourceVideoArtifactRole.proxy_video,
        )
    except AppError as exc:
        if exc.code != "artifact_not_found":
            raise
        proxy_artifact = await get_preferred_video_artifact(session, source_video_id=source_video_id)

    thumbnails_artifact: ArtifactObject | None = None
    try:
        thumbnails_artifact = await get_source_video_artifact(
            session,
            source_video_id=source_video_id,
            role=SourceVideoArtifactRole.thumbnails,
        )
    except AppError as exc:
        if exc.code != "artifact_not_found":
            raise
    return proxy_artifact, thumbnails_artifact


def build_transcript_excerpt(segments: list[TranscriptSegment], *, start_ms: int, end_ms: int) -> str:
    selected = [
        segment.text.strip()
        for segment in segments
        if windows_overlap(
            start_ms=start_ms,
            end_ms=end_ms,
            other_start_ms=segment.start_ms,
            other_end_ms=segment.end_ms,
        )
    ]
    if not selected:
        return ""
    return truncate_excerpt(" ".join(selected))


async def create_neutral_preview_artifact(
    session: AsyncSession,
    *,
    shortlist_id: UUID,
    rank_no: int,
    source_video_id: UUID,
    job_id: UUID | None,
    start_ms: int,
    end_ms: int,
    transcript_excerpt: str,
) -> ArtifactObject:
    proxy_artifact, thumbnails_artifact = await get_source_video_proxy_artifacts(session, source_video_id=source_video_id)
    payload = {
        "artifact_type": "neutral_preview_excerpt",
        "version": PROOF_PROTOCOL_VERSION,
        "source_video_id": str(source_video_id),
        "job_id": str(job_id) if job_id is not None else None,
        "proof_shortlist_id": str(shortlist_id),
        "rank_no": rank_no,
        "preview_window": {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "duration_ms": end_ms - start_ms,
        },
        "proxy_video": {
            "artifact_id": str(proxy_artifact.id),
            "storage_key": proxy_artifact.storage_key,
            "mime_type": proxy_artifact.mime_type,
        },
        "thumbnails": (
            {
                "artifact_id": str(thumbnails_artifact.id),
                "storage_key": thumbnails_artifact.storage_key,
            }
            if thumbnails_artifact is not None
            else None
        ),
        "transcript_excerpt": transcript_excerpt,
        "render_policy": {
            "container": "neutral_v1",
            "branded_styling": False,
            "system_of_origin_visible": False,
        },
    }
    return await write_json_artifact(
        session,
        storage_key=f"proof-harness/shortlists/{shortlist_id}/previews/{rank_no}.json",
        payload=payload,
        metadata_jsonb={
            "artifact_type": "neutral_preview_excerpt",
            "proof_shortlist_id": str(shortlist_id),
            "rank_no": rank_no,
        },
    )


async def create_shortlist_manifest_artifact(session: AsyncSession, *, shortlist: ProofShortlist) -> ArtifactObject:
    candidates = await list_proof_shortlist_candidates(session, proof_shortlist_id=shortlist.id)
    payload = {
        "artifact_type": "proof_shortlist_manifest",
        "version": PROOF_PROTOCOL_VERSION,
        "proof_shortlist_id": str(shortlist.id),
        "source_video_id": str(shortlist.source_video_id),
        "job_id": str(shortlist.job_id) if shortlist.job_id is not None else None,
        "eval_set_id": str(shortlist.eval_set_id) if shortlist.eval_set_id is not None else None,
        "system_name": shortlist.system_name.value,
        "version_no": shortlist.version_no,
        "candidate_count": shortlist.candidate_count,
        "generation_time_seconds": shortlist.generation_time_seconds,
        "metadata_jsonb": shortlist.metadata_jsonb,
        "candidates": [
            {
                "proof_shortlist_candidate_id": str(candidate.id),
                "rank_no": candidate.rank_no,
                "start_ms": candidate.start_ms,
                "end_ms": candidate.end_ms,
                "transcript_excerpt": candidate.transcript_excerpt,
                "preview_artifact_id": str(candidate.preview_artifact_id) if candidate.preview_artifact_id is not None else None,
            }
            for candidate in candidates
        ],
    }
    return await write_json_artifact(
        session,
        storage_key=f"proof-harness/shortlists/{shortlist.id}/manifest.json",
        payload=payload,
        metadata_jsonb={
            "artifact_type": "proof_shortlist_manifest",
            "proof_shortlist_id": str(shortlist.id),
            "system_name": shortlist.system_name.value,
        },
    )


async def get_next_shortlist_version(
    session: AsyncSession,
    *,
    source_video_id: UUID,
    system_name: ProofShortlistSystem,
) -> int:
    current_max = await session.scalar(
        select(func.max(ProofShortlist.version_no)).where(
            ProofShortlist.source_video_id == source_video_id,
            ProofShortlist.system_name == system_name,
        )
    )
    return int(current_max or 0) + 1


async def mark_existing_shortlists_not_current(
    session: AsyncSession,
    *,
    source_video_id: UUID,
    system_name: ProofShortlistSystem,
) -> None:
    await session.execute(
        update(ProofShortlist)
        .where(
            ProofShortlist.source_video_id == source_video_id,
            ProofShortlist.system_name == system_name,
            ProofShortlist.is_current.is_(True),
        )
        .values(is_current=False)
    )


async def list_proof_shortlist_candidates(
    session: AsyncSession,
    *,
    proof_shortlist_id: UUID,
) -> list[ProofShortlistCandidate]:
    result = await session.execute(
        select(ProofShortlistCandidate)
        .where(ProofShortlistCandidate.proof_shortlist_id == proof_shortlist_id)
        .order_by(ProofShortlistCandidate.rank_no.asc())
    )
    return list(result.scalars().all())


async def load_artifact_map(session: AsyncSession, artifact_ids: list[UUID]) -> dict[UUID, ArtifactObject]:
    if not artifact_ids:
        return {}
    result = await session.execute(select(ArtifactObject).where(ArtifactObject.id.in_(artifact_ids)))
    return {artifact.id: artifact for artifact in result.scalars().all()}


async def build_proof_shortlist_payload(session: AsyncSession, shortlist: ProofShortlist) -> dict:
    candidates = await list_proof_shortlist_candidates(session, proof_shortlist_id=shortlist.id)
    artifact_map = await load_artifact_map(
        session,
        artifact_ids=[
            artifact_id
            for artifact_id in [
                shortlist.artifact_id,
                *[candidate.preview_artifact_id for candidate in candidates if candidate.preview_artifact_id is not None],
            ]
            if artifact_id is not None
        ],
    )
    shortlist_artifact = artifact_map.get(shortlist.artifact_id) if shortlist.artifact_id is not None else None
    return {
        "id": shortlist.id,
        "source_video_id": shortlist.source_video_id,
        "job_id": shortlist.job_id,
        "eval_set_id": shortlist.eval_set_id,
        "system_name": shortlist.system_name,
        "version_no": shortlist.version_no,
        "is_current": shortlist.is_current,
        "candidate_count": shortlist.candidate_count,
        "generation_time_seconds": shortlist.generation_time_seconds,
        "actor_ref": shortlist.actor_ref,
        "prompt_version": shortlist.prompt_version,
        "scoring_policy_version": shortlist.scoring_policy_version,
        "metadata_jsonb": shortlist.metadata_jsonb,
        "artifact_id": shortlist.artifact_id,
        "artifact_storage_key": shortlist_artifact.storage_key if shortlist_artifact is not None else None,
        "created_at": shortlist.created_at,
        "candidates": [
            {
                "id": candidate.id,
                "rank_no": candidate.rank_no,
                "start_ms": candidate.start_ms,
                "end_ms": candidate.end_ms,
                "transcript_excerpt": candidate.transcript_excerpt,
                "duplicate_group": candidate.duplicate_group,
                "topic_cluster": candidate.topic_cluster,
                "length_bucket": candidate.length_bucket,
                "rationale_jsonb": candidate.rationale_jsonb,
                "metadata_jsonb": candidate.metadata_jsonb,
                "preview_artifact_id": candidate.preview_artifact_id,
                "preview_storage_key": (
                    artifact_map[candidate.preview_artifact_id].storage_key
                    if candidate.preview_artifact_id in artifact_map
                    else None
                ),
                "created_at": candidate.created_at,
            }
            for candidate in candidates
        ],
    }


def build_blinded_review_candidate_payloads(shortlist_payload: dict) -> list[dict]:
    return [
        {
            "id": candidate["id"],
            "rank_no": candidate["rank_no"],
            "start_ms": candidate["start_ms"],
            "end_ms": candidate["end_ms"],
            "transcript_excerpt": candidate["transcript_excerpt"],
            "preview_artifact_id": candidate["preview_artifact_id"],
            "preview_storage_key": candidate["preview_storage_key"],
        }
        for candidate in shortlist_payload["candidates"]
    ]


async def build_review_session_payload(session: AsyncSession, review_session: ProofReviewSession) -> dict:
    await session.refresh(review_session)
    batches_result = await session.execute(
        select(ProofReviewBatch)
        .where(ProofReviewBatch.proof_review_session_id == review_session.id)
        .order_by(ProofReviewBatch.display_order.asc(), ProofReviewBatch.batch_code.asc())
    )
    batches = list(batches_result.scalars().all())

    batch_payloads = []
    for batch in batches:
        shortlist = await session.get(ProofShortlist, batch.proof_shortlist_id)
        if shortlist is None:
            raise AppError(code="proof_shortlist_not_found", message="Proof shortlist not found.", http_status=404)
        shortlist_payload = await build_proof_shortlist_payload(session, shortlist)
        batch_payloads.append(
            {
                "batch_code": batch.batch_code,
                "display_order": batch.display_order,
                "elapsed_review_seconds": batch.elapsed_review_seconds,
                "candidates": build_blinded_review_candidate_payloads(shortlist_payload),
            }
        )

    return {
        "id": review_session.id,
        "eval_set_id": review_session.eval_set_id,
        "source_video_id": review_session.source_video_id,
        "status": review_session.status,
        "time_budget_seconds": review_session.time_budget_seconds,
        "protocol_version": review_session.protocol_version,
        "batches": batch_payloads,
        "created_at": review_session.created_at,
        "updated_at": review_session.updated_at,
    }


async def get_existing_primary_review_session(
    session: AsyncSession,
    *,
    eval_set_id: UUID,
    source_video_id: UUID,
) -> ProofReviewSession | None:
    result = await session.execute(
        select(ProofReviewSession)
        .where(
            ProofReviewSession.eval_set_id == eval_set_id,
            ProofReviewSession.source_video_id == source_video_id,
            ProofReviewSession.is_audit.is_(False),
        )
        .order_by(ProofReviewSession.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def create_engine_proof_shortlist(
    session: AsyncSession,
    *,
    job_id: UUID,
    actor_ref: str,
    eval_set_id: UUID | None = None,
) -> ProofShortlist:
    job = await session.get(Job, job_id)
    if job is None:
        raise AppError(code="job_not_found", message="Job not found.", http_status=404)
    if eval_set_id is not None:
        await ensure_eval_set_membership(session, eval_set_id=eval_set_id, source_video_id=job.source_video_id)

    candidate_set = await get_current_candidate_set(session, job_id=job.id)
    candidates = await list_current_candidate_clips(session, candidate_set_id=candidate_set.id)
    if len(candidates) < PROOF_SHORTLIST_SIZE:
        raise AppError(
            code="insufficient_engine_candidates",
            message=f"Engine shortlist requires at least {PROOF_SHORTLIST_SIZE} ranked candidates.",
            http_status=409,
        )

    revision = await get_current_transcript_revision(session, job_id=job.id)
    segments = await list_transcript_segments(session, transcript_revision_id=revision.id)

    await mark_existing_shortlists_not_current(
        session,
        source_video_id=job.source_video_id,
        system_name=ProofShortlistSystem.engine,
    )
    shortlist = ProofShortlist(
        source_video_id=job.source_video_id,
        job_id=job.id,
        eval_set_id=eval_set_id,
        system_name=ProofShortlistSystem.engine,
        version_no=await get_next_shortlist_version(
            session,
            source_video_id=job.source_video_id,
            system_name=ProofShortlistSystem.engine,
        ),
        is_current=True,
        candidate_count=PROOF_SHORTLIST_SIZE,
        source_candidate_set_id=candidate_set.id,
        actor_ref=actor_ref,
        prompt_version=job.prompt_version,
        scoring_policy_version=job.scoring_policy_version,
        metadata_jsonb={"proof_type": "engine_snapshot"},
    )
    session.add(shortlist)
    await session.flush()

    for rank_no, candidate in enumerate(candidates[:PROOF_SHORTLIST_SIZE], start=1):
        transcript_excerpt = build_transcript_excerpt(segments, start_ms=candidate.start_ms, end_ms=candidate.end_ms)
        preview_artifact = await create_neutral_preview_artifact(
            session,
            shortlist_id=shortlist.id,
            rank_no=rank_no,
            source_video_id=job.source_video_id,
            job_id=job.id,
            start_ms=candidate.start_ms,
            end_ms=candidate.end_ms,
            transcript_excerpt=transcript_excerpt,
        )
        session.add(
            ProofShortlistCandidate(
                proof_shortlist_id=shortlist.id,
                source_candidate_clip_id=candidate.id,
                rank_no=rank_no,
                start_ms=candidate.start_ms,
                end_ms=candidate.end_ms,
                transcript_excerpt=transcript_excerpt,
                duplicate_group=candidate.duplicate_group,
                topic_cluster=candidate.topic_cluster,
                length_bucket=candidate.length_bucket,
                rationale_jsonb=candidate.rationale_jsonb,
                metadata_jsonb={"final_score": float(candidate.final_score)},
                preview_artifact_id=preview_artifact.id,
            )
        )
    await session.flush()
    shortlist.artifact_id = (await create_shortlist_manifest_artifact(session, shortlist=shortlist)).id
    await session.flush()
    return shortlist


async def import_baseline_shortlist(
    session: AsyncSession,
    *,
    source_video_id: UUID,
    system_name: ProofShortlistSystem,
    actor_ref: str,
    candidates: list[dict],
    eval_set_id: UUID | None = None,
    generation_time_seconds: int | None = None,
    metadata_jsonb: dict | None = None,
) -> ProofShortlist:
    if system_name == ProofShortlistSystem.engine:
        raise AppError(code="validation_error", message="Baseline import only accepts manual or vizard.", http_status=422)
    if len(candidates) != PROOF_SHORTLIST_SIZE:
        raise AppError(
            code="validation_error",
            message=f"Exactly {PROOF_SHORTLIST_SIZE} baseline candidates are required.",
            http_status=422,
        )
    if eval_set_id is not None:
        await ensure_eval_set_membership(session, eval_set_id=eval_set_id, source_video_id=source_video_id)

    job = await get_latest_transcribed_job_for_source_video(session, source_video_id=source_video_id)
    revision = await get_current_transcript_revision(session, job_id=job.id)
    segments = await list_transcript_segments(session, transcript_revision_id=revision.id)

    await mark_existing_shortlists_not_current(
        session,
        source_video_id=source_video_id,
        system_name=system_name,
    )
    shortlist = ProofShortlist(
        source_video_id=source_video_id,
        job_id=job.id,
        eval_set_id=eval_set_id,
        system_name=system_name,
        version_no=await get_next_shortlist_version(session, source_video_id=source_video_id, system_name=system_name),
        is_current=True,
        candidate_count=PROOF_SHORTLIST_SIZE,
        generation_time_seconds=generation_time_seconds,
        actor_ref=actor_ref,
        prompt_version=job.prompt_version,
        scoring_policy_version=job.scoring_policy_version,
        metadata_jsonb={"proof_type": "baseline_import"} | (metadata_jsonb or {}),
    )
    session.add(shortlist)
    await session.flush()

    for rank_no, candidate in enumerate(candidates, start=1):
        transcript_excerpt = build_transcript_excerpt(segments, start_ms=candidate["start_ms"], end_ms=candidate["end_ms"])
        preview_artifact = await create_neutral_preview_artifact(
            session,
            shortlist_id=shortlist.id,
            rank_no=rank_no,
            source_video_id=source_video_id,
            job_id=job.id,
            start_ms=candidate["start_ms"],
            end_ms=candidate["end_ms"],
            transcript_excerpt=transcript_excerpt,
        )
        session.add(
            ProofShortlistCandidate(
                proof_shortlist_id=shortlist.id,
                rank_no=rank_no,
                start_ms=candidate["start_ms"],
                end_ms=candidate["end_ms"],
                transcript_excerpt=transcript_excerpt,
                duplicate_group=candidate.get("duplicate_group"),
                topic_cluster=candidate.get("topic_cluster"),
                length_bucket=candidate.get("length_bucket"),
                rationale_jsonb=candidate.get("rationale_jsonb", {}),
                metadata_jsonb=candidate.get("metadata_jsonb", {}),
                preview_artifact_id=preview_artifact.id,
            )
        )
    await session.flush()
    shortlist.artifact_id = (await create_shortlist_manifest_artifact(session, shortlist=shortlist)).id
    await session.flush()
    return shortlist


async def list_current_proof_shortlists(session: AsyncSession, *, source_video_id: UUID) -> list[ProofShortlist]:
    result = await session.execute(
        select(ProofShortlist)
        .where(ProofShortlist.source_video_id == source_video_id, ProofShortlist.is_current.is_(True))
        .order_by(ProofShortlist.system_name.asc(), ProofShortlist.created_at.desc())
    )
    return list(result.scalars().all())


async def get_proof_review_session(session: AsyncSession, *, proof_review_session_id: UUID) -> ProofReviewSession:
    review_session = await session.get(ProofReviewSession, proof_review_session_id)
    if review_session is None:
        raise AppError(code="proof_review_session_not_found", message="Proof review session not found.", http_status=404)
    return review_session


async def get_current_shortlists_for_review(session: AsyncSession, *, source_video_id: UUID) -> dict[ProofShortlistSystem, ProofShortlist]:
    result = await session.execute(
        select(ProofShortlist)
        .where(ProofShortlist.source_video_id == source_video_id, ProofShortlist.is_current.is_(True))
        .order_by(ProofShortlist.created_at.desc())
    )
    latest_by_system: dict[ProofShortlistSystem, ProofShortlist] = {}
    for shortlist in result.scalars().all():
        latest_by_system.setdefault(shortlist.system_name, shortlist)
    required_systems = {
        ProofShortlistSystem.engine,
        ProofShortlistSystem.manual,
        ProofShortlistSystem.vizard,
    }
    if set(latest_by_system) != required_systems:
        missing = ", ".join(sorted(system.value for system in required_systems - set(latest_by_system)))
        raise AppError(
            code="proof_shortlists_incomplete",
            message=f"Current proof shortlists are missing for: {missing}.",
            http_status=409,
        )
    return latest_by_system


async def assert_shortlist_candidate_count(session: AsyncSession, *, shortlist_id: UUID) -> None:
    candidate_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ProofShortlistCandidate)
            .where(ProofShortlistCandidate.proof_shortlist_id == shortlist_id)
        )
        or 0
    )
    if candidate_count != PROOF_SHORTLIST_SIZE:
        raise AppError(
            code="proof_shortlist_invalid",
            message=f"Proof shortlist must contain exactly {PROOF_SHORTLIST_SIZE} candidates.",
            http_status=409,
        )


async def create_review_session(
    session: AsyncSession,
    *,
    eval_set_id: UUID,
    source_video_id: UUID,
    reviewer_actor_ref: str,
    is_audit: bool = False,
    time_budget_seconds: int = PROOF_REVIEW_TIME_BUDGET_SECONDS,
) -> ProofReviewSession:
    await ensure_eval_set_membership(session, eval_set_id=eval_set_id, source_video_id=source_video_id)
    shortlists = await get_current_shortlists_for_review(session, source_video_id=source_video_id)
    for shortlist in shortlists.values():
        await assert_shortlist_candidate_count(session, shortlist_id=shortlist.id)

    primary_review_session = await get_existing_primary_review_session(
        session,
        eval_set_id=eval_set_id,
        source_video_id=source_video_id,
    )
    if not is_audit and primary_review_session is not None:
        raise AppError(
            code="proof_primary_review_exists",
            message="A primary review session already exists for this source video and eval set.",
            http_status=409,
        )
    if is_audit:
        if primary_review_session is None or primary_review_session.status != ProofReviewStatus.completed:
            raise AppError(
                code="proof_audit_requires_completed_primary_review",
                message="Audit review requires an existing completed primary review session.",
                http_status=409,
            )
        if primary_review_session.reviewer_actor_ref == reviewer_actor_ref:
            raise AppError(
                code="proof_audit_reviewer_conflict",
                message="Audit reviewer must be different from the primary reviewer.",
                http_status=409,
            )

    review_session = ProofReviewSession(
        eval_set_id=eval_set_id,
        source_video_id=source_video_id,
        reviewer_actor_ref=reviewer_actor_ref,
        status=ProofReviewStatus.in_progress,
        time_budget_seconds=time_budget_seconds,
        is_audit=is_audit,
        protocol_version=PROOF_PROTOCOL_VERSION,
    )
    session.add(review_session)
    await session.flush()

    systems = list(shortlists.keys())
    randomized_systems = random.sample(systems, k=len(systems))
    for display_order, (batch_code, system_name) in enumerate(zip(PROOF_BATCH_CODES, randomized_systems, strict=True), start=1):
        session.add(
            ProofReviewBatch(
                proof_review_session_id=review_session.id,
                batch_code=batch_code,
                proof_shortlist_id=shortlists[system_name].id,
                system_name=system_name,
                display_order=display_order,
            )
        )
    await session.flush()
    return review_session


async def get_session_batch_map(
    session: AsyncSession,
    *,
    proof_review_session_id: UUID,
) -> dict[str, ProofReviewBatch]:
    result = await session.execute(
        select(ProofReviewBatch).where(ProofReviewBatch.proof_review_session_id == proof_review_session_id)
    )
    batch_map = {batch.batch_code: batch for batch in result.scalars().all()}
    if set(batch_map) != set(PROOF_BATCH_CODES):
        raise AppError(code="proof_review_session_invalid", message="Review session batches are incomplete.", http_status=409)
    return batch_map


async def get_shortlist_candidate_map(
    session: AsyncSession,
    *,
    shortlist_id: UUID,
) -> dict[UUID, ProofShortlistCandidate]:
    candidates = await list_proof_shortlist_candidates(session, proof_shortlist_id=shortlist_id)
    return {candidate.id: candidate for candidate in candidates}


async def complete_review_session(
    session: AsyncSession,
    *,
    proof_review_session_id: UUID,
    reviewer_actor_ref: str,
    batch_reviews: list[dict],
    batch_preference_ranking: list[str],
) -> ProofReviewSession:
    review_session = await get_proof_review_session(session, proof_review_session_id=proof_review_session_id)
    if review_session.reviewer_actor_ref != reviewer_actor_ref:
        raise AppError(code="forbidden", message="Review session belongs to a different reviewer.", http_status=403)
    if review_session.status != ProofReviewStatus.in_progress:
        raise AppError(code="state_conflict", message="Review session is already completed.", http_status=409)

    existing_decision_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ProofReviewDecision)
            .where(ProofReviewDecision.proof_review_session_id == proof_review_session_id)
        )
        or 0
    )
    if existing_decision_count:
        raise AppError(code="state_conflict", message="Review decisions already exist for this session.", http_status=409)

    batch_map = await get_session_batch_map(session, proof_review_session_id=proof_review_session_id)
    if list(batch_preference_ranking) != batch_preference_ranking or sorted(batch_preference_ranking) != sorted(PROOF_BATCH_CODES):
        raise AppError(code="validation_error", message="Invalid batch preference ranking.", http_status=422)

    for batch_payload in batch_reviews:
        batch_code = batch_payload["batch_code"]
        if batch_code not in batch_map:
            raise AppError(code="validation_error", message=f"Unknown batch code {batch_code}.", http_status=422)
        batch = batch_map[batch_code]
        candidate_map = await get_shortlist_candidate_map(session, shortlist_id=batch.proof_shortlist_id)
        submitted_candidate_ids = {UUID(str(item["proof_shortlist_candidate_id"])) for item in batch_payload["candidate_decisions"]}
        if submitted_candidate_ids != set(candidate_map):
            raise AppError(
                code="validation_error",
                message=f"Batch {batch_code} must include decisions for every shortlisted candidate exactly once.",
                http_status=422,
            )
        batch.elapsed_review_seconds = int(batch_payload["elapsed_review_seconds"])
        for decision_payload in batch_payload["candidate_decisions"]:
            candidate_id = UUID(str(decision_payload["proof_shortlist_candidate_id"]))
            if candidate_id not in candidate_map:
                raise AppError(code="validation_error", message="Decision references an unknown candidate.", http_status=422)
            session.add(
                ProofReviewDecision(
                    proof_review_session_id=proof_review_session_id,
                    batch_code=batch_code,
                    proof_shortlist_candidate_id=candidate_id,
                    decision=ProofDecisionValue(decision_payload["decision"]),
                    reject_reason_code=(
                        ProofRejectReasonCode(decision_payload["reject_reason_code"])
                        if decision_payload.get("reject_reason_code") is not None
                        else None
                    ),
                    rationale_helpful=bool(decision_payload["rationale_helpful"]),
                    notes=decision_payload.get("notes"),
                )
            )

    for rank_no, batch_code in enumerate(batch_preference_ranking, start=1):
        session.add(
            ProofReviewPreference(
                proof_review_session_id=proof_review_session_id,
                rank_no=rank_no,
                batch_code=batch_code,
            )
        )

    review_session.status = ProofReviewStatus.completed
    await session.flush()
    return review_session


def summarize_system_review_metrics(
    *,
    decisions: list[ProofReviewDecision],
    elapsed_review_seconds: int | None,
    batch_preference_rank: int,
) -> SystemReviewMetrics:
    approved_decisions = [decision for decision in decisions if decision.decision == ProofDecisionValue.approve]
    rejected_decisions = [decision for decision in decisions if decision.decision == ProofDecisionValue.reject]
    approved_clips = len(approved_decisions)
    junk_rejects = sum(1 for decision in rejected_decisions if decision.reject_reason_code in JUNK_REJECT_REASONS)
    duplicate_rejects = sum(
        1 for decision in rejected_decisions if decision.reject_reason_code == ProofRejectReasonCode.duplicate_angle
    )
    approved_rationale_helpful_count = sum(1 for decision in approved_decisions if decision.rationale_helpful)
    rationale_helpful_rate = (
        round(approved_rationale_helpful_count / approved_clips, 4) if approved_clips else 0.0
    )
    return SystemReviewMetrics(
        approved_clips=approved_clips,
        junk_rate=round(junk_rejects / PROOF_SHORTLIST_SIZE, 4),
        duplicate_angle_rate=round(duplicate_rejects / PROOF_SHORTLIST_SIZE, 4),
        reviewer_time_seconds=float(elapsed_review_seconds or 0),
        rationale_helpful_rate_on_approved=rationale_helpful_rate,
        batch_preference_rank=batch_preference_rank,
        batch_preference_win=1.0 if batch_preference_rank == 1 else 0.0,
        approved_rationale_helpful_count=approved_rationale_helpful_count,
    )


def median_metric(values: list[float]) -> float:
    return round(float(median(values)), 4) if values else 0.0


def build_gate_payload(
    *,
    source_count: int,
    approved_clip_win_source_count: int,
    duplicate_rate_better_source_count: int,
    batch_preference_win_source_count: int,
    system_aggregate: dict[str, dict[str, float]],
    engine_rationale_helpful_rate_on_approved: float,
    overfitting_payload: dict,
) -> dict:
    evaluable = source_count == 8
    median_engine_junk = system_aggregate[ProofShortlistSystem.engine.value]["median_junk_rate"]
    median_vizard_junk = system_aggregate[ProofShortlistSystem.vizard.value]["median_junk_rate"]
    median_engine_time = system_aggregate[ProofShortlistSystem.engine.value]["median_reviewer_time_seconds"]
    median_manual_time = system_aggregate[ProofShortlistSystem.manual.value]["median_reviewer_time_seconds"]
    median_vizard_time = system_aggregate[ProofShortlistSystem.vizard.value]["median_reviewer_time_seconds"]

    gates = {
        "source_count_is_eight": {
            "pass": source_count == 8,
            "actual": source_count,
            "threshold": 8,
        },
        "engine_beats_both_baselines_on_approved_clips": {
            "pass": evaluable and approved_clip_win_source_count >= 5,
            "actual": approved_clip_win_source_count,
            "threshold": 5,
        },
        "engine_median_junk_rate_at_least_25_percent_lower_than_vizard": {
            "pass": evaluable and median_engine_junk <= round(median_vizard_junk * 0.75, 4),
            "actual": median_engine_junk,
            "threshold": round(median_vizard_junk * 0.75, 4),
        },
        "engine_duplicate_angle_rate_lower_than_both_baselines": {
            "pass": evaluable and duplicate_rate_better_source_count >= 6,
            "actual": duplicate_rate_better_source_count,
            "threshold": 6,
        },
        "engine_median_reviewer_time_faster_than_manual": {
            "pass": evaluable and median_engine_time < median_manual_time,
            "actual": median_engine_time,
            "threshold": median_manual_time,
        },
        "engine_median_reviewer_time_within_10_percent_of_vizard": {
            "pass": evaluable and median_engine_time <= round(median_vizard_time * 1.1, 4),
            "actual": median_engine_time,
            "threshold": round(median_vizard_time * 1.1, 4),
        },
        "engine_rationale_helpful_rate_on_approved_clips": {
            "pass": evaluable and engine_rationale_helpful_rate_on_approved >= 0.6,
            "actual": engine_rationale_helpful_rate_on_approved,
            "threshold": 0.6,
        },
        "reviewer_ranks_engine_batch_best": {
            "pass": evaluable and batch_preference_win_source_count >= 5,
            "actual": batch_preference_win_source_count,
            "threshold": 5,
        },
        "overfitting_rule": overfitting_payload,
    }
    return {
        "evaluable": evaluable and overfitting_payload.get("pass") is not None,
        "overall_pass": evaluable and all(item["pass"] for key, item in gates.items() if key != "overfitting_rule") and bool(overfitting_payload.get("pass")),
        "gates": gates,
    }


async def build_comparison_payload(
    session: AsyncSession,
    *,
    eval_set_id: UUID,
) -> tuple[dict, list[tuple[UUID, ProofShortlistSystem, str, float]]]:
    eval_set = await get_eval_set(session, eval_set_id=eval_set_id)
    if eval_set.status != EvalSetStatus.frozen:
        raise AppError(code="eval_set_not_frozen", message="Proof comparison requires a frozen eval set.", http_status=409)

    members = await list_eval_set_members(session, eval_set_id=eval_set_id)
    if not members:
        raise AppError(code="eval_set_empty", message="Eval set must contain at least one source video.", http_status=409)

    comparison_rows: list[tuple[UUID, ProofShortlistSystem, str, float]] = []
    sources_payload: list[dict] = []
    source_count = 0
    approved_clip_win_source_count = 0
    duplicate_rate_better_source_count = 0
    batch_preference_win_source_count = 0
    engine_win_channels: set[str] = set()
    engine_win_patterns: set[str] = set()
    channel_series_values = {meta for meta in [member.metadata_jsonb.get("channel_series") for member in members] if meta}
    content_pattern_values = {meta for meta in [member.metadata_jsonb.get("content_pattern") for member in members] if meta}

    system_metric_buckets: dict[ProofShortlistSystem, dict[str, list[float]]] = {
        system: {
            "approved_clips": [],
            "junk_rate": [],
            "duplicate_angle_rate": [],
            "reviewer_time_seconds": [],
            "rationale_helpful_rate_on_approved": [],
            "batch_preference_rank": [],
            "batch_preference_win": [],
        }
        for system in ProofShortlistSystem
    }
    engine_approved_total = 0
    engine_approved_helpful_total = 0

    for member in members:
        source_count += 1
        session_result = await session.execute(
            select(ProofReviewSession)
            .where(
                ProofReviewSession.eval_set_id == eval_set_id,
                ProofReviewSession.source_video_id == member.source_video_id,
                ProofReviewSession.is_audit.is_(False),
                ProofReviewSession.status == ProofReviewStatus.completed,
            )
            .order_by(ProofReviewSession.created_at.desc())
            .limit(1)
        )
        review_session = session_result.scalars().first()
        if review_session is None:
            raise AppError(
                code="proof_review_missing",
                message="Each eval set member requires one completed non-audit proof review session.",
                http_status=409,
            )

        batches = (await session.execute(
            select(ProofReviewBatch)
            .where(ProofReviewBatch.proof_review_session_id == review_session.id)
            .order_by(ProofReviewBatch.display_order.asc())
        )).scalars().all()
        preferences = (await session.execute(
            select(ProofReviewPreference)
            .where(ProofReviewPreference.proof_review_session_id == review_session.id)
            .order_by(ProofReviewPreference.rank_no.asc())
        )).scalars().all()
        preference_by_batch = {preference.batch_code: preference.rank_no for preference in preferences}

        batch_metrics_by_system: dict[ProofShortlistSystem, SystemReviewMetrics] = {}
        system_batch_codes: dict[ProofShortlistSystem, str] = {}
        for batch in batches:
            decisions = (await session.execute(
                select(ProofReviewDecision)
                .where(
                    ProofReviewDecision.proof_review_session_id == review_session.id,
                    ProofReviewDecision.batch_code == batch.batch_code,
                )
                .order_by(ProofReviewDecision.created_at.asc())
            )).scalars().all()
            metrics = summarize_system_review_metrics(
                decisions=list(decisions),
                elapsed_review_seconds=batch.elapsed_review_seconds,
                batch_preference_rank=preference_by_batch[batch.batch_code],
            )
            batch_metrics_by_system[batch.system_name] = metrics
            system_batch_codes[batch.system_name] = batch.batch_code
            comparison_rows.extend(
                [
                    (member.source_video_id, batch.system_name, "approved_clips", float(metrics.approved_clips)),
                    (member.source_video_id, batch.system_name, "junk_rate", metrics.junk_rate),
                    (member.source_video_id, batch.system_name, "duplicate_angle_rate", metrics.duplicate_angle_rate),
                    (member.source_video_id, batch.system_name, "reviewer_time_seconds", metrics.reviewer_time_seconds),
                    (
                        member.source_video_id,
                        batch.system_name,
                        "rationale_helpful_rate_on_approved",
                        metrics.rationale_helpful_rate_on_approved,
                    ),
                    (member.source_video_id, batch.system_name, "batch_preference_rank", float(metrics.batch_preference_rank)),
                    (member.source_video_id, batch.system_name, "batch_preference_win", metrics.batch_preference_win),
                ]
            )

        if set(batch_metrics_by_system) != {ProofShortlistSystem.engine, ProofShortlistSystem.manual, ProofShortlistSystem.vizard}:
            raise AppError(code="proof_review_invalid", message="Review session does not cover all three systems.", http_status=409)

        engine_metrics = batch_metrics_by_system[ProofShortlistSystem.engine]
        manual_metrics = batch_metrics_by_system[ProofShortlistSystem.manual]
        vizard_metrics = batch_metrics_by_system[ProofShortlistSystem.vizard]
        if engine_metrics.approved_clips > manual_metrics.approved_clips and engine_metrics.approved_clips > vizard_metrics.approved_clips:
            approved_clip_win_source_count += 1
            channel_series = member.metadata_jsonb.get("channel_series")
            content_pattern = member.metadata_jsonb.get("content_pattern")
            if channel_series:
                engine_win_channels.add(channel_series)
            if content_pattern:
                engine_win_patterns.add(content_pattern)
        if (
            engine_metrics.duplicate_angle_rate < manual_metrics.duplicate_angle_rate
            and engine_metrics.duplicate_angle_rate < vizard_metrics.duplicate_angle_rate
        ):
            duplicate_rate_better_source_count += 1
        if engine_metrics.batch_preference_rank == 1:
            batch_preference_win_source_count += 1

        engine_approved_total += engine_metrics.approved_clips
        engine_approved_helpful_total += engine_metrics.approved_rationale_helpful_count
        for system_name, metrics in batch_metrics_by_system.items():
            bucket = system_metric_buckets[system_name]
            bucket["approved_clips"].append(float(metrics.approved_clips))
            bucket["junk_rate"].append(metrics.junk_rate)
            bucket["duplicate_angle_rate"].append(metrics.duplicate_angle_rate)
            bucket["reviewer_time_seconds"].append(metrics.reviewer_time_seconds)
            bucket["rationale_helpful_rate_on_approved"].append(metrics.rationale_helpful_rate_on_approved)
            bucket["batch_preference_rank"].append(float(metrics.batch_preference_rank))
            bucket["batch_preference_win"].append(metrics.batch_preference_win)

        sources_payload.append(
            {
                "source_video_id": str(member.source_video_id),
                "review_session_id": str(review_session.id),
                "member_metadata_jsonb": member.metadata_jsonb,
                "systems": {
                    system.value: {
                        "batch_code": system_batch_codes[system],
                        "approved_clips": batch_metrics_by_system[system].approved_clips,
                        "junk_rate": batch_metrics_by_system[system].junk_rate,
                        "duplicate_angle_rate": batch_metrics_by_system[system].duplicate_angle_rate,
                        "reviewer_time_seconds": batch_metrics_by_system[system].reviewer_time_seconds,
                        "rationale_helpful_rate_on_approved": batch_metrics_by_system[system].rationale_helpful_rate_on_approved,
                        "batch_preference_rank": batch_metrics_by_system[system].batch_preference_rank,
                        "batch_preference_win": batch_metrics_by_system[system].batch_preference_win,
                    }
                    for system in ProofShortlistSystem
                },
            }
        )

    system_aggregate = {
        system.value: {
            "median_approved_clips_per_video": median_metric(buckets["approved_clips"]),
            "median_junk_rate": median_metric(buckets["junk_rate"]),
            "median_duplicate_angle_rate": median_metric(buckets["duplicate_angle_rate"]),
            "median_reviewer_time_seconds": median_metric(buckets["reviewer_time_seconds"]),
            "median_rationale_helpful_rate_on_approved": median_metric(buckets["rationale_helpful_rate_on_approved"]),
            "median_batch_preference_rank": median_metric(buckets["batch_preference_rank"]),
            "batch_preference_wins": int(sum(buckets["batch_preference_win"])),
        }
        for system, buckets in system_metric_buckets.items()
    }
    engine_rationale_helpful_rate_on_approved = round(
        engine_approved_helpful_total / engine_approved_total,
        4,
    ) if engine_approved_total else 0.0

    overfitting_evaluable = bool(channel_series_values) and bool(content_pattern_values)
    overfitting_pass = None
    if overfitting_evaluable:
        overfitting_pass = (
            len(channel_series_values) >= 3
            and len(content_pattern_values) >= 2
            and len(engine_win_channels) >= 2
            and len(engine_win_patterns) >= 2
        )
    overfitting_payload = {
        "pass": overfitting_pass,
        "evaluable": overfitting_evaluable,
        "holdout_channel_series_count": len(channel_series_values),
        "holdout_content_pattern_count": len(content_pattern_values),
        "engine_win_channel_series_count": len(engine_win_channels),
        "engine_win_content_pattern_count": len(engine_win_patterns),
    }

    gates = build_gate_payload(
        source_count=source_count,
        approved_clip_win_source_count=approved_clip_win_source_count,
        duplicate_rate_better_source_count=duplicate_rate_better_source_count,
        batch_preference_win_source_count=batch_preference_win_source_count,
        system_aggregate=system_aggregate,
        engine_rationale_helpful_rate_on_approved=engine_rationale_helpful_rate_on_approved,
        overfitting_payload=overfitting_payload,
    )
    payload = {
        "artifact_type": "proof_comparison",
        "version": PROOF_PROTOCOL_VERSION,
        "judgment_basis": "holdout_only",
        "development_results_count_as_stop_go_evidence": False,
        "eval_set_id": str(eval_set_id),
        "eval_set_name": eval_set.name,
        "source_count": source_count,
        "system_aggregate": system_aggregate,
        "engine_rationale_helpful_rate_on_approved": engine_rationale_helpful_rate_on_approved,
        "source_level_wins": {
            "approved_clip_win_source_count": approved_clip_win_source_count,
            "duplicate_rate_better_source_count": duplicate_rate_better_source_count,
            "batch_preference_win_source_count": batch_preference_win_source_count,
        },
        "gates": gates,
        "sources": sources_payload,
    }
    return payload, comparison_rows


async def create_proof_comparison_run(
    session: AsyncSession,
    *,
    eval_set_id: UUID,
    actor_ref: str,
) -> tuple[ProofComparisonRun, dict]:
    payload, comparison_rows = await build_comparison_payload(session, eval_set_id=eval_set_id)
    run = ProofComparisonRun(
        eval_set_id=eval_set_id,
        actor_ref=actor_ref,
        protocol_version=PROOF_PROTOCOL_VERSION,
    )
    session.add(run)
    await session.flush()

    artifact = await write_json_artifact(
        session,
        storage_key=f"proof-harness/comparisons/{run.id}/comparison.json",
        payload=payload | {"proof_comparison_run_id": str(run.id)},
        metadata_jsonb={
            "artifact_type": "proof_comparison",
            "proof_comparison_run_id": str(run.id),
            "eval_set_id": str(eval_set_id),
        },
    )
    run.artifact_id = artifact.id
    await session.flush()

    for source_video_id, system_name, metric_name, metric_value in comparison_rows:
        session.add(
            ProofComparisonResult(
                proof_comparison_run_id=run.id,
                source_video_id=source_video_id,
                system_name=system_name,
                metric_name=metric_name,
                metric_value=round(metric_value, 4),
            )
        )
    await session.flush()
    return run, payload | {"proof_comparison_run_id": str(run.id)}


async def build_proof_comparison_run_payload(session: AsyncSession, run: ProofComparisonRun) -> dict:
    artifact = await session.get(ArtifactObject, run.artifact_id) if run.artifact_id is not None else None
    payload = {}
    if artifact is not None:
        payload = get_storage_service().read_json(storage_key=artifact.storage_key)
    return {
        "id": run.id,
        "eval_set_id": run.eval_set_id,
        "artifact_id": run.artifact_id,
        "artifact_storage_key": artifact.storage_key if artifact is not None else None,
        "actor_ref": run.actor_ref,
        "protocol_version": run.protocol_version,
        "created_at": run.created_at,
        "payload": payload,
    }

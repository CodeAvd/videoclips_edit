from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models.enums import ArtifactKind, CandidateLabelValue, EvalSetStatus, StageName
from app.models.job import (
    ArtifactObject,
    BenchmarkResult,
    BenchmarkRun,
    CandidateLabel,
    EvalSet,
    EvalSetMember,
    Job,
)
from app.services.candidate_ranker import RankedCandidate, rank_candidates
from app.services.storage import get_storage_service
from app.services.worker_runtime import (
    get_current_transcript_revision,
    get_latest_succeeded_stage_run,
    list_transcript_segments,
    list_transcript_words,
    load_stage_artifact_payloads,
)
from app.services.transcript_provider import TranscriptSegmentItem, TranscriptWordItem


BENCHMARK_METRIC_ACCEPT_TOP_5 = "accepted_coverage_top_5"
BENCHMARK_METRIC_ACCEPT_TOP_10 = "accepted_coverage_top_10"
BENCHMARK_METRIC_REJECT_TOP_5 = "rejected_intrusion_top_5"


@dataclass(slots=True)
class LabeledWindow:
    start_ms: int
    end_ms: int
    label: CandidateLabelValue


@dataclass(slots=True)
class SourceBenchmarkSummary:
    source_video_id: UUID
    job_id: UUID
    candidate_count: int
    metrics: dict[str, float]


def windows_overlap(*, start_ms: int, end_ms: int, other_start_ms: int, other_end_ms: int) -> bool:
    return start_ms < other_end_ms and other_start_ms < end_ms


def label_overlap_rate(candidates: list[RankedCandidate], labels: list[LabeledWindow], *, limit: int) -> float:
    if not labels:
        return 0.0
    matched_labels = 0
    for label in labels:
        if any(
            windows_overlap(
                start_ms=candidate.start_ms,
                end_ms=candidate.end_ms,
                other_start_ms=label.start_ms,
                other_end_ms=label.end_ms,
            )
            for candidate in candidates[:limit]
        ):
            matched_labels += 1
    return round(matched_labels / len(labels), 4)


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
) -> EvalSetMember:
    existing = await session.get(EvalSetMember, {"eval_set_id": eval_set_id, "source_video_id": source_video_id})
    if existing is not None:
        return existing
    member = EvalSetMember(eval_set_id=eval_set_id, source_video_id=source_video_id)
    session.add(member)
    await session.flush()
    return member


async def store_candidate_label(
    session: AsyncSession,
    *,
    eval_set_id: UUID,
    source_video_id: UUID,
    start_ms: int,
    end_ms: int,
    label: CandidateLabelValue,
    actor_ref: str,
    notes: str | None = None,
) -> CandidateLabel:
    candidate_label = CandidateLabel(
        eval_set_id=eval_set_id,
        source_video_id=source_video_id,
        start_ms=start_ms,
        end_ms=end_ms,
        label=label,
        actor_ref=actor_ref,
        notes=notes,
    )
    session.add(candidate_label)
    await session.flush()
    return candidate_label


async def create_benchmark_run(
    session: AsyncSession,
    *,
    eval_set_id: UUID,
    prompt_version: str,
    scoring_policy_version: str,
    artifact_id: UUID | None = None,
) -> BenchmarkRun:
    benchmark_run = BenchmarkRun(
        eval_set_id=eval_set_id,
        prompt_version=prompt_version,
        scoring_policy_version=scoring_policy_version,
        artifact_id=artifact_id,
    )
    session.add(benchmark_run)
    await session.flush()
    return benchmark_run


async def add_benchmark_result(
    session: AsyncSession,
    *,
    benchmark_run_id: UUID,
    source_video_id: UUID,
    metric_name: str,
    metric_value: float,
) -> BenchmarkResult:
    result = BenchmarkResult(
        benchmark_run_id=benchmark_run_id,
        source_video_id=source_video_id,
        metric_name=metric_name,
        metric_value=round(metric_value, 4),
    )
    session.add(result)
    await session.flush()
    return result


async def get_matching_job_for_source_video(
    session: AsyncSession,
    *,
    source_video_id: UUID,
    prompt_version: str,
    scoring_policy_version: str,
) -> Job:
    result = await session.execute(
        select(Job)
        .where(
            Job.source_video_id == source_video_id,
            Job.prompt_version == prompt_version,
            Job.scoring_policy_version == scoring_policy_version,
        )
        .order_by(Job.created_at.desc())
    )
    jobs = list(result.scalars().all())
    for job in jobs:
        try:
            await get_current_transcript_revision(session, job_id=job.id)
            await get_latest_succeeded_stage_run(session, job_id=job.id, stage_name=StageName.feature_extract)
            return job
        except AppError:
            continue
    raise AppError(
        code="benchmark_job_missing",
        message="No eligible job exists for the requested source video and benchmark version.",
        http_status=409,
    )


async def list_labels_for_source_video(
    session: AsyncSession,
    *,
    eval_set_id: UUID,
    source_video_id: UUID,
) -> list[LabeledWindow]:
    result = await session.execute(
        select(CandidateLabel)
        .where(
            CandidateLabel.eval_set_id == eval_set_id,
            CandidateLabel.source_video_id == source_video_id,
        )
        .order_by(CandidateLabel.created_at.asc())
    )
    labels = [
        LabeledWindow(
            start_ms=label.start_ms,
            end_ms=label.end_ms,
            label=label.label,
        )
        for label in result.scalars().all()
    ]
    if not labels:
        raise AppError(
            code="benchmark_labels_missing",
            message="Benchmark members must have at least one human label.",
            http_status=409,
        )
    return labels


async def rank_source_video_for_benchmark(session: AsyncSession, *, job: Job) -> list[RankedCandidate]:
    revision = await get_current_transcript_revision(session, job_id=job.id)
    words = await list_transcript_words(session, transcript_revision_id=revision.id)
    segments = await list_transcript_segments(session, transcript_revision_id=revision.id)
    feature_stage_run = await get_latest_succeeded_stage_run(session, job_id=job.id, stage_name=StageName.feature_extract)
    feature_payloads = await load_stage_artifact_payloads(session, stage_run_id=feature_stage_run.id)
    return rank_candidates(
        words=[
            TranscriptWordItem(
                seq_no=word.seq_no,
                start_ms=word.start_ms,
                end_ms=word.end_ms,
                token=word.token,
                speaker=word.speaker,
                confidence=float(word.confidence) if word.confidence is not None else None,
            )
            for word in words
        ],
        segments=[
            TranscriptSegmentItem(
                seq_no=segment.seq_no,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                speaker=segment.speaker,
                text=segment.text,
                pause_before_ms=segment.pause_before_ms,
                pause_after_ms=segment.pause_after_ms,
                energy_score=float(segment.energy_score) if segment.energy_score is not None else None,
            )
            for segment in segments
        ],
        pause_track=feature_payloads.get("pause_track", []),
        audio_energy_track=feature_payloads.get("audio_energy_track", []),
        scene_track=feature_payloads.get("scene_track", []),
        crop_risk_track=feature_payloads.get("crop_risk_track", []),
    )


def summarize_source_metrics(*, candidates: list[RankedCandidate], labels: list[LabeledWindow]) -> dict[str, float]:
    accepted_labels = [label for label in labels if label.label == CandidateLabelValue.accept]
    rejected_labels = [label for label in labels if label.label == CandidateLabelValue.reject]
    return {
        BENCHMARK_METRIC_ACCEPT_TOP_5: label_overlap_rate(candidates, accepted_labels, limit=5),
        BENCHMARK_METRIC_ACCEPT_TOP_10: label_overlap_rate(candidates, accepted_labels, limit=10),
        BENCHMARK_METRIC_REJECT_TOP_5: label_overlap_rate(candidates, rejected_labels, limit=5),
    }


def build_comparison_payload(
    *,
    benchmark_run: BenchmarkRun,
    source_summaries: list[SourceBenchmarkSummary],
) -> dict:
    aggregate_metrics: dict[str, float] = {}
    if source_summaries:
        metric_names = source_summaries[0].metrics.keys()
        for metric_name in metric_names:
            aggregate_metrics[metric_name] = round(
                sum(summary.metrics[metric_name] for summary in source_summaries) / len(source_summaries),
                4,
            )
    return {
        "benchmark_run_id": str(benchmark_run.id),
        "eval_set_id": str(benchmark_run.eval_set_id),
        "prompt_version": benchmark_run.prompt_version,
        "scoring_policy_version": benchmark_run.scoring_policy_version,
        "source_count": len(source_summaries),
        "aggregate_metrics": aggregate_metrics,
        "sources": [
            {
                "source_video_id": str(summary.source_video_id),
                "job_id": str(summary.job_id),
                "candidate_count": summary.candidate_count,
                "metrics": summary.metrics,
            }
            for summary in source_summaries
        ],
    }


async def persist_benchmark_artifact(
    session: AsyncSession,
    *,
    benchmark_run: BenchmarkRun,
    payload: dict,
) -> ArtifactObject:
    storage_key = f"benchmarks/{benchmark_run.id}/comparison.json"
    storage = get_storage_service()
    stored = storage.write_json(storage_key=storage_key, payload=payload)
    artifact = ArtifactObject(
        storage_key=storage_key,
        kind=ArtifactKind.stage_artifact,
        sha256=stored.sha256 or "",
        size_bytes=stored.size_bytes,
        mime_type=stored.content_type or "application/json",
        metadata_jsonb={
            "artifact_type": "benchmark_comparison",
            "benchmark_run_id": str(benchmark_run.id),
            "eval_set_id": str(benchmark_run.eval_set_id),
            "storage_backend": stored.backend,
        },
    )
    session.add(artifact)
    await session.flush()
    benchmark_run.artifact_id = artifact.id
    await session.flush()
    return artifact


async def run_benchmark(
    session: AsyncSession | None = None,
    *,
    eval_set_id: UUID,
    prompt_version: str,
    scoring_policy_version: str,
) -> BenchmarkRun:
    if session is None:
        async with SessionLocal() as managed_session:
            benchmark_run = await run_benchmark(
                managed_session,
                eval_set_id=eval_set_id,
                prompt_version=prompt_version,
                scoring_policy_version=scoring_policy_version,
            )
            await managed_session.commit()
            await managed_session.refresh(benchmark_run)
            return benchmark_run

    eval_set = await get_eval_set(session, eval_set_id=eval_set_id)
    if eval_set.status != EvalSetStatus.frozen:
        raise AppError(
            code="eval_set_not_frozen",
            message="Only frozen eval sets can be benchmarked.",
            http_status=409,
        )

    members = (
        await session.execute(
            select(EvalSetMember)
            .where(EvalSetMember.eval_set_id == eval_set_id)
            .order_by(EvalSetMember.created_at.asc())
        )
    ).scalars().all()
    if not members:
        raise AppError(code="eval_set_empty", message="Eval set has no members.", http_status=409)

    benchmark_run = await create_benchmark_run(
        session,
        eval_set_id=eval_set_id,
        prompt_version=prompt_version,
        scoring_policy_version=scoring_policy_version,
    )
    source_summaries: list[SourceBenchmarkSummary] = []

    for member in members:
        job = await get_matching_job_for_source_video(
            session,
            source_video_id=member.source_video_id,
            prompt_version=prompt_version,
            scoring_policy_version=scoring_policy_version,
        )
        labels = await list_labels_for_source_video(
            session,
            eval_set_id=eval_set_id,
            source_video_id=member.source_video_id,
        )
        candidates = await rank_source_video_for_benchmark(session, job=job)
        metrics = summarize_source_metrics(candidates=candidates, labels=labels)
        for metric_name, metric_value in metrics.items():
            await add_benchmark_result(
                session,
                benchmark_run_id=benchmark_run.id,
                source_video_id=member.source_video_id,
                metric_name=metric_name,
                metric_value=metric_value,
            )
        source_summaries.append(
            SourceBenchmarkSummary(
                source_video_id=member.source_video_id,
                job_id=job.id,
                candidate_count=len(candidates),
                metrics=metrics,
            )
        )

    comparison_payload = build_comparison_payload(
        benchmark_run=benchmark_run,
        source_summaries=source_summaries,
    )
    await persist_benchmark_artifact(
        session,
        benchmark_run=benchmark_run,
        payload=comparison_payload,
    )
    return benchmark_run


async def assert_pre_m3_benchmark_ready(
    session: AsyncSession | None = None,
    *,
    eval_set_id: UUID,
    prompt_version: str,
    scoring_policy_version: str,
) -> BenchmarkRun:
    if session is None:
        async with SessionLocal() as managed_session:
            return await assert_pre_m3_benchmark_ready(
                managed_session,
                eval_set_id=eval_set_id,
                prompt_version=prompt_version,
                scoring_policy_version=scoring_policy_version,
            )

    result = await session.execute(
        select(BenchmarkRun)
        .join(EvalSet, EvalSet.id == BenchmarkRun.eval_set_id)
        .where(
            BenchmarkRun.eval_set_id == eval_set_id,
            BenchmarkRun.prompt_version == prompt_version,
            BenchmarkRun.scoring_policy_version == scoring_policy_version,
            EvalSet.status == EvalSetStatus.frozen,
        )
        .order_by(BenchmarkRun.created_at.desc())
        .limit(1)
    )
    benchmark_run = result.scalars().first()
    if benchmark_run is None:
        raise AppError(
            code="benchmark_gate_unmet",
            message="No persisted benchmark comparison artifact exists for this frozen eval set and version pair.",
            http_status=409,
        )
    if benchmark_run.artifact_id is None:
        raise AppError(
            code="benchmark_gate_unmet",
            message="No persisted benchmark comparison artifact exists for this frozen eval set and version pair.",
            http_status=409,
        )
    result_count = (
        await session.execute(
            select(BenchmarkResult).where(BenchmarkResult.benchmark_run_id == benchmark_run.id)
        )
    ).scalars().all()
    if not result_count:
        raise AppError(
            code="benchmark_gate_unmet",
            message="No persisted benchmark comparison artifact exists for this frozen eval set and version pair.",
            http_status=409,
        )
    return benchmark_run


async def run_benchmark_from_args(args: argparse.Namespace) -> None:
    async with SessionLocal() as session:
        await run_benchmark(
            session,
            eval_set_id=UUID(args.eval_set_id),
            prompt_version=args.prompt_version,
            scoring_policy_version=args.scoring_policy_version,
        )
        await session.commit()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the internal offline eval benchmark.")
    parser.add_argument("--eval-set-id", required=True, help="UUID of the frozen eval set.")
    parser.add_argument("--prompt-version", required=True, help="Prompt version to benchmark.")
    parser.add_argument("--scoring-policy-version", required=True, help="Scoring policy version to benchmark.")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    asyncio.run(run_benchmark_from_args(args))


if __name__ == "__main__":
    main()

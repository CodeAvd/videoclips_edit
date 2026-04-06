from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.errors import AppError
from app.models.enums import CandidateLabelValue, EvalSetStatus
from app.models.job import BenchmarkRun, CandidateLabel, EvalSet, EvalSetMember


async def create_eval_set(session, *, name: str, status: EvalSetStatus = EvalSetStatus.draft) -> EvalSet:
    eval_set = EvalSet(name=name, status=status)
    session.add(eval_set)
    await session.flush()
    return eval_set


async def get_eval_set(session, *, eval_set_id: UUID) -> EvalSet:
    eval_set = await session.get(EvalSet, eval_set_id)
    if eval_set is None:
        raise AppError(code="not_found", message="Eval set not found.", http_status=404)
    return eval_set


async def add_eval_set_member(session, *, eval_set_id: UUID, source_video_id: UUID) -> EvalSetMember:
    member = EvalSetMember(eval_set_id=eval_set_id, source_video_id=source_video_id)
    session.add(member)
    await session.flush()
    return member


async def list_eval_set_members(session, *, eval_set_id: UUID) -> list[EvalSetMember]:
    result = await session.execute(
        select(EvalSetMember)
        .where(EvalSetMember.eval_set_id == eval_set_id)
        .order_by(EvalSetMember.created_at.asc())
    )
    return list(result.scalars().all())


async def add_candidate_label(
    session,
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


async def list_candidate_labels(
    session,
    *,
    eval_set_id: UUID,
    source_video_id: UUID,
) -> list[CandidateLabel]:
    result = await session.execute(
        select(CandidateLabel)
        .where(
            CandidateLabel.eval_set_id == eval_set_id,
            CandidateLabel.source_video_id == source_video_id,
        )
        .order_by(CandidateLabel.created_at.asc())
    )
    return list(result.scalars().all())


async def list_benchmark_runs(
    session,
    *,
    eval_set_id: UUID,
    prompt_version: str,
    scoring_policy_version: str,
) -> list[BenchmarkRun]:
    result = await session.execute(
        select(BenchmarkRun)
        .where(
            BenchmarkRun.eval_set_id == eval_set_id,
            BenchmarkRun.prompt_version == prompt_version,
            BenchmarkRun.scoring_policy_version == scoring_policy_version,
        )
        .order_by(BenchmarkRun.created_at.desc())
    )
    return list(result.scalars().all())

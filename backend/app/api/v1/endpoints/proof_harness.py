from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import Actor, DbSession
from app.core.security import require_role
from app.models.enums import ActorRole
from app.schemas.common import ListResponse
from app.schemas.proof_harness import (
    BaselineShortlistImportRequest,
    CompleteProofReviewSessionRequest,
    CreateEngineProofShortlistRequest,
    EvalSetCreateRequest,
    EvalSetMemberCreateRequest,
    EvalSetMemberOut,
    EvalSetOut,
    ProofComparisonRunCreateRequest,
    ProofComparisonRunOut,
    ProofReviewSessionCreateRequest,
    ProofReviewSessionOut,
    ProofShortlistOut,
)
from app.services import proof_harness

router = APIRouter()


@router.post(
    "/proof-harness/eval-sets",
    response_model=EvalSetOut,
    dependencies=[Depends(require_role(ActorRole.operator, ActorRole.admin))],
)
async def create_eval_set(payload: EvalSetCreateRequest, db: DbSession) -> EvalSetOut:
    eval_set = await proof_harness.create_eval_set(
        db,
        name=payload.name,
        status=payload.status,
    )
    return EvalSetOut.model_validate(eval_set)


@router.post(
    "/proof-harness/eval-sets/{eval_set_id}/members",
    response_model=EvalSetMemberOut,
    dependencies=[Depends(require_role(ActorRole.operator, ActorRole.admin))],
)
async def add_eval_set_member(
    eval_set_id: UUID,
    payload: EvalSetMemberCreateRequest,
    db: DbSession,
) -> EvalSetMemberOut:
    member = await proof_harness.add_eval_set_member(
        db,
        eval_set_id=eval_set_id,
        source_video_id=payload.source_video_id,
        metadata_jsonb=payload.metadata_jsonb,
    )
    return EvalSetMemberOut.model_validate(member)


@router.get(
    "/proof-harness/eval-sets/{eval_set_id}/members",
    response_model=ListResponse[EvalSetMemberOut],
    dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def list_eval_set_members(eval_set_id: UUID, db: DbSession) -> ListResponse[EvalSetMemberOut]:
    members = await proof_harness.list_eval_set_members(db, eval_set_id=eval_set_id)
    return ListResponse(items=[EvalSetMemberOut.model_validate(member) for member in members], next_cursor=None)


@router.post(
    "/proof-harness/jobs/{job_id}/engine-shortlist",
    response_model=ProofShortlistOut,
    dependencies=[Depends(require_role(ActorRole.operator, ActorRole.admin))],
)
async def create_engine_shortlist(
    job_id: UUID,
    payload: CreateEngineProofShortlistRequest,
    db: DbSession,
    actor: Actor,
) -> ProofShortlistOut:
    shortlist = await proof_harness.create_engine_proof_shortlist(
        db,
        job_id=job_id,
        actor_ref=actor.actor_id,
        eval_set_id=payload.eval_set_id,
    )
    response_payload = await proof_harness.build_proof_shortlist_payload(db, shortlist)
    return ProofShortlistOut.model_validate(response_payload)


@router.post(
    "/proof-harness/source-videos/{source_video_id}/baseline-shortlists",
    response_model=ProofShortlistOut,
    dependencies=[Depends(require_role(ActorRole.operator, ActorRole.admin))],
)
async def import_baseline_shortlist(
    source_video_id: UUID,
    payload: BaselineShortlistImportRequest,
    db: DbSession,
    actor: Actor,
) -> ProofShortlistOut:
    shortlist = await proof_harness.import_baseline_shortlist(
        db,
        source_video_id=source_video_id,
        system_name=payload.system_name,
        actor_ref=actor.actor_id,
        candidates=[item.model_dump(mode="json") for item in payload.candidates],
        eval_set_id=payload.eval_set_id,
        generation_time_seconds=payload.generation_time_seconds,
        metadata_jsonb=payload.metadata_jsonb,
    )
    response_payload = await proof_harness.build_proof_shortlist_payload(db, shortlist)
    return ProofShortlistOut.model_validate(response_payload)


@router.get(
    "/proof-harness/source-videos/{source_video_id}/shortlists",
    response_model=ListResponse[ProofShortlistOut],
    dependencies=[Depends(require_role(ActorRole.operator, ActorRole.admin))],
)
async def list_current_shortlists(source_video_id: UUID, db: DbSession) -> ListResponse[ProofShortlistOut]:
    shortlists = await proof_harness.list_current_proof_shortlists(db, source_video_id=source_video_id)
    items = [
        ProofShortlistOut.model_validate(await proof_harness.build_proof_shortlist_payload(db, shortlist))
        for shortlist in shortlists
    ]
    return ListResponse(items=items, next_cursor=None)


@router.post(
    "/proof-harness/review-sessions",
    response_model=ProofReviewSessionOut,
    dependencies=[Depends(require_role(ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def create_review_session(
    payload: ProofReviewSessionCreateRequest,
    db: DbSession,
    actor: Actor,
) -> ProofReviewSessionOut:
    review_session = await proof_harness.create_review_session(
        db,
        eval_set_id=payload.eval_set_id,
        source_video_id=payload.source_video_id,
        reviewer_actor_ref=actor.actor_id,
        is_audit=payload.is_audit,
        time_budget_seconds=payload.time_budget_seconds,
    )
    response_payload = await proof_harness.build_review_session_payload(db, review_session)
    return ProofReviewSessionOut.model_validate(response_payload)


@router.get(
    "/proof-harness/review-sessions/{proof_review_session_id}",
    response_model=ProofReviewSessionOut,
    dependencies=[Depends(require_role(ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def get_review_session(proof_review_session_id: UUID, db: DbSession) -> ProofReviewSessionOut:
    review_session = await proof_harness.get_proof_review_session(db, proof_review_session_id=proof_review_session_id)
    response_payload = await proof_harness.build_review_session_payload(db, review_session)
    return ProofReviewSessionOut.model_validate(response_payload)


@router.post(
    "/proof-harness/review-sessions/{proof_review_session_id}/complete",
    response_model=ProofReviewSessionOut,
    dependencies=[Depends(require_role(ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def complete_review_session(
    proof_review_session_id: UUID,
    payload: CompleteProofReviewSessionRequest,
    db: DbSession,
    actor: Actor,
) -> ProofReviewSessionOut:
    review_session = await proof_harness.complete_review_session(
        db,
        proof_review_session_id=proof_review_session_id,
        reviewer_actor_ref=actor.actor_id,
        batch_reviews=[item.model_dump(mode="json") for item in payload.batch_reviews],
        batch_preference_ranking=payload.batch_preference_ranking,
    )
    response_payload = await proof_harness.build_review_session_payload(db, review_session)
    return ProofReviewSessionOut.model_validate(response_payload)


@router.post(
    "/proof-harness/comparison-runs",
    response_model=ProofComparisonRunOut,
    dependencies=[Depends(require_role(ActorRole.operator, ActorRole.admin))],
)
async def create_comparison_run(
    payload: ProofComparisonRunCreateRequest,
    db: DbSession,
    actor: Actor,
) -> ProofComparisonRunOut:
    run, artifact_payload = await proof_harness.create_proof_comparison_run(
        db,
        eval_set_id=payload.eval_set_id,
        actor_ref=actor.actor_id,
    )
    response_payload = await proof_harness.build_proof_comparison_run_payload(db, run)
    response_payload["payload"] = artifact_payload
    return ProofComparisonRunOut.model_validate(response_payload)

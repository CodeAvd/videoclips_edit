import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
from uuid import UUID

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models.enums import (
    ArtifactKind,
    IngestStatus,
    JobStatus,
    ProvenanceType,
    SourceType,
    SourceVideoArtifactRole,
    StageName,
    StageRunStatus,
)
from app.models.job import (
    ArtifactObject,
    CandidateClip,
    CandidateSet,
    Job,
    SourceVideo,
    SourceVideoArtifact,
    SourceVideoProvenance,
    StageRun,
    StageRunArtifact,
    TranscriptRevision,
    TranscriptSegment,
    TranscriptWord,
)
from app.repositories.outbox import (
    claim_next_outbox_event,
    compute_backoff_seconds,
    mark_outbox_failed,
    mark_outbox_processed,
    renew_outbox_lease,
)
from app.repositories.stage_runs import (
    LEASE_SECONDS,
    block_stage_run,
    claim_stage_run,
    fail_stage_run,
    get_stage_run,
    renew_stage_run_lease,
    succeed_stage_run,
)
from app.services.candidate_ranker import rank_candidates
from app.services.feature_extract import (
    build_active_speaker_track,
    build_audio_energy_track,
    build_crop_risk_track,
    build_pause_track,
    build_scene_track,
    summarize_features,
)
from app.services.intake_policy import IntakeInput, evaluate_intake
from app.services.media_ingest import build_ingest_outputs_from_path
from app.services.orchestration import enqueue_stage, transition_job_status
from app.services.source_video_artifacts import get_preferred_video_artifact, get_source_video_artifact
from app.services.storage import get_storage_service
from app.services.transcript_provider import TranscriptSegmentItem, TranscriptWordItem, transcribe_with_fallback

settings = get_settings()


def parse_event_payload(payload: dict) -> tuple[UUID, StageName, int]:
    return UUID(payload["job_id"]), StageName(payload["stage_name"]), int(payload["attempt_no"])


def classify_outbox_failure(exc: Exception) -> tuple[bool, str, str]:
    if isinstance(exc, AppError):
        is_retryable = exc.retryable or exc.http_status >= 500
        return is_retryable, exc.code, exc.message
    return True, exc.__class__.__name__, str(exc)


def compute_lease_heartbeat_interval_seconds() -> float:
    shortest_ttl = min(float(settings.outbox_claim_ttl_seconds), float(LEASE_SECONDS))
    return max(1.0, min(shortest_ttl / 3, 30.0))


async def renew_claimed_execution_leases(
    *,
    event_id: UUID,
    job_id: UUID,
    stage_name: StageName,
    attempt_no: int,
    worker_id: str,
    lease_token: str | None = None,
) -> str | None:
    async with SessionLocal() as heartbeat_session:
        renewed_lease_token: str | None = None
        try:
            try:
                stage_run = await get_stage_run(heartbeat_session, job_id, stage_name, attempt_no)
            except AppError:
                stage_run = None
            if (
                stage_run is not None
                and stage_run.status == StageRunStatus.running
                and stage_run.worker_id == worker_id
                and stage_run.lease_token is not None
            ):
                current_token = lease_token or stage_run.lease_token
                if stage_run.lease_token == current_token:
                    renewed = await renew_stage_run_lease(
                        heartbeat_session,
                        stage_run_id=stage_run.id,
                        lease_token=current_token,
                    )
                    if renewed:
                        outbox_renewed = await renew_outbox_lease(heartbeat_session, event_id=event_id)
                        if outbox_renewed:
                            renewed_lease_token = current_token
            await heartbeat_session.commit()
        except Exception:
            await heartbeat_session.rollback()
        return renewed_lease_token


async def maintain_execution_leases(
    *,
    event_id: UUID,
    job_id: UUID,
    stage_name: StageName,
    attempt_no: int,
    worker_id: str,
    stop_event: asyncio.Event,
) -> None:
    lease_token: str | None = None
    while not stop_event.is_set():
        await asyncio.sleep(compute_lease_heartbeat_interval_seconds())
        if stop_event.is_set():
            return
        lease_token = await renew_claimed_execution_leases(
            event_id=event_id,
            job_id=job_id,
            stage_name=stage_name,
            attempt_no=attempt_no,
            worker_id=worker_id,
            lease_token=lease_token,
        )


async def stop_lease_heartbeat(stop_event: asyncio.Event, heartbeat_task: asyncio.Task[None]) -> None:
    stop_event.set()
    if not heartbeat_task.done():
        heartbeat_task.cancel()
    with suppress(asyncio.CancelledError):
        await heartbeat_task


async def create_artifact_from_bytes(
    *,
    session,
    storage_key: str,
    kind: ArtifactKind,
    mime_type: str,
    body: bytes,
    metadata_jsonb: dict,
) -> ArtifactObject:
    storage = get_storage_service()
    stored = storage.write_bytes(storage_key=storage_key, content_type=mime_type, body=body)
    artifact = ArtifactObject(
        storage_key=storage_key,
        kind=kind,
        sha256=stored.sha256 or "",
        size_bytes=stored.size_bytes,
        mime_type=stored.content_type or mime_type,
        metadata_jsonb=metadata_jsonb | {"storage_backend": stored.backend},
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def create_artifact_from_json(
    *,
    session,
    storage_key: str,
    kind: ArtifactKind,
    payload: dict | list,
    metadata_jsonb: dict,
) -> ArtifactObject:
    storage = get_storage_service()
    stored = storage.write_json(storage_key=storage_key, payload=payload)
    artifact = ArtifactObject(
        storage_key=storage_key,
        kind=kind,
        sha256=stored.sha256 or "",
        size_bytes=stored.size_bytes,
        mime_type=stored.content_type or "application/json",
        metadata_jsonb=metadata_jsonb | {"storage_backend": stored.backend},
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def get_current_transcript_revision(session, *, job_id: UUID) -> TranscriptRevision:
    result = await session.execute(
        select(TranscriptRevision)
        .where(TranscriptRevision.job_id == job_id, TranscriptRevision.is_current.is_(True))
        .order_by(TranscriptRevision.version_no.desc())
        .limit(1)
    )
    revision = result.scalars().first()
    if revision is None:
        raise AppError(code="transcript_not_found", message="Transcript revision not found.", http_status=404)
    return revision


async def list_transcript_words(session, *, transcript_revision_id: UUID) -> list[TranscriptWord]:
    result = await session.execute(
        select(TranscriptWord)
        .where(TranscriptWord.transcript_revision_id == transcript_revision_id)
        .order_by(TranscriptWord.seq_no.asc())
    )
    return list(result.scalars().all())


async def list_transcript_segments(session, *, transcript_revision_id: UUID) -> list[TranscriptSegment]:
    result = await session.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcript_revision_id == transcript_revision_id)
        .order_by(TranscriptSegment.seq_no.asc())
    )
    return list(result.scalars().all())


async def get_latest_succeeded_stage_run(session, *, job_id: UUID, stage_name: StageName):
    result = await session.execute(
        select(StageRun)
        .where(
            StageRun.job_id == job_id,
            StageRun.stage_name == stage_name,
            StageRun.status == StageRunStatus.succeeded,
        )
        .order_by(StageRun.created_at.desc())
        .limit(1)
    )
    stage_run = result.scalars().first()
    if stage_run is None:
        raise AppError(
            code="stage_run_not_found",
            message=f"No succeeded stage run found for {stage_name.value}.",
            http_status=404,
        )
    return stage_run


async def load_stage_artifact_payloads(session, *, stage_run_id: UUID) -> dict[str, object]:
    result = await session.execute(
        select(StageRunArtifact.role, ArtifactObject.storage_key)
        .join(ArtifactObject, ArtifactObject.id == StageRunArtifact.artifact_id)
        .where(StageRunArtifact.stage_run_id == stage_run_id)
    )
    storage = get_storage_service()
    return {role: storage.read_json(storage_key=storage_key) for role, storage_key in result.all()}


async def handle_intake(job_id: UUID, attempt_no: int, *, worker_id: str, session) -> None:
    job = await session.get(Job, job_id)
    source_video = await session.get(SourceVideo, job.source_video_id)
    has_provenance = bool(
        await session.scalar(select(func.count()).select_from(SourceVideoProvenance).where(SourceVideoProvenance.source_video_id == source_video.id))
    )
    stage_run = await claim_stage_run(session, job_id=job_id, stage_name=StageName.intake, attempt_no=attempt_no, worker_id=worker_id)
    decision = evaluate_intake(
        IntakeInput(
            rights_attestation=source_video.rights_attestation,
            duration_ms=source_video.duration_ms,
            language=source_video.language,
            deployment_language=settings.deployment_language,
            source_type=source_video.source_type.value,
            has_provenance=has_provenance or source_video.source_type == SourceType.uploaded_asset,
            speaker_count_estimate=source_video.speaker_count_estimate,
        )
    )

    if decision.outcome == "accepted":
        source_video.ingest_status = IngestStatus.accepted
        await succeed_stage_run(session, stage_run)
        await transition_job_status(
            session,
            job=job,
            to_status=JobStatus.processing,
            stage_run_id=stage_run.id,
            actor_type="worker",
            actor_ref=worker_id,
            reason_code="intake_accepted",
        )
        await enqueue_stage(
            session,
            job_id=job.id,
            stage_name=StageName.ingest,
            dedupe_key=f"job:{job.id}:stage:{StageName.ingest.value}:attempt:1",
        )
        return

    if decision.outcome == "manual_review_required":
        source_video.ingest_status = IngestStatus.manual_review_required
        await block_stage_run(session, stage_run, error_code="manual_review_required")
        await transition_job_status(
            session,
            job=job,
            to_status=JobStatus.awaiting_manual_review,
            stage_run_id=stage_run.id,
            actor_type="worker",
            actor_ref=worker_id,
            reason_code=decision.reason_codes[0],
        )
        return

    source_video.ingest_status = IngestStatus.rejected_out_of_scope
    await fail_stage_run(session, stage_run, error_code=decision.reason_codes[0], retryable=False)
    await transition_job_status(
        session,
        job=job,
        to_status=JobStatus.failed,
        stage_run_id=stage_run.id,
        actor_type="worker",
        actor_ref=worker_id,
        reason_code=decision.reason_codes[0],
    )


async def handle_ingest(job_id: UUID, attempt_no: int, *, worker_id: str, session) -> None:
    job = await session.get(Job, job_id)
    source_video = await session.get(SourceVideo, job.source_video_id)
    stage_run = await claim_stage_run(session, job_id=job_id, stage_name=StageName.ingest, attempt_no=attempt_no, worker_id=worker_id)
    source_video.ingest_status = IngestStatus.processing
    await session.commit()
    source_asset = await get_source_video_artifact(
        session,
        source_video_id=source_video.id,
        role=SourceVideoArtifactRole.source_asset,
    )
    storage = get_storage_service()
    source_path = storage.local_path_for_key(storage_key=source_asset.storage_key)
    if source_path is not None:
        ingest_output = await build_ingest_outputs_from_path(input_path=source_path)
    else:
        with tempfile.TemporaryDirectory(prefix="ai-shorts-source-") as temp_dir:
            staged_input_path = Path(temp_dir) / Path(source_asset.storage_key).name
            storage.materialize_to_path(storage_key=source_asset.storage_key, destination=staged_input_path)
            ingest_output = await build_ingest_outputs_from_path(input_path=staged_input_path)
    if source_video.duration_ms is None and ingest_output.probe.duration_ms is not None:
        source_video.duration_ms = ingest_output.probe.duration_ms

    derived_artifacts = [
        (
            (SourceVideoArtifactRole.normalized_audio,),
            ArtifactKind.normalized_audio,
            f"derived/{source_video.id}/audio.wav",
            "audio/wav",
            ingest_output.normalized_audio_bytes,
            {
                "source_video_id": str(source_video.id),
                "role": SourceVideoArtifactRole.normalized_audio.value,
                "probe_duration_ms": ingest_output.probe.duration_ms,
            },
        ),
        (
            (SourceVideoArtifactRole.thumbnails,),
            ArtifactKind.thumbnails,
            f"derived/{source_video.id}/thumbnails.json",
            "application/json",
            None,
            {"source_video_id": str(source_video.id), "role": SourceVideoArtifactRole.thumbnails.value},
        ),
    ]
    if ingest_output.proxy_video_bytes:
        derived_artifacts.append(
            (
                (SourceVideoArtifactRole.proxy_video, SourceVideoArtifactRole.canonical_video),
                ArtifactKind.proxy_video,
                f"derived/{source_video.id}/proxy.mp4",
                "video/mp4",
                ingest_output.proxy_video_bytes,
                {"source_video_id": str(source_video.id), "role": SourceVideoArtifactRole.proxy_video.value},
            )
        )

    for roles, kind, storage_key, mime_type, body, metadata_jsonb in derived_artifacts:
        if body is None:
            artifact = await create_artifact_from_json(
                session=session,
                storage_key=storage_key,
                kind=kind,
                payload=ingest_output.thumbnails_payload,
                metadata_jsonb=metadata_jsonb,
            )
        else:
            artifact = await create_artifact_from_bytes(
                session=session,
                storage_key=storage_key,
                kind=kind,
                mime_type=mime_type,
                body=body,
                metadata_jsonb=metadata_jsonb,
            )
        for role in roles:
            session.add(SourceVideoArtifact(source_video_id=source_video.id, artifact_id=artifact.id, role=role.value))

    evidence = await create_artifact_from_json(
        session=session,
        storage_key=f"logs/{job.id}/{stage_run.id}/ingest.json",
        kind=ArtifactKind.stage_artifact,
        payload={
            "job_id": str(job.id),
            "stage_run_id": str(stage_run.id),
            "stage_name": StageName.ingest.value,
            "artifacts": [
                SourceVideoArtifactRole.normalized_audio.value,
                SourceVideoArtifactRole.proxy_video.value,
                SourceVideoArtifactRole.canonical_video.value,
                SourceVideoArtifactRole.thumbnails.value,
            ],
            "probe": {
                "duration_ms": ingest_output.probe.duration_ms,
                "has_video": ingest_output.probe.has_video,
                "has_audio": ingest_output.probe.has_audio,
                "width": ingest_output.probe.width,
                "height": ingest_output.probe.height,
            },
        },
        metadata_jsonb={"stage_name": StageName.ingest.value, "probe_duration_ms": ingest_output.probe.duration_ms},
    )
    session.add(StageRunArtifact(stage_run_id=stage_run.id, artifact_id=evidence.id, role="ingest_log"))
    source_video.ingest_status = IngestStatus.ready
    await succeed_stage_run(session, stage_run)
    await enqueue_stage(
        session,
        job_id=job.id,
        stage_name=StageName.transcript,
        dedupe_key=f"job:{job.id}:stage:{StageName.transcript.value}:attempt:1",
    )


async def handle_transcript(job_id: UUID, attempt_no: int, *, worker_id: str, session) -> None:
    job = await session.get(Job, job_id)
    source_video = await session.get(SourceVideo, job.source_video_id)
    stage_run = await claim_stage_run(session, job_id=job_id, stage_name=StageName.transcript, attempt_no=attempt_no, worker_id=worker_id)
    await session.commit()
    audio_artifact = await get_source_video_artifact(
        session,
        source_video_id=source_video.id,
        role=SourceVideoArtifactRole.normalized_audio,
    )
    storage = get_storage_service()
    transcript_payload = await transcribe_with_fallback(
        filename=Path(audio_artifact.storage_key).name,
        content_type=audio_artifact.mime_type,
        body=storage.read_bytes(storage_key=audio_artifact.storage_key),
        language_hint=source_video.language,
        diarization_mode="optional",
    )

    current_revisions = await session.execute(
        select(TranscriptRevision).where(TranscriptRevision.job_id == job.id, TranscriptRevision.is_current.is_(True))
    )
    for revision in current_revisions.scalars().all():
        revision.is_current = False

    current_max = await session.scalar(
        select(func.max(TranscriptRevision.version_no)).where(TranscriptRevision.job_id == job.id)
    )
    version_no = int(current_max or 0) + 1
    revision = TranscriptRevision(
        job_id=job.id,
        stage_run_id=stage_run.id,
        version_no=version_no,
        is_current=True,
        provider=transcript_payload.provider,
        provider_version=transcript_payload.provider_version,
        language=transcript_payload.language,
        adapter_metadata_jsonb=transcript_payload.adapter_metadata,
    )
    session.add(revision)
    await session.flush()

    for word in transcript_payload.words:
        session.add(
            TranscriptWord(
                transcript_revision_id=revision.id,
                seq_no=word.seq_no,
                start_ms=word.start_ms,
                end_ms=word.end_ms,
                token=word.token,
                speaker=word.speaker,
                confidence=word.confidence,
            )
        )
    for segment in transcript_payload.segments:
        session.add(
            TranscriptSegment(
                transcript_revision_id=revision.id,
                seq_no=segment.seq_no,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                speaker=segment.speaker,
                text=segment.text,
                pause_before_ms=segment.pause_before_ms,
                pause_after_ms=segment.pause_after_ms,
                energy_score=segment.energy_score,
            )
        )
    asr_payload = await create_artifact_from_json(
        session=session,
        storage_key=f"logs/{job.id}/{stage_run.id}/transcript.json",
        kind=ArtifactKind.asr_payload,
        payload=transcript_payload.raw_payload,
        metadata_jsonb={
            "provider": transcript_payload.provider,
            "provider_version": transcript_payload.provider_version,
            "language": transcript_payload.language,
        },
    )
    session.add(StageRunArtifact(stage_run_id=stage_run.id, artifact_id=asr_payload.id, role="asr_payload"))
    await succeed_stage_run(session, stage_run)
    await enqueue_stage(
        session,
        job_id=job.id,
        stage_name=StageName.feature_extract,
        dedupe_key=f"job:{job.id}:stage:{StageName.feature_extract.value}:attempt:1",
    )


async def handle_feature_extract(job_id: UUID, attempt_no: int, *, worker_id: str, session) -> None:
    job = await session.get(Job, job_id)
    source_video = await session.get(SourceVideo, job.source_video_id)
    stage_run = await claim_stage_run(session, job_id=job_id, stage_name=StageName.feature_extract, attempt_no=attempt_no, worker_id=worker_id)
    await session.commit()
    revision = await get_current_transcript_revision(session, job_id=job.id)
    words = await list_transcript_words(session, transcript_revision_id=revision.id)
    segments = await list_transcript_segments(session, transcript_revision_id=revision.id)
    preferred_video_artifact = await get_preferred_video_artifact(session, source_video_id=source_video.id)
    audio_artifact = await get_source_video_artifact(
        session,
        source_video_id=source_video.id,
        role=SourceVideoArtifactRole.normalized_audio,
    )
    storage = get_storage_service()
    normalized_audio_bytes = storage.read_bytes(storage_key=audio_artifact.storage_key)

    pause_track = build_pause_track(words)
    audio_energy_track = build_audio_energy_track(normalized_audio_bytes)
    scene_track = build_scene_track(segments)
    active_speaker_track = build_active_speaker_track(segments)
    crop_risk_track = build_crop_risk_track(segments, speaker_count_estimate=source_video.speaker_count_estimate)
    feature_summary = summarize_features(
        pauses=pause_track,
        audio_energy=audio_energy_track,
        scene_track=scene_track,
        active_speaker_track=active_speaker_track,
        crop_risk_track=crop_risk_track,
    )

    artifacts = {
        "pause_track": pause_track,
        "audio_energy_track": audio_energy_track,
        "scene_track": scene_track,
        "active_speaker_track": active_speaker_track,
        "crop_risk_track": crop_risk_track,
        "feature_summary": feature_summary,
    }
    for role, payload in artifacts.items():
        artifact = await create_artifact_from_json(
            session=session,
            storage_key=f"logs/{job.id}/{stage_run.id}/{role}.json",
            kind=ArtifactKind.stage_artifact,
            payload=payload,
            metadata_jsonb={
                "stage_name": StageName.feature_extract.value,
                "role": role,
                "video_storage_key": preferred_video_artifact.storage_key,
            },
        )
        session.add(StageRunArtifact(stage_run_id=stage_run.id, artifact_id=artifact.id, role=role))

    await succeed_stage_run(session, stage_run)
    await enqueue_stage(
        session,
        job_id=job.id,
        stage_name=StageName.ranking,
        dedupe_key=f"job:{job.id}:stage:{StageName.ranking.value}:attempt:1",
    )


async def handle_ranking(job_id: UUID, attempt_no: int, *, worker_id: str, session) -> None:
    job = await session.get(Job, job_id)
    stage_run = await claim_stage_run(session, job_id=job_id, stage_name=StageName.ranking, attempt_no=attempt_no, worker_id=worker_id)
    await session.commit()
    revision = await get_current_transcript_revision(session, job_id=job.id)
    words = await list_transcript_words(session, transcript_revision_id=revision.id)
    segments = await list_transcript_segments(session, transcript_revision_id=revision.id)
    feature_stage_run = await get_latest_succeeded_stage_run(session, job_id=job.id, stage_name=StageName.feature_extract)
    feature_payloads = await load_stage_artifact_payloads(session, stage_run_id=feature_stage_run.id)
    ranked = rank_candidates(
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
    if len(ranked) < 5:
        raise AppError(
            code="candidate_generation_failed",
            message="Ranking did not produce enough candidate clips.",
            http_status=422,
        )

    current_candidate_sets = await session.execute(
        select(CandidateSet).where(CandidateSet.job_id == job.id, CandidateSet.is_current.is_(True))
    )
    for candidate_set in current_candidate_sets.scalars().all():
        candidate_set.is_current = False
    current_max = await session.scalar(select(func.max(CandidateSet.version_no)).where(CandidateSet.job_id == job.id))
    candidate_set = CandidateSet(
        job_id=job.id,
        stage_run_id=stage_run.id,
        transcript_revision_id=revision.id,
        version_no=int(current_max or 0) + 1,
        is_current=True,
        scoring_policy_version=job.scoring_policy_version,
    )
    session.add(candidate_set)
    await session.flush()

    for rank_no, candidate in enumerate(ranked, start=1):
        session.add(
            CandidateClip(
                candidate_set_id=candidate_set.id,
                job_id=job.id,
                rank_no=rank_no,
                start_ms=candidate.start_ms,
                end_ms=candidate.end_ms,
                hook_score=candidate.hook_score,
                semantic_score=candidate.semantic_score,
                audio_score=candidate.audio_score,
                visual_score=candidate.visual_score,
                llm_score=candidate.llm_score,
                final_score=candidate.final_score,
                duplicate_group=candidate.duplicate_group,
                topic_cluster=candidate.topic_cluster,
                length_bucket=candidate.length_bucket,
                rationale_jsonb=candidate.rationale_jsonb,
            )
        )

    ranking_summary = await create_artifact_from_json(
        session=session,
        storage_key=f"logs/{job.id}/{stage_run.id}/ranking_summary.json",
        kind=ArtifactKind.stage_artifact,
        payload={
            "candidate_count": len(ranked),
            "top_score": ranked[0].final_score,
            "bottom_score": ranked[-1].final_score,
            "scoring_policy_version": job.scoring_policy_version,
        },
        metadata_jsonb={"stage_name": StageName.ranking.value},
    )
    session.add(StageRunArtifact(stage_run_id=stage_run.id, artifact_id=ranking_summary.id, role="ranking_summary"))
    await succeed_stage_run(session, stage_run)
    await transition_job_status(
        session,
        job=job,
        to_status=JobStatus.awaiting_shortlist_review,
        stage_run_id=stage_run.id,
        actor_type="worker",
        actor_ref=worker_id,
        reason_code="candidate_set_ready",
    )


async def dispatch_outbox_event(event, *, worker_id: str, session) -> None:
    job_id, stage_name, attempt_no = parse_event_payload(event.payload_jsonb)
    if stage_name == StageName.intake:
        await handle_intake(job_id, attempt_no, worker_id=worker_id, session=session)
        return
    if stage_name == StageName.ingest:
        await handle_ingest(job_id, attempt_no, worker_id=worker_id, session=session)
        return
    if stage_name == StageName.transcript:
        await handle_transcript(job_id, attempt_no, worker_id=worker_id, session=session)
        return
    if stage_name == StageName.feature_extract:
        await handle_feature_extract(job_id, attempt_no, worker_id=worker_id, session=session)
        return
    if stage_name == StageName.ranking:
        await handle_ranking(job_id, attempt_no, worker_id=worker_id, session=session)
        return
    raise RuntimeError(f"Unsupported stage dispatch: {stage_name}")


async def process_next_outbox_event(*, worker_id: str) -> bool:
    async with SessionLocal() as session:
        event = await claim_next_outbox_event(session)
        if event is None:
            return False
        await session.commit()
        event_id = event.id
        job_id, stage_name, attempt_no = parse_event_payload(event.payload_jsonb)
        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            maintain_execution_leases(
                event_id=event_id,
                job_id=job_id,
                stage_name=stage_name,
                attempt_no=attempt_no,
                worker_id=worker_id,
                stop_event=stop_heartbeat,
            )
        )
        try:
            await dispatch_outbox_event(event, worker_id=worker_id, session=session)
            await stop_lease_heartbeat(stop_heartbeat, heartbeat_task)
            await mark_outbox_processed(session, event)
            await session.commit()
            return True
        except Exception as exc:
            await stop_lease_heartbeat(stop_heartbeat, heartbeat_task)
            await session.rollback()
            retryable, error_code, error_message = classify_outbox_failure(exc)
            async with SessionLocal() as retry_session:
                retry_event = await retry_session.get(type(event), event_id)
                if retry_event is not None:
                    next_retry_count = await mark_outbox_failed(
                        retry_session,
                        retry_event,
                        error_code=error_code,
                        error_message=error_message,
                    )
                    should_retry = retryable and next_retry_count <= retry_event.max_retries
                    try:
                        stage_run = await get_stage_run(retry_session, job_id, stage_name, attempt_no)
                    except AppError:
                        stage_run = None
                    if stage_run is not None:
                        await fail_stage_run(retry_session, stage_run, error_code=error_code, retryable=should_retry)
                    if should_retry:
                        await enqueue_stage(
                            retry_session,
                            job_id=job_id,
                            stage_name=stage_name,
                            available_at=datetime.now(UTC) + timedelta(seconds=compute_backoff_seconds(next_retry_count)),
                            retry_count=next_retry_count,
                            max_retries=retry_event.max_retries,
                        )
                    else:
                        job = await retry_session.get(Job, job_id)
                        if job is not None and job.status not in {JobStatus.failed, JobStatus.cancelled}:
                            await transition_job_status(
                                retry_session,
                                job=job,
                                to_status=JobStatus.failed,
                                stage_run_id=stage_run.id if stage_run is not None else None,
                                actor_type="worker",
                                actor_ref=worker_id,
                                reason_code=error_code,
                            )
                    await retry_session.commit()
            raise
        finally:
            with suppress(Exception):
                await stop_lease_heartbeat(stop_heartbeat, heartbeat_task)


async def run_worker_loop(*, worker_id: str, poll_interval_seconds: float, once: bool, max_events: int | None) -> None:
    processed = 0
    while True:
        try:
            had_work = await process_next_outbox_event(worker_id=worker_id)
        except Exception:
            if once:
                raise
            await asyncio.sleep(poll_interval_seconds)
            continue
        if had_work:
            processed += 1
            if once:
                return
            if max_events is not None and processed >= max_events:
                return
            continue
        if once:
            return
        await asyncio.sleep(poll_interval_seconds)

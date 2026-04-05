# AI Shorts Engine v1 Implementation Specification

## 1. Product Decision

### V1 product

- Product type: internal production engine
- Core job: convert one owned long-form spoken video into `3-5` publish-ready YouTube Shorts
- Secondary output: export packages for TikTok and Instagram Reels
- Publish mode: approval-gated only
- Primary user: solo creator or small content team with recurring long-form content

### System of record

- This specification is the implementation contract.
- [research-dossier.md](/Users/grisaavdeev/Downloads/thumbnails/projects/2026-04-04-ai-shorts-engine/research-dossier.md) remains the evidence base and product brief.
- Where the dossier and this spec differ, this spec wins for v1 implementation.

### Explicit non-goals

- no multi-tenant SaaS
- no billing
- no net-new script-to-video or avatar generation
- no full manual NLE replacement
- no autoposting without approval
- no trend-ingestion engine in v1
- no fine-tuned proprietary ranking model in v1

## 2. Scope and Constraints

### Supported inputs

- owned content only
- one source per job
- spoken long-form only
- supported formats: podcast, interview, webinar, talking-head educational video
- supported duration: `20-120 min`
- supported language in v1: one configured language per deployment
- recommended speaker count: `1-2` active speakers

### Intake policy

- accepted intake types:
  - uploaded asset
  - approved import from allowlisted source
- every job must include `rights_attestation = true`
- generic arbitrary `source_url` ingestion is out of scope for v1

### Output scope

- raw candidate set: `30-80`
- shortlist: `5-8`
- target final approved renders: `3-5`
- one master render per approved clip
- per-platform output is metadata and export packaging, not separate creative trees in v1

## 3. Success Criteria

### North star

`publish_ready_rate = jobs_with_at_least_3_approved_clips / all_completed_jobs`

### Product metrics

- `time_to_first_preview`
- `time_to_approved_batch`
- `manual_minutes_per_video`
- `cost_per_approved_clip`
- `qa_pass_rate`
- `opening_hold_rate`
- `completion_rate`

### Acceptance thresholds for pilot

- at least `3` approved clips on most in-scope videos
- `5-10x` reduction in manual production time
- no publish without explicit approval
- no mid-word cuts in approved clips
- subtitle/audio drift operational target `<100ms`
- cost per approved clip remains below a configured project threshold

### Kill criteria

- if pilot jobs fail to produce `>=3` approved clips on at least `60%` of in-scope videos, reduce scope before expanding
- if manual salvage is required for most outputs, pause automation expansion
- if cost per approved clip is above manual baseline for two consecutive pilot rounds, cut feature scope

## 4. Target Architecture

### Chosen architecture

- `FastAPI` modular monolith as control plane
- `Postgres` as primary relational store
- `S3-compatible object storage` for media and artifacts
- worker queue for asynchronous execution
- Python workers for ingest, ASR, features, ranking, rendering, QA, publishing, analytics
- `Redis` is optional and should only be added if caching or locking pain is proven

Implementation note:

- `api-service`, `job-orchestrator`, and workers are logical modules inside one app plus one worker runtime, not separate deployables in v1

### Rejected v1 architectures

- `n8n` as core execution backbone: rejected for v1 production use
- `Temporal` as mandatory orchestration base: rejected for v1 unless the team already operates it
- fully distributed services: rejected for v1 as premature infra complexity

### Allowed helper tools

- `n8n` for ops glue or non-core automations
- `Vizard` as primary editing adapter
- `FFmpeg templates` as fallback and control lane
- commercial tools are adapters, not the system of record

## 5. Core Components

### Control plane

#### `api-service`

- receives job creation requests
- manages asset intake
- stores brand settings and platform settings
- exposes review actions

#### `job-orchestrator`

- DB-backed state machine
- owns stage transitions
- owns retries and terminal states
- owns human approval gates

### Workers

#### `ingest-worker`

- validates source asset
- normalizes container and codecs
- creates audio track, proxy, preview thumbnails

#### `transcript-worker`

- generates word-level timestamps
- optionally generates speaker labels
- stores transcript confidence

#### `feature-worker`

- extracts pause spans
- computes audio energy
- detects scene boundaries
- computes active speaker and crop risk signals

#### `ranking-worker`

- generates candidate windows
- scores candidates using hybrid scoring
- applies diversification rules

#### `render-worker`

- produces preview renders
- produces final renders
- applies captions, reframe, overlay, silence trim

#### `qa-worker`

- runs deterministic checks
- runs LLM critique as advisory layer
- returns pass, regenerate, manual review, or reject

#### `publish-worker`

- creates drafts or scheduled posts
- records publish intent and attempts
- enforces idempotency

#### `analytics-worker`

- fetches post metrics at fixed windows
- writes metric snapshots with lineage

## 6. Execution Model

### Separation of content entities and execution entities

Content entities describe the source and outputs.

- `JobConfigSnapshot`
- `BrandProfile`
- `SourceVideo`
- `TranscriptWord`
- `TranscriptSegment`
- `CandidateClip`
- `EditPlan`
- `RenderVariant`
- `PostDraft`
- `ExportPackage`
- `PlatformPost`

Execution entities describe runs and attempts.

- `Job`
- `StageRun`
- `RenderAttempt`
- `QaRun`
- `QaFinding`
- `ApprovalDecision`
- `PublishIntent`
- `PublishAttempt`
- `MetricsSnapshot`

### Execution rules

- a `SourceVideo` may be reused across multiple `Job`s
- every decision and artifact must be attached to a specific `Job`
- retries happen on execution entities, not by mutating content entities in place
- every worker stage must emit terminal or retryable outcome
- only one active `StageRun` may exist per `(job_id, stage_name)`
- stage transitions use optimistic locking or compare-and-swap semantics
- workers must claim a lease before stage execution and renew it while running
- external side effects must be emitted through an outbox or equivalent durable handoff
- artifact writes are immutable; new attempts produce new artifact refs instead of overwriting old ones

## 7. State Machines

### Job state machine

States:

- `created`
- `processing`
- `awaiting_manual_review`
- `awaiting_shortlist_review`
- `rendering_finals`
- `qa_manual_salvage_required`
- `awaiting_final_approval`
- `publishing`
- `metrics_ingesting`
- `completed`
- `completed_partial`
- `completed_insufficient_output`
- `failed`
- `cancelled`

Rules:

- user-facing state is coarse; stage detail lives in `StageRun`
- stage transitions are monotonic within a single execution branch
- failed stage writes reason code
- retries create new `StageRun`, not silent overwrite
- `awaiting_manual_review` may resume to `processing` or terminate as `cancelled`
- `qa_manual_salvage_required` may resume to `rendering_finals` or terminate as `completed_partial`
- `completed_partial` means the job produced at least one approved output but missed the target final clip count
- `completed_insufficient_output` means the job finished without meeting the minimum success threshold

### Review and approval gates

#### Gate 1: shortlist approval

- user approves which preview clips proceed to final render

#### Gate 2: final approval

- user approves the exact final payload: render asset, title, caption, hashtags, destination account, and schedule
- approval writes an immutable approved payload snapshot
- any material change to the approved payload invalidates approval and requires re-approval

### Publish state machine

States:

- `intent_created`
- `awaiting_final_approval`
- `approved_snapshot_frozen`
- `dispatching`
- `draft_created`
- `scheduled`
- `published`
- `failed_retryable`
- `failed_terminal`
- `cancelled`

Rules:

- publish actions are idempotent
- state changes require audit trail
- external platform IDs are recorded as soon as available
- publish may start only from an immutable approved payload snapshot
- terminal publish states cannot be retried without explicit user action

## 8. Data Model

### Required entities

#### `BrandProfile`

- `id`
- `name`
- `language`
- `caption_style_defaults`
- `overlay_policy`
- `music_policy`
- `platform_defaults`

#### `PlatformAccount`

- `id`
- `platform`
- `channel_name`
- `connection_ref`
- `capabilities_json`
- `status`

#### `SourceVideo`

- `id`
- `brand_profile_id`
- `source_type`
- `asset_ref`
- `duration_ms`
- `language`
- `speaker_count_estimate`
- `rights_attestation`
- `ingest_status`

#### `Job`

- `id`
- `source_video_id`
- `brand_profile_id`
- `target_final_clip_count`
- `target_platforms`
- `status`
- `prompt_version`
- `scoring_policy_version`
- `job_config_snapshot_id`
- `created_at`

#### `JobConfigSnapshot`

- `id`
- `job_id`
- `target_final_clip_count`
- `shortlist_target_count`
- `prompt_version`
- `scoring_policy_version`
- `config_json`
- `created_at`

#### `StageRun`

- `id`
- `job_id`
- `stage_name`
- `attempt_no`
- `status`
- `worker_id`
- `lease_expires_at`
- `started_at`
- `ended_at`
- `error_code`
- `cost_usd`

#### `TranscriptWord`

- `id`
- `job_id`
- `start_ms`
- `end_ms`
- `token`
- `speaker`
- `confidence`

#### `TranscriptSegment`

- `id`
- `job_id`
- `start_ms`
- `end_ms`
- `speaker`
- `text`
- `pause_before_ms`
- `pause_after_ms`
- `energy_score`

#### `CandidateClip`

- `id`
- `job_id`
- `start_ms`
- `end_ms`
- `hook_score`
- `semantic_score`
- `audio_score`
- `visual_score`
- `llm_score`
- `final_score`
- `duplicate_group`
- `topic_cluster`
- `length_bucket`
- `rationale`

#### `EditPlan`

- `id`
- `job_id`
- `candidate_clip_id`
- `headline`
- `caption_style`
- `crop_mode`
- `silence_trim_level`
- `broll_mode`
- `cut_map`
- `timewarp_map`
- `render_spec_version`

#### `RenderVariant`

- `id`
- `job_id`
- `edit_plan_id`
- `variant_key`
- `render_backend`
- `render_backend_version`
- `asset_ref`
- `preview_asset_ref`
- `manifest_ref`
- `qa_status`

#### `RenderAttempt`

- `id`
- `render_variant_id`
- `attempt_no`
- `render_backend`
- `render_backend_version`
- `input_asset_refs`
- `output_asset_refs`
- `status`
- `error_code`
- `started_at`
- `ended_at`

#### `PostDraft`

- `id`
- `render_variant_id`
- `platform`
- `title`
- `caption`
- `hashtags`
- `scheduled_at`
- `status`

#### `QaRun`

- `id`
- `render_variant_id`
- `attempt_no`
- `status`
- `started_at`
- `ended_at`

#### `QaFinding`

- `id`
- `qa_run_id`
- `check_name`
- `severity`
- `reason_code`
- `measured_value`
- `threshold_value`
- `artifact_ref`
- `timecode_start_ms`
- `timecode_end_ms`

#### `ApprovalDecision`

- `id`
- `job_id`
- `gate_name`
- `subject_type`
- `subject_id`
- `actor`
- `decision`
- `reason`
- `approved_payload_snapshot`
- `approved_payload_checksum`
- `created_at`

#### `PublishIntent`

- `id`
- `render_variant_id`
- `post_draft_id`
- `platform_account_id`
- `scheduled_at`
- `idempotency_key`
- `approved_payload_snapshot`
- `approved_payload_checksum`
- `status`

#### `PublishAttempt`

- `id`
- `publish_intent_id`
- `attempt_no`
- `external_post_id`
- `external_status`
- `status`
- `error_code`
- `started_at`
- `ended_at`

#### `PlatformPost`

- `id`
- `publish_intent_id`
- `external_post_id`
- `platform`
- `published_at`
- `post_url`

#### `MetricsSnapshot`

- `id`
- `platform_post_id`
- `window_name`
- `status`
- `provider`
- `provider_version`
- `source_payload_ref`
- `fetched_at`
- `views`
- `avg_watch_time`
- `completion_rate`
- `opening_hold_rate`
- `shares`
- `comments`

#### `ExportPackage`

- `id`
- `render_variant_id`
- `platform`
- `manifest_ref`
- `status`
- `approved_at`
- `delivered_at`

## 9. Public Contracts

### `VideoIngestRequest`

```json
{
  "uploaded_asset_id": "asset_123",
  "approved_import_id": null,
  "brand_profile_id": "brand_001",
  "rights_attestation": true,
  "target_platforms": ["youtube_shorts"],
  "target_final_clip_count": 4,
  "publish_mode": "approval_gated"
}
```

### `TranscriptSegment`

```json
{
  "id": "seg_001",
  "job_id": "job_001",
  "start_ms": 45200,
  "end_ms": 51900,
  "speaker": "spk_01",
  "text": "The real mistake is starting too slow.",
  "pause_before_ms": 180,
  "pause_after_ms": 90,
  "energy_score": 0.72
}
```

### `CandidateClip`

```json
{
  "id": "cand_001",
  "job_id": "job_001",
  "start_ms": 45000,
  "end_ms": 67000,
  "hook_score": 0.86,
  "semantic_score": 0.81,
  "audio_score": 0.63,
  "visual_score": 0.55,
  "llm_score": 0.79,
  "final_score": 0.77,
  "duplicate_group": "hook_speed_01",
  "topic_cluster": "retention_hook",
  "length_bucket": "15_25",
  "rationale": {
    "why_it_works": "clear pain statement lands in first second",
    "risks": ["minor_crop_risk"]
  }
}
```

### `EditPlan`

```json
{
  "id": "plan_001",
  "job_id": "job_001",
  "candidate_clip_id": "cand_001",
  "headline": "This kills retention",
  "caption_style": "bold_bottom",
  "crop_mode": "active_speaker",
  "silence_trim_level": "medium",
  "broll_mode": "off",
  "cut_map": [
    {"src_start_ms": 45000, "src_end_ms": 67000, "dst_start_ms": 0, "dst_end_ms": 21400}
  ],
  "timewarp_map": [
    {"src_start_ms": 47000, "src_end_ms": 47800, "speed": 1.15}
  ]
}
```

### `PostDraft`

```json
{
  "render_variant_id": "rv_001",
  "platform": "youtube_shorts",
  "title": "The mistake that kills retention",
  "caption": "Fast hook, faster payoff.",
  "hashtags": ["#youtubeshorts", "#contentstrategy"],
  "scheduled_at": "2026-04-07T09:00:00Z",
  "approval_required": true
}
```

### `ExportPackage`

```json
{
  "render_variant_id": "rv_001",
  "platform": "instagram_reels",
  "artifacts": [
    {"kind": "video", "asset_ref": "s3://exports/rv_001_master.mp4"},
    {"kind": "caption_file", "asset_ref": "s3://exports/rv_001.srt"},
    {"kind": "metadata", "asset_ref": "s3://exports/rv_001-instagram.json"}
  ],
  "approval_required": true
}
```

### `FeedbackEvent`

```json
{
  "platform_post_id": "post_001",
  "window_name": "24h",
  "opening_hold_rate": 0.71,
  "completion_rate": 0.42,
  "avg_watch_time": 18.4,
  "views": 12432
}
```

## 10. Pipeline

### Stage 1: Intake and quality gate

Checks:

- rights attestation present
- supported duration
- supported language
- audio quality above minimum threshold
- content type matches spoken-video scope
- source ownership or approved-import provenance is present

Outcomes:

- `accepted`
- `rejected_out_of_scope`
- `manual_review_required`

### Stage 2: Ingest

Outputs:

- canonical source asset
- normalized audio track
- proxy video
- preview thumbnails

### Stage 3: Transcription

Requirements:

- word-level timestamps mandatory
- segment aggregation mandatory
- diarization optional but preferred

### Stage 4: Feature extraction

Minimum required features:

- transcript turns
- pause spans
- audio energy
- scene boundaries
- active speaker signal
- crop risk signal

### Stage 5: Candidate generation

Rules:

- create `30-80` candidates
- allow overlaps
- anchor generation on transcript turns, pauses, scene changes, and semantic pivots
- shortlist size is an internal policy target, not a user-facing promise

### Stage 6: Ranking and diversification

Rules:

- rank with hybrid score
- LLM is one feature, not the final truth
- diversification is mandatory

Diversification constraints:

- maximum one top candidate per `duplicate_group` before fill pass
- maintain topic diversity across shortlist
- maintain length-bucket diversity where possible

Output:

- `5-8` shortlisted candidates

### Stage 7: Preview-first review

Rules:

- generate preview renders for shortlisted candidates
- human reviewer selects up to `target_final_clip_count` clips for final render
- rejected previews store reason codes

### Stage 8: Final render

Required edits:

- `9:16` reframe
- captions
- opening overlay
- silence tightening

Optional edits:

- B-roll only when comprehension improves
- music only when allowed by brand policy

### Stage 9: QA

Deterministic checks:

- no mid-word cuts
- subtitle timing valid
- subtitle safe zone valid
- output duration valid
- no duplicate final clips

Advisory LLM checks:

- hook clarity
- context completeness
- brand consistency
- misleading copy

QA outcomes:

- `pass`
- `regenerate_once`
- `manual_salvage_required`
- `reject`

Regen rule:

- maximum one auto-regenerate pass per clip

### Stage 10: Publish approval

- user edits title, caption, hashtags, destination, and schedule if needed
- user chooses destination account
- system materializes immutable approved payload snapshot
- user approves final payload snapshot
- any material change after approval requires re-approval

### Stage 11: Publish and metrics

- create draft or scheduled post on YouTube Shorts
- create export packages for TikTok and Instagram when requested
- fetch metric windows at `1h`, `24h`, `72h`, `7d`
- write snapshots with lineage back to render variant and scoring policy
- metrics backfill is asynchronous and must not block publish completion

## 11. Publishing Model

### V1 destination support

- direct publish or draft: YouTube Shorts only
- export package only: TikTok, Instagram Reels

### Idempotency rules

- one unique `PublishIntent` per `render_variant + platform_account + scheduled_at`
- retries create new `PublishAttempt`
- external platform IDs are bound once and reused
- terminal publish states cannot be retried without explicit user action
- only one active `StageRun` may exist per `(job_id, stage_name)`
- all external side effects must be driven from durable records, not transient worker memory

### Export package contract

- one `ExportPackage` is created per `render_variant + export_platform`
- package includes artifact manifest, metadata file, and status
- export packages require approval if they are generated from final approved clips
- export package completion means artifacts are assembled and available for manual upload or downstream delivery

## 12. Review Console Requirements

### Minimum UI surface

- job list
- job detail with stage status
- preview player
- shortlist approve/reject actions
- final draft review
- metadata editor
- publish approval log
- failure reason view

### Manual salvage path

If final QA fails, the system must expose:

- timestamps
- transcript
- hook suggestion
- caption draft
- metadata draft
- QA findings and reason codes

## 13. Observability

### Required telemetry

- structured logs with `job_id`, `stage_run_id`, `render_variant_id`, `publish_intent_id`
- stage duration and retry count
- cost per stage and per approved clip
- worker error class
- lease conflicts and duplicate-claim prevention events

### Required dashboards

- job throughput
- preview-to-approved conversion
- QA failure distribution
- publish success rate
- cost per approved clip
- score-to-performance correlation

### Alerts

- publish failures
- repeated render failures
- repeated transcription failures
- repeated lease-expiry or duplicate-stage conflicts
- analytics ingestion lag
- cost spike beyond configured threshold

## 14. Security and Compliance

- encrypt platform credentials at rest
- keep audit log for all approvals and publish actions
- redact secrets and private URLs from logs
- apply retention policy to source media and generated artifacts
- restrict approved imports to owned or authorized content only

## 15. Offline Evaluation

### Mandatory before optimization changes

- maintain frozen eval set of `20-50` source videos
- maintain human labels for accepted and rejected clip candidates
- compare ranking and prompt changes offline before pilot rollout
- no scoring policy change without benchmark comparison artifact

### Regression gate

- no ranking or prompt change may ship if it degrades benchmark quality without explicit approval

## 16. Build Order

1. Build control plane, storage, and DB-backed job state machine.
2. Implement intake gate, ingest worker, and transcription worker.
3. Implement metrics schema, offline eval harness, reason codes, and artifact lineage.
4. Implement feature extraction and candidate generation.
5. Implement hybrid ranking and diversification.
6. Implement preview rendering and shortlist review console.
7. Implement final rendering, `QaRun`, `QaFinding`, and deterministic QA.
8. Implement approved payload snapshot, publish intent, publish attempt, export package contract, and YouTube draft/schedule adapter.
9. Implement analytics snapshots and async metrics backfill.

## 17. Deferred to Later Phases

- TikTok and Instagram direct publishing
- multi-brand support
- agency workflows
- self-serve onboarding
- auto-weight tuning
- bandit optimization
- advanced trend-conditioned ranking

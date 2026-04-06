# AI Shorts Engine v1 Worker Contracts

## Purpose

- This document turns the execution model in [specification.md](/Users/grisaavdeev/Downloads/thumbnails/projects/2026-04-04-ai-shorts-engine/specification.md) into concrete worker-stage contracts.
- v1 runs as one control-plane app plus one worker runtime with multiple worker groups.
- All stage execution is DB-backed and outbox-driven.

## Global Execution Rules

- Only one active `StageRun` may exist per `(job_id, stage_name)`.
- Workers must claim a lease before running and renew it while work is active.
- All stage side effects must be derived from durable DB rows, never transient memory.
- Stage transitions use compare-and-swap semantics on `job.version` and the relevant execution record.
- Preview-first review is mandatory. Final renders do not start until shortlist approval completes.
- Publish does not start until:
  - final QA passed
  - final approval exists
  - approved payload snapshot is frozen and current
- Auto-regenerate is limited to one pass per final render variant.
- Export creation is separate from direct publish and is idempotent per `(render_variant, platform)`.

## Worker Groups

- `ingest-worker`
- `transcript-worker`
- `feature-worker`
- `ranking-worker`
- `preview-render-worker`
- `final-render-worker`
- `qa-worker`
- `publish-worker`
- `metrics-worker`

## StageRun-Backed Contracts

### `intake`

- Trigger:
  - `POST /jobs` creates the initial job and config snapshot.
- Claim:
  - orchestrator creates `StageRun(stage_name = intake, status = queued)`
  - worker claims by setting `claimed/running` with a lease token
- Reads:
  - `job`
  - `job_config_snapshot`
  - `source_video`
  - `source_video_artifact`
- Required checks:
  - rights attestation present
  - supported duration
  - supported language
  - minimum audio quality
  - spoken-video scope match
  - ownership or approved-import provenance
- Writes:
  - `source_video.ingest_status`
  - `job_status_transition`
  - `outbox_event` for `ingest` or manual review
- Terminal outcomes:
  - `accepted`
  - `manual_review_required`
  - `rejected_out_of_scope`
- Next events:
  - accepted -> queue `ingest`
  - manual review -> set job to `awaiting_manual_review`
  - rejected -> set job to `failed` or `cancelled` based on operator policy

### `ingest`

- Trigger:
  - accepted intake
- Reads:
  - source asset via `source_video_artifact(role='source_asset')`
  - `brand_profile`
- Writes:
  - keep `source_video.canonical_asset_id` pinned to the original owned source asset
  - normalized media via `source_video_artifact`:
    - `normalized_audio`
    - `proxy_video`
    - `canonical_video` when normalized video exists
    - `thumbnails`
  - `stage_run_artifact` for logs or diagnostics
  - `outbox_event` for `transcript`
- Retryable failures:
  - transient storage or transcoding errors
- Terminal failures:
  - corrupted media
  - unsupported codec after normalization policy is exhausted

### `transcript`

- Trigger:
  - completed ingest
- Reads:
  - original source asset via `source_video_artifact(role='source_asset')` when provenance context is needed
  - normalized audio via `source_video_artifact(role='normalized_audio')`
- Writes:
  - `transcript_revision`
  - `transcript_word`
  - `transcript_segment`
  - raw ASR payload to `stage_run_artifact`
  - `outbox_event` for `feature_extract`
- Preconditions:
  - word timestamps are mandatory
- Retryable failures:
  - ASR provider timeout or transient quota issue
- Terminal failures:
  - no usable transcript produced

### `feature_extract`

- Trigger:
  - current transcript revision available
- Reads:
  - current transcript revision
  - normalized video via `source_video_artifact(role='canonical_video')` or `proxy_video`
  - normalized audio via `source_video_artifact(role='normalized_audio')`
- Writes:
  - transcript turn boundaries normalized for scoring
  - audio energy features for each relevant segment window
  - pause, scene, crop-risk, and active-speaker tracks to `stage_run_artifact`
  - stage cost and diagnostic metadata
  - `outbox_event` for `ranking`
- Retryable failures:
  - temporary media analysis failures
- Terminal failures:
  - source media unreadable after ingest

### `ranking`

- Trigger:
  - features available
- Reads:
  - current transcript revision
  - extracted feature artifacts
  - job config and scoring policy version
- Writes:
  - `candidate_set`
  - `candidate_clip` rows for `30-80` candidates
  - `outbox_event` for `preview_render`
  - coarse job state to `awaiting_shortlist_review` after previews are ready
- Rules:
  - LLM score is one feature, not the final decision
  - diversification is mandatory
  - shortlist target is internal policy, not a hard external promise
- Terminal failures:
  - fewer than the minimum candidate set after policy fallback

### `preview_render`

- Trigger:
  - current ranked candidate set exists
- Reads:
  - top candidates from the current candidate set
  - source media artifacts
  - brand defaults
- Writes:
  - one preview `edit_plan` and one preview `render_variant` per shortlisted candidate
  - `render_attempt` rows and preview artifacts
  - `outbox_event` for review console refresh
- Rules:
  - previews are cheap and fast
  - previews may omit optional polish, but must preserve timing, captions, and framing intent

## Control-Plane Review Gates

The contracts below are part of the execution graph, but they are not separate `stage_name` values in `StageRun`. They are API-driven gates that read durable outputs from the worker stages and emit the next outbox event.

### `shortlist_review`

- Trigger:
  - reviewer action via `POST /jobs/{id}/shortlist-decisions`
- Reads:
  - preview `render_variant`
  - `candidate_clip`
- Writes:
  - `shortlist_decision`
  - job status transition to `rendering_finals` or `completed_insufficient_output`
  - `outbox_event` for `final_render` when at least one preview is approved
- Rules:
  - reviewer selects `5-8` down to at most `target_final_clip_count`
  - rejected previews must store reason codes

### `final_render`

- Trigger:
  - shortlist approval completed
- Reads:
  - approved preview decisions
  - current `edit_plan` or derived final plan
  - source media artifacts
  - brand defaults
- Writes:
  - final `edit_plan` version if needed
  - final `render_variant`
  - `render_attempt`
  - final video, subtitles, manifest, and evidence artifacts
  - `outbox_event` for `qa`
- Required edits:
  - `9:16` reframe
  - captions
  - opening overlay
  - silence tightening
- Optional edits:
  - B-roll only when it improves comprehension
  - music only when brand policy allows it

### `qa`

- Trigger:
  - final render completed
- Reads:
  - final `render_variant`
  - final artifacts
  - transcript revision
- Writes:
  - `qa_run`
  - `qa_finding`
  - `render_variant.qa_status`
  - job state transition
  - `outbox_event` for regenerate, final approval, or salvage handling
- Deterministic checks:
  - no mid-word cuts
  - subtitle timing valid
  - subtitle safe zone valid
  - output duration valid
  - no duplicate finals
- Advisory checks:
  - hook clarity
  - context completeness
  - brand consistency
  - misleading copy
- Outcomes:
  - `pass`
  - `regenerate_once`
  - `manual_salvage_required`
  - `reject`
- Rules:
  - only one auto-regenerate pass is allowed
  - `manual_salvage_required` moves the job to `qa_manual_salvage_required`

### `final_approval`

- Trigger:
  - reviewer edits a `post_draft` and approves via API
- Reads:
  - final `render_variant`
  - current `post_draft`
  - selected `platform_account`
- Writes:
  - `approval_payload_snapshot`
  - `final_approval`
  - publish-ready audit trail and operator-visible approval state
- Rules:
  - payload freeze includes render asset, title, caption, hashtags, account, and schedule
  - any subsequent material draft edit invalidates current approval
  - approval must not transition the job back into a pre-approval state

## Supporting Async Contracts

### `publish`

- Trigger:
  - `publish_intent` created from a valid approved snapshot
- Reads:
  - `publish_intent`
  - `approval_payload_snapshot`
  - destination account
  - final render artifacts
- Writes:
  - `publish_attempt`
  - `publish_intent_transition`
  - `platform_post` when external ID exists
  - job state transitions
  - `outbox_event` for `metrics`
- Rules:
  - direct publish or draft only for `youtube_shorts`
  - publish is idempotent by durable intent record, not by transient worker behavior
  - terminal states require explicit operator action for retry

### `export_package`

- Trigger:
  - final approved clip exists and requested platform is export-only
- Reads:
  - final render artifacts
  - current approved payload snapshot
- Writes:
  - `export_package`
  - manifest artifact
- Rules:
  - one package per `(render_variant, platform)`
  - package assembly must not call external publish APIs

### `metrics`

- Trigger:
  - `platform_post` exists
  - scheduled windows at `1h`, `24h`, `72h`, `7d`
- Reads:
  - `platform_post`
  - provider credentials if required
- Writes:
  - `metrics_snapshot`
  - raw provider payload artifact
  - job transition to `completed`, `completed_partial`, or remain unchanged if more windows are pending
- Rules:
  - metrics backfill is asynchronous and does not block publish completion
  - distinguish unavailable metrics from zero-valued metrics through `metrics_snapshot.status`

## Orchestrator Contract

- The orchestrator owns:
  - stage creation
  - retry scheduling
  - state transitions
  - lease timeout recovery
  - outbox dispatch
- It must enforce:
  - monotonic state within a single branch
  - no duplicate active stage runs
  - no publish without final approval
  - no final render without shortlist approval

## Retry Policy

- Retryable failures mark the current `StageRun` as `failed_retryable`, preserve its artifacts, and create a new `StageRun` with incremented `attempt_no`.
- Terminal failures end the current branch and must write a reason code.
- Publish retries create a new `PublishAttempt`, not a new `PublishIntent`.
- QA regenerate creates a new `RenderAttempt` and new `QaRun`, but keeps the same logical final `render_variant`.

## Manual Paths

- Intake manual review:
  - job enters `awaiting_manual_review`
  - operator resolves via API to resume or cancel
- QA salvage:
  - job enters `qa_manual_salvage_required`
  - review console must expose timestamps, transcript, draft copy, and findings
  - operator can continue to a salvage render path or close as `completed_partial`

## Required Telemetry

- Structured logs must include:
  - `job_id`
  - `stage_run_id`
  - `render_variant_id`
  - `publish_intent_id`
- Emit metrics for:
  - stage duration
  - retry count
  - lease conflicts
  - duplicate-claim prevention
  - cost per stage
  - cost per approved clip

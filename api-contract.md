# AI Shorts Engine v1 API Contract

## Purpose

- This document defines the public control-plane API for the v1 engine.
- The API serves the review console and trusted internal operators.
- Worker-to-worker mutations are internal and must not be modeled as public CRUD endpoints.

## Conventions

- Base path: `/api/v1`
- Response format: JSON
- Pagination: cursor-based `ListResponse[T] { items, next_cursor }`
- Idempotency header: `Idempotency-Key` for all required create or action endpoints
- Time format: RFC 3339 UTC
- Async work returns `202 Accepted` with current job or intent state
- Mutating lifecycle operations use `POST .../actions/...` unless the resource is explicitly mutable by design

## Auth and Roles

- Web console auth: `OIDC + httpOnly Secure session cookie`
- Worker auth: service JWT with worker-only scopes
- Roles:
  - `viewer`: read-only access
  - `reviewer`: shortlist and final approval actions
  - `operator`: retry, cancel, scheduling, publish dispatch actions
  - `admin`: manage brand profiles and platform accounts

## Resource Map

### Uploads

#### `POST /uploads`

- Purpose: create an upload session before ingest.
- Request:
  - `filename`
  - `content_type`
  - `size_bytes`
  - `sha256` optional
- Response:
  - `upload_id`
  - `upload_url` or multipart instructions
  - `expires_at`
  - `status`
- Auth: `admin`, `operator`
- Idempotency: optional

#### `POST /uploads/{upload_id}/complete`

- Purpose: finalize upload and materialize the immutable asset object.
- Request:
  - `sha256`
  - `size_bytes`
- Response:
  - `upload_id`
  - `artifact_id`
  - `status`
- Idempotency: required

#### `GET /uploads/{upload_id}`

- Purpose: poll upload completion state.

### Brand Profiles

#### `GET /brand-profiles`

- Purpose: list available brand configs.

#### `POST /brand-profiles`

- Purpose: create a brand profile.
- Request fields:
  - `name`
  - `language`
  - `caption_style_defaults`
  - `overlay_policy`
  - `music_policy`
  - `platform_defaults`
- Auth: `admin`

#### `GET /brand-profiles/{brand_profile_id}`

- Purpose: fetch a single brand profile.

#### `PATCH /brand-profiles/{brand_profile_id}`

- Purpose: mutate mutable brand config defaults.
- Auth: `admin`

### Platform Accounts

#### `GET /platform-accounts`

- Purpose: list destination accounts.

#### `POST /platform-accounts`

- Purpose: register a destination account.
- Request fields:
  - `brand_profile_id`
  - `platform`
  - `channel_name`
  - `credential_payload`
  - `capabilities_json`
- Response excludes secrets and returns only connection metadata.
- Auth: `admin`

#### `GET /platform-accounts/{platform_account_id}`

- Purpose: fetch one destination account.

#### `PATCH /platform-accounts/{platform_account_id}`

- Purpose: pause, re-enable, or rotate metadata for a destination account.
- Auth: `admin`

### Source Videos

#### `POST /source-videos`

- Purpose: register an uploaded or approved-import asset as a source video.
- Request:
  - `artifact_id` or `approved_import_id`
  - `brand_profile_id`
  - `rights_attestation`
  - `source_type`
  - `provenance` when `source_type = approved_import`
- Response:
  - minimum stable fields:
    - `id`
    - `ingest_status`
  - current implementation also returns the created source-video record fields
  - `ingest_status`
- Auth: `operator`, `admin`

#### `GET /source-videos/{source_video_id}`

- Purpose: fetch intake state and attached artifacts.
- Response:
  - base source-video fields
  - `artifacts`: latest attached artifact per role
    - `source_asset`
    - `canonical_video`
    - `proxy_video`
    - `normalized_audio`
    - `thumbnails`
  - each artifact entry includes:
    - `artifact_id`
    - `role`
    - `kind`
    - `storage_key`
    - `mime_type`
    - `size_bytes`
    - `sha256`
    - `metadata_jsonb`
    - `attached_at`
  - `provenance`: created-order provenance entries for approved imports or manual attestation evidence

### Jobs

#### `POST /jobs`

- Purpose: create a new processing job.
- Request:
  - `source_video_id`
  - `target_platforms`
  - `target_final_clip_count`
  - `publish_mode = approval_gated`
- Response:
  - `202 JobAccepted`
  - `job_id`
  - `status`
  - `current_job_config_snapshot_id`
- Auth: `operator`, `admin`
- Idempotency: required
- Natural dedupe key:
  - `source_video_id + job_config_checksum`

#### `GET /jobs`

- Purpose: list jobs with filters.
- Recommended filters:
  - `status`
  - `brand_profile_id`
  - `created_after`
  - `created_before`

#### `GET /jobs/{job_id}`

- Purpose: job detail for the review console.
- Response includes:
  - coarse job state
  - current config snapshot
  - stage summary
  - output counts
  - current approval state

#### `GET /jobs/{job_id}/stage-runs`

- Purpose: stage execution history for debugging and ops.
- Read-only.

#### `POST /jobs/{job_id}/actions/resolve-intake-review`

- Purpose: resume or cancel a job blocked on intake review.
- Request:
  - `decision`: `approve` or `cancel`
  - `reason_code`
- Auth: `reviewer`, `operator`
- Idempotency: required

#### `POST /jobs/{job_id}/shortlist-decisions`

- Purpose: persist Gate 1 preview approvals and rejections.
- Request:
  - `decisions: [{ preview_render_variant_id, decision, reason_code }]`
- Response:
  - accepted decisions
  - resulting shortlist count
  - next job state
- Auth: `reviewer`
- Idempotency: required

#### `POST /jobs/{job_id}/actions/complete-partial`

- Purpose: explicitly close a salvage branch as `completed_partial`.
- Auth: `reviewer`, `operator`
- Idempotency: required

#### `POST /jobs/{job_id}/actions/resume-manual-salvage`

- Purpose: resume a job from `qa_manual_salvage_required` back into the final render branch after reviewer intervention.
- Request:
  - `reason`
- Auth: `reviewer`, `operator`
- Idempotency: required

#### `GET /jobs/{job_id}/approval-history`

- Purpose: fetch a unified read model of shortlist and final approval decisions for the review console.
- Notes:
  - read-only projection
  - may be backed by `shortlist_decision`, `approval_payload_snapshot`, and `final_approval`

### Transcripts

#### `GET /jobs/{job_id}/transcript-segments`

- Purpose: fetch the current transcript revision at segment granularity.

#### `GET /jobs/{job_id}/transcript-words`

- Purpose: fetch word-level timestamps for debugging and cut inspection.

### Candidate Clips

#### `GET /jobs/{job_id}/candidate-clips`

- Purpose: list ranked candidates from the current candidate set.
- Filters:
  - `length_bucket`
  - `topic_cluster`
  - `duplicate_group`

#### `GET /candidate-clips/{candidate_clip_id}`

- Purpose: fetch one candidate and its rationale.

### Render Variants

#### `GET /jobs/{job_id}/render-variants`

- Purpose: list preview and final renders for a job.

#### `GET /render-variants/{render_variant_id}`

- Purpose: fetch one render variant, current artifacts, and QA state.

#### `GET /render-variants/{render_variant_id}/edit-plan`

- Purpose: fetch the current edit plan and salvage context for a render variant.

### QA

#### `GET /render-variants/{render_variant_id}/qa-runs`

- Purpose: list QA attempts for a render variant.

#### `GET /qa-runs/{qa_run_id}/findings`

- Purpose: fetch deterministic findings and advisory critique outputs.

#### `GET /jobs/{job_id}/manual-salvage-package`

- Purpose: fetch the review payload required for manual salvage.
- Response must include:
  - timestamps
  - transcript excerpt
  - current hook suggestion
  - caption draft
  - metadata draft
  - QA findings and reason codes

### Post Drafts and Final Approval

#### `GET /render-variants/{render_variant_id}/post-drafts`

- Purpose: fetch per-platform metadata drafts.

#### `PATCH /post-drafts/{post_draft_id}`

- Purpose: mutate draft metadata before final approval.
- Mutable fields only:
  - `title`
  - `caption`
  - `hashtags`
  - `platform_account_id`
  - `scheduled_at`
- Rules:
  - material edits increment draft version
  - material edits invalidate existing final approval
- Auth: `reviewer`, `operator`

#### `POST /post-drafts/{post_draft_id}/actions/approve-final`

- Purpose: Gate 2 approval of the exact publish payload.
- Request:
  - optional `reason`
- Response:
  - `approval_payload_snapshot_id`
  - `checksum`
  - `publish_ready = true`
- Auth: `reviewer`
- Idempotency: required

#### `POST /post-drafts/{post_draft_id}/actions/revoke-approval`

- Purpose: explicitly revoke a prior final approval.
- Auth: `reviewer`
- Idempotency: required

### Publish Intents

#### `POST /publish-intents`

- Purpose: create a durable publish command from an approved final payload.
- Request:
  - `post_draft_id`
- Preconditions:
  - approved payload snapshot exists and matches current draft version
- Response:
  - `publish_intent_id`
  - `status`
  - `platform_account_id`
  - `scheduled_at`
- Auth: `operator`
- Idempotency: required

#### `GET /publish-intents/{publish_intent_id}`

- Purpose: fetch publish state, attempts, and audit trail summary.

#### `POST /publish-intents/{publish_intent_id}/actions/retry`

- Purpose: re-dispatch a retryable publish intent.
- Preconditions:
  - current status is retryable terminal
  - explicit operator action
- Auth: `operator`
- Idempotency: required

#### `POST /publish-intents/{publish_intent_id}/actions/cancel`

- Purpose: cancel a publish before terminal completion.
- Auth: `operator`
- Idempotency: required

### Platform Posts and Metrics

#### `GET /publish-intents/{publish_intent_id}/platform-post`

- Purpose: fetch the bound external post created by a publish intent.

#### `GET /platform-posts/{platform_post_id}/metrics-snapshots`

- Purpose: fetch metric windows and lineage.

### Export Packages

#### `GET /render-variants/{render_variant_id}/export-packages`

- Purpose: fetch export-only deliverables for TikTok and Instagram.
- Notes:
  - export packages are read-only through the public API
  - creation is internal and follows final approval of the master clip

## Models

### Shared Envelopes

#### `ListResponse[T]`

```json
{
  "items": [],
  "next_cursor": "cursor_123"
}
```

#### `ErrorResponse`

```json
{
  "code": "state_conflict",
  "message": "Final approval is required before publish intent creation.",
  "details": {},
  "request_id": "req_123",
  "retryable": false
}
```

### Canonical Resource Shapes

- `VideoIngestRequest`
- `TranscriptSegmentOut`
- `TranscriptWordOut`
- `CandidateClipOut`
- `EditPlanOut`
- `ManualSalvagePackageOut`
- `RenderVariantOut`
- `QaRunOut`
- `QaFindingOut`
- `PostDraftOut`
- `ApprovalHistoryOut`
- `PublishIntentOut`
- `PlatformPostOut`
- `MetricsSnapshotOut`
- `ExportPackageOut`

All response models must mirror the terminology already fixed in [specification.md](/Users/grisaavdeev/Downloads/thumbnails/projects/2026-04-04-ai-shorts-engine/specification.md) and [db-schema.md](/Users/grisaavdeev/Downloads/thumbnails/projects/2026-04-04-ai-shorts-engine/db-schema.md).

## Sync vs Async Boundaries

- Synchronous:
- upload session creation
  - upload completion
  - brand and platform account writes
  - source video registration
  - post draft metadata edit
  - approval, revoke, intake resolution, salvage resume, and complete-partial actions
  - publish intent create, retry, cancel
- Asynchronous:
  - ingest
  - transcription
  - feature extraction
  - candidate generation and ranking
  - preview render
  - final render
  - QA
  - publish dispatch
  - metrics backfill

## Error Codes

- `validation_error`
- `unauthorized`
- `forbidden`
- `not_found`
- `state_conflict`
- `approval_required`
- `approval_invalidated`
- `idempotency_conflict`
- `out_of_scope_rejected`
- `manual_review_required`
- `lease_conflict`
- `external_provider_retryable`
- `external_provider_terminal`

## API Invariants

- Public API must not expose generic status mutation on `Job`, `StageRun`, `QaRun`, `PublishAttempt`, or `ExportPackage`.
- Public API must not allow publish without a frozen approved payload snapshot.
- Final approval must freeze the exact render, metadata, destination account, and schedule.
- `PATCH /post-drafts/{id}` is the only ordinary mutable content endpoint in v1.
- All list endpoints must have deterministic sort order, defaulting to newest-first for jobs and created-order for artifacts within a parent resource.

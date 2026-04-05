# AI Shorts Engine v1 DB Schema

## Purpose

- This document decomposes [specification.md](/Users/grisaavdeev/Downloads/thumbnails/projects/2026-04-04-ai-shorts-engine/specification.md) into an implementation-ready relational schema.
- `Postgres 16` is the primary store for state, lineage, and audit records.
- `SQLAlchemy 2.0` models and `Alembic` migrations must follow this document.
- Heavy artifacts live in object storage; the database stores immutable references and relational metadata.

## Global Rules

- `tenant_id` is out of scope for v1.
- Use `uuid` primary keys unless a table explicitly benefits from a composite key.
- Use `timestamptz` for all wall-clock timestamps and `bigint` milliseconds for media time ranges.
- Use `jsonb` only for bounded blobs that are not primary filter keys.
- Artifact payloads are immutable. New attempts create new artifact rows or new link rows instead of overwriting previous refs.
- State transitions must be auditable. Mutable rows are allowed only where the contract explicitly permits mutation.

## Contexts

### `config_assets`

#### `artifact_object`

- Purpose: immutable registry for media, manifests, evidence, and provider payloads.
- Columns:
  - `id`
  - `storage_key`
  - `kind`
  - `sha256`
  - `size_bytes`
  - `mime_type`
  - `metadata_jsonb`
  - `created_at`
- Constraints:
  - `unique(storage_key)`
  - `unique(sha256, size_bytes, kind)` is optional dedupe optimization, not a hard v1 requirement.

#### `brand_profile`

- Columns:
  - `id`
  - `name`
  - `language`
  - `caption_style_defaults`
  - `overlay_policy`
  - `music_policy`
  - `platform_defaults`
  - `created_at`
  - `updated_at`

#### `platform_account`

- Columns:
  - `id`
  - `brand_profile_id`
  - `platform`
  - `channel_name`
  - `connection_ref`
  - `capabilities_jsonb`
  - `status`
  - `created_at`
  - `updated_at`
- Constraints:
  - `fk(platform_account.brand_profile_id -> brand_profile.id)`
  - `unique(brand_profile_id, platform, channel_name)`

#### `source_video`

- Columns:
  - `id`
  - `brand_profile_id`
  - `canonical_asset_id`
  - `source_type`
  - `duration_ms`
  - `language`
  - `speaker_count_estimate`
  - `rights_attestation`
  - `ingest_status`
  - `created_at`
  - `updated_at`
- Constraints:
  - `fk(source_video.brand_profile_id -> brand_profile.id)`
  - `fk(source_video.canonical_asset_id -> artifact_object.id)`

#### `source_video_provenance`

- Purpose: persist ownership or approved-import provenance required by intake policy.
- Columns:
  - `id`
  - `source_video_id`
  - `provenance_type`
  - `provider`
  - `source_uri`
  - `evidence_artifact_id`
  - `approved_by`
  - `approved_at`
  - `created_at`
- Constraints:
  - `fk(source_video_id -> source_video.id)`
  - `fk(evidence_artifact_id -> artifact_object.id)` nullable
- Notes:
  - required for `approved_import`
  - optional for uploaded assets that only rely on `rights_attestation`

#### `source_video_artifact`

- Purpose: attach normalized audio, proxy video, poster frames, waveform, thumbnails.
- Columns:
  - `source_video_id`
  - `artifact_id`
  - `role`
  - `created_at`
- Constraints:
  - `pk(source_video_id, role, artifact_id)`
  - `fk(source_video_id -> source_video.id)`
  - `fk(artifact_id -> artifact_object.id)`

### `job_control`

#### `job`

- Columns:
  - `id`
  - `source_video_id`
  - `brand_profile_id`
  - `target_final_clip_count`
  - `status`
  - `prompt_version`
  - `scoring_policy_version`
  - `version`
  - `created_at`
  - `updated_at`
- Constraints:
  - `fk(source_video_id -> source_video.id)`
  - `fk(brand_profile_id -> brand_profile.id)`
- Notes:
  - the current config snapshot is derived by joining `job_config_snapshot where is_current = true`; v1 does not store a back-reference on `job`.

#### `job_target_platform`

- Columns:
  - `job_id`
  - `platform`
  - `created_at`
- Constraints:
  - `pk(job_id, platform)`
  - `fk(job_id -> job.id)`

#### `job_config_snapshot`

- Purpose: append-only configuration history.
- Columns:
  - `id`
  - `job_id`
  - `version_no`
  - `is_current`
  - `checksum`
  - `target_final_clip_count`
  - `shortlist_target_count`
  - `prompt_version`
  - `scoring_policy_version`
  - `config_jsonb`
  - `created_at`
- Constraints:
  - `fk(job_id -> job.id)`
  - `unique(job_id, version_no)`
  - partial unique current snapshot per job

#### `stage_run`

- Purpose: one durable execution record per stage attempt.
- Columns:
  - `id`
  - `job_id`
  - `stage_name`
  - `attempt_no`
  - `status`
  - `worker_id`
  - `lease_token`
  - `lease_expires_at`
  - `started_at`
  - `ended_at`
  - `error_code`
  - `cost_usd`
  - `created_at`
- Constraints:
  - `fk(job_id -> job.id)`
  - `unique(job_id, stage_name, attempt_no)`
  - partial unique active stage run on `(job_id, stage_name)` where `status in ('queued','claimed','running')`
- Indexes:
  - `(job_id, stage_name, status)`
  - `(lease_expires_at)` for claim sweeps

#### `job_status_transition`

- Purpose: append-only audit trail for coarse job state changes.
- Columns:
  - `id`
  - `job_id`
  - `from_status`
  - `to_status`
  - `stage_run_id`
  - `actor_type`
  - `actor_ref`
  - `reason_code`
  - `created_at`
- Constraints:
  - `fk(job_id -> job.id)`
  - `fk(stage_run_id -> stage_run.id)` nullable

#### `outbox_event`

- Purpose: durable handoff for worker triggers and side effects.
- Columns:
  - `id`
  - `aggregate_type`
  - `aggregate_id`
  - `event_type`
  - `dedupe_key`
  - `payload_jsonb`
  - `status`
  - `available_at`
  - `claimed_at`
  - `processed_at`
  - `created_at`
- Constraints:
  - `unique(dedupe_key)`
- Indexes:
  - `(status, available_at)`

### `transcription_analysis`

#### `transcript_revision`

- Purpose: versioned ASR result set for a job.
- Columns:
  - `id`
  - `job_id`
  - `stage_run_id`
  - `version_no`
  - `is_current`
  - `provider`
  - `provider_version`
  - `created_at`
- Constraints:
  - `fk(job_id -> job.id)`
  - `fk(stage_run_id -> stage_run.id)`
  - `unique(job_id, version_no)`
  - partial unique current revision per job

#### `transcript_word`

- Purpose: word-level timestamps; required for cut safety.
- Columns:
  - `transcript_revision_id`
  - `seq_no`
  - `start_ms`
  - `end_ms`
  - `token`
  - `speaker`
  - `confidence`
- Constraints:
  - `pk(transcript_revision_id, seq_no)`
  - `fk(transcript_revision_id -> transcript_revision.id)`
- Indexes:
  - `(transcript_revision_id, start_ms)`

#### `transcript_segment`

- Purpose: segment-level search and scoring input.
- Columns:
  - `transcript_revision_id`
  - `seq_no`
  - `start_ms`
  - `end_ms`
  - `speaker`
  - `text`
  - `pause_before_ms`
  - `pause_after_ms`
  - `energy_score`
- Constraints:
  - `pk(transcript_revision_id, seq_no)`
  - `fk(transcript_revision_id -> transcript_revision.id)`
- Indexes:
  - `(transcript_revision_id, start_ms)`

#### `stage_run_artifact`

- Purpose: attach raw ASR JSON, scene tracks, pause tracks, crop-risk tracks, or analytics payloads to a stage attempt.
- Columns:
  - `stage_run_id`
  - `artifact_id`
  - `role`
  - `created_at`
- Constraints:
  - `pk(stage_run_id, role, artifact_id)`
  - `fk(stage_run_id -> stage_run.id)`
  - `fk(artifact_id -> artifact_object.id)`

### `selection_rendering`

#### `candidate_set`

- Purpose: versioned output of candidate generation and ranking.
- Columns:
  - `id`
  - `job_id`
  - `stage_run_id`
  - `transcript_revision_id`
  - `version_no`
  - `is_current`
  - `scoring_policy_version`
  - `created_at`
- Constraints:
  - `fk(job_id -> job.id)`
  - `fk(stage_run_id -> stage_run.id)`
  - `fk(transcript_revision_id -> transcript_revision.id)`
  - `unique(job_id, version_no)`
  - partial unique current candidate set per job

#### Offline evaluation support

The v1 schema must support frozen benchmark artifacts before ranking or prompt changes ship.

#### `eval_set`

- Columns:
  - `id`
  - `name`
  - `status`
  - `created_at`

#### `eval_set_member`

- Columns:
  - `eval_set_id`
  - `source_video_id`
  - `created_at`
- Constraints:
  - `pk(eval_set_id, source_video_id)`
  - `fk(eval_set_id -> eval_set.id)`
  - `fk(source_video_id -> source_video.id)`

#### `candidate_label`

- Purpose: human labels for accepted or rejected clip candidates in the eval set.
- Columns:
  - `id`
  - `eval_set_id`
  - `source_video_id`
  - `start_ms`
  - `end_ms`
  - `label`
  - `actor_ref`
  - `notes`
  - `created_at`
- Constraints:
  - `fk(eval_set_id -> eval_set.id)`
  - `fk(source_video_id -> source_video.id)`

#### `benchmark_run`

- Columns:
  - `id`
  - `eval_set_id`
  - `prompt_version`
  - `scoring_policy_version`
  - `artifact_id`
  - `created_at`
- Constraints:
  - `fk(eval_set_id -> eval_set.id)`
  - `fk(artifact_id -> artifact_object.id)` nullable

#### `benchmark_result`

- Columns:
  - `id`
  - `benchmark_run_id`
  - `source_video_id`
  - `metric_name`
  - `metric_value`
  - `created_at`
- Constraints:
  - `fk(benchmark_run_id -> benchmark_run.id)`
  - `fk(source_video_id -> source_video.id)`

#### `candidate_clip`

- Columns:
  - `id`
  - `candidate_set_id`
  - `job_id`
  - `rank_no`
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
  - `rationale_jsonb`
  - `created_at`
- Constraints:
  - `fk(candidate_set_id -> candidate_set.id)`
  - `fk(job_id -> job.id)`
  - `unique(candidate_set_id, rank_no)`
- Indexes:
  - `(job_id, final_score desc)`
  - `(candidate_set_id, duplicate_group)`
  - `(candidate_set_id, topic_cluster)`

#### `edit_plan`

- Purpose: versioned edit instructions derived from a candidate clip.
- Columns:
  - `id`
  - `job_id`
  - `candidate_clip_id`
  - `parent_edit_plan_id`
  - `version_no`
  - `headline`
  - `caption_style`
  - `crop_mode`
  - `silence_trim_level`
  - `broll_mode`
  - `cut_map`
  - `timewarp_map`
  - `render_spec_version`
  - `created_at`
- Constraints:
  - `fk(job_id -> job.id)`
  - `fk(candidate_clip_id -> candidate_clip.id)`
  - `fk(parent_edit_plan_id -> edit_plan.id)` nullable
  - `unique(candidate_clip_id, version_no)`

#### `render_variant`

- Purpose: current logical render target for preview or final output.
- Columns:
  - `id`
  - `job_id`
  - `edit_plan_id`
  - `variant_kind`
  - `variant_key`
  - `render_backend`
  - `render_backend_version`
  - `qa_status`
  - `current_asset_id`
  - `current_preview_asset_id`
  - `current_manifest_id`
  - `created_at`
  - `updated_at`
- Constraints:
  - `fk(job_id -> job.id)`
  - `fk(edit_plan_id -> edit_plan.id)`
  - `fk(current_asset_id -> artifact_object.id)` nullable
  - `fk(current_preview_asset_id -> artifact_object.id)` nullable
  - `fk(current_manifest_id -> artifact_object.id)` nullable
  - `unique(edit_plan_id, variant_kind, variant_key)`
  - `unique(id, job_id)`
- Notes:
  - `variant_kind` should distinguish `preview` and `final`.

#### `render_attempt`

- Columns:
  - `id`
  - `render_variant_id`
  - `attempt_no`
  - `status`
  - `error_code`
  - `render_backend`
  - `render_backend_version`
  - `started_at`
  - `ended_at`
  - `created_at`
- Constraints:
  - `fk(render_variant_id -> render_variant.id)`
  - `unique(render_variant_id, attempt_no)`

#### `render_attempt_artifact`

- Purpose: attach output video, preview video, manifest, subtitle file, evidence frames.
- Columns:
  - `render_attempt_id`
  - `artifact_id`
  - `role`
  - `created_at`
- Constraints:
  - `pk(render_attempt_id, role, artifact_id)`
  - `fk(render_attempt_id -> render_attempt.id)`
  - `fk(artifact_id -> artifact_object.id)`

### `review_delivery`

#### `qa_run`

- Columns:
  - `id`
  - `render_variant_id`
  - `attempt_no`
  - `status`
  - `started_at`
  - `ended_at`
  - `created_at`
- Constraints:
  - `fk(render_variant_id -> render_variant.id)`
  - `unique(render_variant_id, attempt_no)`

#### `qa_finding`

- Columns:
  - `id`
  - `qa_run_id`
  - `check_name`
  - `severity`
  - `reason_code`
  - `measured_value`
  - `threshold_value`
  - `artifact_id`
  - `timecode_start_ms`
  - `timecode_end_ms`
  - `created_at`
- Constraints:
  - `fk(qa_run_id -> qa_run.id)`
  - `fk(artifact_id -> artifact_object.id)` nullable
- Indexes:
  - `(qa_run_id, severity)`
  - `(qa_run_id, reason_code)`

#### `shortlist_decision`

- Purpose: reviewer disposition for preview clips.
- Columns:
  - `id`
  - `job_id`
  - `preview_render_variant_id`
  - `decision_seq_no`
  - `actor_ref`
  - `decision`
  - `reason_code`
  - `created_at`
- Constraints:
  - `fk(job_id -> job.id)`
  - `fk(preview_render_variant_id -> render_variant.id)`
  - `unique(job_id, preview_render_variant_id, decision_seq_no)`
- Notes:
  - append-only audit model; the current reviewer disposition is the latest `decision_seq_no` per preview render variant

#### `post_draft`

- Purpose: mutable draft metadata until final approval freeze.
- Columns:
  - `id`
  - `render_variant_id`
  - `platform`
  - `title`
  - `caption`
  - `hashtags`
  - `platform_account_id`
  - `scheduled_at`
  - `status`
  - `version`
  - `created_at`
  - `updated_at`
- Constraints:
  - `fk(render_variant_id -> render_variant.id)`
  - `fk(platform_account_id -> platform_account.id)` nullable until selected
  - `unique(render_variant_id, platform)`
  - `unique(id, render_variant_id)`

#### `approval_payload_snapshot`

- Purpose: immutable approved payload materialization.
- Columns:
  - `id`
  - `job_id`
  - `render_variant_id`
  - `post_draft_id`
  - `platform_account_id`
  - `post_draft_version`
  - `scheduled_at`
  - `checksum`
  - `payload_jsonb`
  - `created_at`
- Constraints:
  - `fk(job_id -> job.id)`
  - composite fk `(render_variant_id, job_id) -> render_variant(id, job_id)`
  - composite fk `(post_draft_id, render_variant_id) -> post_draft(id, render_variant_id)`
  - `fk(platform_account_id -> platform_account.id)`
  - `unique(id, job_id, render_variant_id, post_draft_id, platform_account_id)`
- Indexes:
  - `(job_id, render_variant_id, post_draft_id, created_at desc)`

#### `final_approval`

- Purpose: append-only audit record for the second approval gate.
- Columns:
  - `id`
  - `job_id`
  - `approval_payload_snapshot_id`
  - `actor_ref`
  - `decision`
  - `reason`
  - `created_at`
- Constraints:
  - `fk(job_id -> job.id)`
  - composite fk `(approval_payload_snapshot_id, job_id) -> approval_payload_snapshot(id, job_id)`
- Notes:
  - if the application needs a compatibility read model similar to the old `ApprovalDecision`, expose it as a DB view or API projection over `shortlist_decision` and `final_approval`, not as a polymorphic write table.

#### `publish_intent`

- Columns:
  - `id`
  - `job_id`
  - `render_variant_id`
  - `post_draft_id`
  - `platform_account_id`
  - `approval_payload_snapshot_id`
  - `delivery_mode`
  - `scheduled_at`
  - `idempotency_key`
  - `status`
  - `created_at`
  - `updated_at`
- Constraints:
  - `fk(job_id -> job.id)`
  - composite fk `(render_variant_id, job_id) -> render_variant(id, job_id)`
  - composite fk `(post_draft_id, render_variant_id) -> post_draft(id, render_variant_id)`
  - `fk(platform_account_id -> platform_account.id)`
  - composite fk `(approval_payload_snapshot_id, job_id, render_variant_id, post_draft_id, platform_account_id) -> approval_payload_snapshot(id, job_id, render_variant_id, post_draft_id, platform_account_id)`
  - `unique(idempotency_key)`
- Indexes:
  - unique partial `(render_variant_id, platform_account_id, delivery_mode)` where `delivery_mode = 'draft'`
  - unique partial `(render_variant_id, platform_account_id, scheduled_at)` where `delivery_mode = 'scheduled'`
- Notes:
  - `delivery_mode` is `draft` or `scheduled` in v1
  - request payload and frozen approval snapshot must resolve to the same `job`, `render_variant`, `post_draft`, destination account, and schedule

#### `publish_attempt`

- Columns:
  - `id`
  - `publish_intent_id`
  - `attempt_no`
  - `external_post_id`
  - `external_status`
  - `status`
  - `error_code`
  - `started_at`
  - `ended_at`
  - `created_at`
- Constraints:
  - `fk(publish_intent_id -> publish_intent.id)`
  - `unique(publish_intent_id, attempt_no)`

#### `publish_intent_transition`

- Purpose: append-only audit trail for publish lifecycle.
- Columns:
  - `id`
  - `publish_intent_id`
  - `publish_attempt_id`
  - `from_status`
  - `to_status`
  - `actor_type`
  - `actor_ref`
  - `reason_code`
  - `created_at`
- Constraints:
  - `fk(publish_intent_id -> publish_intent.id)`
  - `fk(publish_attempt_id -> publish_attempt.id)` nullable

#### `platform_post`

- Columns:
  - `id`
  - `publish_intent_id`
  - `platform`
  - `external_post_id`
  - `published_at`
  - `post_url`
  - `created_at`
- Constraints:
  - `fk(publish_intent_id -> publish_intent.id)`
  - `unique(publish_intent_id)`
  - `unique(platform, external_post_id)`

#### `export_package`

- Purpose: export-only delivery for TikTok and Instagram.
- Columns:
  - `id`
  - `render_variant_id`
  - `platform`
  - `manifest_artifact_id`
  - `status`
  - `approved_at`
  - `delivered_at`
  - `created_at`
- Constraints:
  - `fk(render_variant_id -> render_variant.id)`
  - `fk(manifest_artifact_id -> artifact_object.id)`
  - `unique(render_variant_id, platform)`

#### `metrics_snapshot`

- Columns:
  - `id`
  - `platform_post_id`
  - `window_name`
  - `revision_no`
  - `status`
  - `provider`
  - `provider_version`
  - `source_payload_artifact_id`
  - `fetched_at`
  - `views`
  - `avg_watch_time`
  - `completion_rate`
  - `opening_hold_rate`
  - `shares`
  - `comments`
  - `created_at`
- Constraints:
  - `fk(platform_post_id -> platform_post.id)`
  - `fk(source_payload_artifact_id -> artifact_object.id)` nullable
  - `unique(platform_post_id, window_name, revision_no)`
- Notes:
  - `revision_no` distinguishes refetches from missing or stale data.

## Enums

- `platform`: `youtube_shorts`, `instagram_reels`, `tiktok`
- `source_type`: `uploaded_asset`, `approved_import`
- `job_status`: `created`, `processing`, `awaiting_manual_review`, `awaiting_shortlist_review`, `rendering_finals`, `qa_manual_salvage_required`, `awaiting_final_approval`, `publishing`, `metrics_ingesting`, `completed`, `completed_partial`, `completed_insufficient_output`, `failed`, `cancelled`
- `stage_name`: `intake`, `ingest`, `transcript`, `feature_extract`, `ranking`, `preview_render`, `final_render`, `qa`, `publish`, `metrics`
- `stage_run_status`: `queued`, `claimed`, `running`, `succeeded`, `failed_retryable`, `failed_terminal`, `blocked_manual_review`, `cancelled`
- `ingest_status`: `pending`, `accepted`, `manual_review_required`, `rejected_out_of_scope`, `processing`, `ready`, `failed`
- `variant_kind`: `preview`, `final`
- `length_bucket`: `15_25`, `25_40`, `40_60`
- `qa_status`: `pending`, `pass`, `regenerate_once`, `manual_salvage_required`, `reject`, `failed`
- `decision_enum`: `approve`, `reject`, `revoke`
- `provenance_type`: `approved_import`, `manual_attestation`, `channel_allowlist`
- `publish_status`: `intent_created`, `awaiting_final_approval`, `approved_snapshot_frozen`, `dispatching`, `draft_created`, `scheduled`, `published`, `failed_retryable`, `failed_terminal`, `cancelled`
- `delivery_mode`: `draft`, `scheduled`
- `export_status`: `pending`, `approved`, `assembled`, `delivered`, `failed`
- `metrics_window`: `1h`, `24h`, `72h`, `7d`
- `metrics_status`: `pending`, `fetched`, `unavailable`, `failed`
- `platform_account_status`: `active`, `paused`, `revoked`, `invalid`
- `qa_finding_severity`: `info`, `warning`, `error`

## Mutation and Versioning Rules

- Append-only:
  - `job_config_snapshot`
  - `job_status_transition`
  - `transcript_revision`
  - `candidate_set`
  - `edit_plan`
  - `render_attempt`
  - `qa_run`
  - `qa_finding`
  - `shortlist_decision`
  - `approval_payload_snapshot`
  - `final_approval`
  - `publish_attempt`
  - `publish_intent_transition`
  - `metrics_snapshot`
  - `outbox_event`
- Mutable:
  - `job.status`, `job.version`
  - `source_video.ingest_status`
  - `render_variant.qa_status` and current artifact pointers
  - `post_draft` fields before final approval
  - `publish_intent.status`
  - `platform_account.status`
- Material edits to `post_draft` must:
  - increment `post_draft.version`
  - invalidate any current final approval in application logic
  - require a new `approval_payload_snapshot` before publish

## Row vs Artifact Storage

- Keep in rows:
  - ids, statuses, reason codes, timestamps, time ranges, scores, checksums, schedule, platform identifiers
- Keep in `jsonb`:
  - `brand_profile.*_policy`
  - `platform_account.capabilities_jsonb`
  - `job_config_snapshot.config_jsonb`
  - `candidate_clip.rationale_jsonb`
  - `edit_plan.cut_map`
  - `edit_plan.timewarp_map`
  - `approval_payload_snapshot.payload_jsonb`
- Keep in object storage:
  - uploaded video
  - normalized audio
  - proxy video
  - thumbnails
  - raw ASR JSON
  - diarization, scene, crop-risk, and pause tracks
  - preview and final renders
  - subtitle files
  - render manifests
  - QA evidence
  - export manifests
  - raw provider analytics payloads

## Migration Order

1. Create enums, `artifact_object`, and `outbox_event`.
2. Create `brand_profile`, `platform_account`, `source_video`, `source_video_artifact`, `source_video_provenance`.
3. Create `job`, `job_target_platform`, `job_config_snapshot`, `stage_run`, `job_status_transition`.
4. Add `transcript_revision`, `transcript_word`, `transcript_segment`, `stage_run_artifact`.
5. Add offline-eval support tables: `eval_set`, `eval_set_member`, `candidate_label`, `benchmark_run`, `benchmark_result`.
6. Add `candidate_set`, `candidate_clip`, `edit_plan`, `render_variant`, `render_attempt`, `render_attempt_artifact`.
7. Add `qa_run`, `qa_finding`, `shortlist_decision`, `post_draft`, `approval_payload_snapshot`, `final_approval`.
8. Add `publish_intent`, `publish_attempt`, `publish_intent_transition`, `platform_post`, `export_package`.
9. Add `metrics_snapshot`.
10. Add performance indexes and partial unique indexes after the base tables are in place.

## Required SQLAlchemy Notes

- Model append-only tables as insert-only in repositories; do not expose generic update helpers for them.
- Use explicit SQLAlchemy `Enum` or constrained text columns for all state machine values.
- Model partial unique constraints and partial indexes directly in Alembic migrations.
- `outbox_event`, `stage_run`, and `publish_intent` need repository methods that enforce compare-and-swap semantics.

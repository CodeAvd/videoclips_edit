# AI Shorts Engine v1 Implementation Backlog

## Purpose

- This backlog decomposes the v1 contract into execution-ready milestones and issues.
- Each issue must carry `depends_on`, owner surface, touched schema or API areas, and explicit acceptance criteria.
- Milestones are sequential on the critical path unless a task is explicitly marked parallel-safe.

## Milestone Map

- `M0 Foundation`
- `M1 Intake + Transcription`
- `M2 Candidate Engine`
- `M3 Preview + Render`
- `M4 QA + Approval + Delivery`
- `M5 Feedback + Ops`

## M0 Foundation

### Goal

- Stand up the control plane, schema baseline, auth, and orchestration primitives without touching media intelligence yet.

### Issues

#### `M0-1 Project skeleton`

- Depends on: none
- Owner surface: app bootstrap
- Touchpoints:
  - FastAPI app factory
  - settings
  - dependency wiring
- Acceptance:
  - service boots locally
  - health endpoint works
  - config is environment-driven

#### `M0-2 SQLAlchemy base and Alembic baseline`

- Depends on: `M0-1`
- Owner surface: persistence
- Touchpoints:
  - `artifact_object`
  - `brand_profile`
  - `platform_account`
  - `source_video`
  - `job`
  - `job_config_snapshot`
  - `stage_run`
  - `outbox_event`
- Acceptance:
  - initial migration applies cleanly
  - rollback works in dev
  - enums exist with exact v1 state names

#### `M0-3 Auth and RBAC`

- Depends on: `M0-1`
- Owner surface: auth
- Touchpoints:
  - session auth
  - worker JWT auth
  - role guards
- Acceptance:
  - `viewer`, `reviewer`, `operator`, `admin` are enforced at route level
  - worker endpoints remain internal-only

#### `M0-4 Job state machine and CAS`

- Depends on: `M0-2`
- Owner surface: orchestration
- Touchpoints:
  - `job`
  - `stage_run`
  - `job_status_transition`
- Acceptance:
  - only one active `StageRun` per `(job_id, stage_name)`
  - compare-and-swap update path exists for state transitions
  - lease expiry recovery path is defined and tested

#### `M0-5 Outbox and durable side effects`

- Depends on: `M0-2`, `M0-4`
- Owner surface: orchestration
- Touchpoints:
  - `outbox_event`
- Acceptance:
  - stage completions enqueue next-stage work through outbox
  - retryable stage failures close the current attempt and enqueue a new `StageRun(attempt_no + 1)`
  - publish side effects cannot happen without a durable record

#### `M0-6 Reason codes, artifact lineage, and eval groundwork`

- Depends on: `M0-2`
- Owner surface: persistence + evaluation
- Touchpoints:
  - artifact link tables
  - offline eval tables
  - reason-code catalog
- Acceptance:
  - schema can store frozen eval sets and benchmark runs
  - artifact lineage exists for stage, render, QA, and analytics payloads
  - reason codes used by intake, QA, and review flows are enumerated and reusable

## M1 Intake + Transcription

### Goal

- Accept owned source media, normalize it, and persist transcript revisions with word-level timestamps.

### Issues

#### `M1-1 Upload session and asset registration`

- Depends on: `M0-1`, `M0-2`
- Owner surface: API + storage
- Touchpoints:
  - `POST /uploads`
  - `POST /uploads/{id}/complete`
  - `artifact_object`
- Acceptance:
  - completed uploads yield immutable artifact rows
  - checksum mismatch is rejected

#### `M1-2 Source video intake API`

- Depends on: `M1-1`
- Owner surface: API
- Touchpoints:
  - `POST /source-videos`
  - `GET /source-videos/{id}`
  - `source_video`
  - `source_video_artifact`
- Acceptance:
  - intake requires `rights_attestation = true`
  - approved imports require provenance payload
  - unsupported inputs can enter `manual_review_required`

#### `M1-3 Job creation API`

- Depends on: `M1-2`, `M0-4`
- Owner surface: API + orchestration
- Touchpoints:
  - `POST /jobs`
  - `GET /jobs`
  - `GET /jobs/{id}`
  - `job_target_platform`
  - `job_config_snapshot`
- Acceptance:
  - `POST /jobs` is idempotent
  - new jobs emit the `intake` stage through outbox

#### `M1-4 Ingest worker`

- Depends on: `M1-3`, `M0-5`
- Owner surface: worker
- Touchpoints:
  - `source_video_artifact`
  - `stage_run_artifact`
- Acceptance:
  - intake gate checks duration, language, audio quality, spoken-video scope, and provenance before ingest proceeds
  - original source linkage remains immutable while `canonical_video`, normalized audio, proxy, and thumbnails are produced through `source_video_artifact`
  - transient media failures retry cleanly

#### `M1-5 Transcript worker`

- Depends on: `M1-4`
- Owner surface: worker
- Touchpoints:
  - `transcript_revision`
  - `transcript_word`
  - `transcript_segment`
- Acceptance:
  - word-level timestamps are stored
  - segment aggregation is stored
  - current transcript revision can be queried via API

## M2 Candidate Engine

### Goal

- Build the multimodal ranking core and produce reviewable candidate sets.

### Issues

#### `M2-1 Feature extraction worker`

- Depends on: `M1-5`, `M0-6`
- Owner surface: worker
- Touchpoints:
  - `stage_run_artifact`
- Acceptance:
  - transcript turns and audio energy features are persisted
  - pause, scene, active-speaker, and crop-risk artifacts are persisted

#### `M2-2 Candidate generation and ranking`

- Depends on: `M2-1`, `M0-6`
- Owner surface: worker
- Touchpoints:
  - `candidate_set`
  - `candidate_clip`
- Acceptance:
  - each in-scope job yields `30-80` candidates
  - scores and rationale are persisted
  - diversification constraints are applied before shortlist output

#### `M2-3 Offline eval harness`

- Depends on: `M0-6`, `M1-5`
- Owner surface: evaluation
- Touchpoints:
  - eval dataset and benchmark artifacts
- Acceptance:
  - frozen eval sets and human labels can be managed
  - ranking changes can be benchmarked offline
  - no scoring policy change ships without a comparison artifact

#### `M2-4 Candidate and transcript read APIs`

- Depends on: `M2-2`
- Owner surface: API
- Touchpoints:
  - transcript endpoints
  - candidate clip endpoints
- Acceptance:
  - review console can fetch transcript and ranked candidates

## M3 Preview + Render

### Goal

- Turn the ranked shortlist into preview renders and then final masters.
- Gate before starting `M3`:
  - live Postgres smoke for `upload -> ranking` must be green
  - a persisted benchmark comparison artifact must exist for the active `prompt_version` and `scoring_policy_version`

### Issues

#### `M3-1 Preview render lane`

- Depends on: `M2-2`
- Owner surface: worker
- Touchpoints:
  - `edit_plan`
  - `render_variant`
  - `render_attempt`
  - `render_attempt_artifact`
- Acceptance:
  - previews exist for shortlisted candidates
  - previews preserve timing, captions, and framing intent

#### `M3-2 Shortlist review API`

- Depends on: `M3-1`
- Owner surface: API
- Touchpoints:
  - `POST /jobs/{id}/shortlist-decisions`
  - `shortlist_decision`
- Acceptance:
  - reviewer can approve and reject previews with reason codes
  - approved preview count is capped by `target_final_clip_count`

#### `M3-4 Review console minimum surface`

- Depends on: `M3-2`
- Owner surface: review console
- Touchpoints:
  - job list
  - job detail
  - preview player
  - stage status
  - failure reasons
- Acceptance:
  - reviewer can inspect job status, previews, and rejection reasons without direct DB access

#### `M3-3 Final render lane`

- Depends on: `M3-2`
- Owner surface: worker
- Touchpoints:
  - final `edit_plan`
  - final `render_variant`
  - `render_attempt`
- Acceptance:
  - final renders include `9:16`, captions, opening overlay, and silence tightening
  - optional B-roll and music obey brand policy

## M4 QA + Approval + Delivery

### Goal

- Add the final quality gate, payload freeze, and delivery adapters.

### Issues

#### `M4-1 QA worker and findings model`

- Depends on: `M3-3`
- Owner surface: worker
- Touchpoints:
  - `qa_run`
  - `qa_finding`
  - `render_variant.qa_status`
- Acceptance:
  - deterministic checks run on every final render
  - outcomes are `pass`, `regenerate_once`, `manual_salvage_required`, or `reject`

#### `M4-2 Regenerate-once flow`

- Depends on: `M4-1`
- Owner surface: worker + review API
- Touchpoints:
  - `render_attempt`
  - `qa_run`
- Acceptance:
  - QA auto-regenerate executes automatically when outcome is `regenerate_once`
  - at most one auto-regenerate pass is possible per final render variant
  - manual salvage resume path exists for `qa_manual_salvage_required`

#### `M4-3 Post draft API and final approval freeze`

- Depends on: `M4-1`
- Owner surface: API
- Touchpoints:
  - `post_draft`
  - `approval_payload_snapshot`
  - `final_approval`
- Acceptance:
  - draft metadata is editable before final approval
  - approval freezes exact payload and checksum
  - material edits invalidate prior approval

#### `M4-4 YouTube publish adapter`

- Depends on: `M4-3`
- Owner surface: worker + integration
- Touchpoints:
  - `publish_intent`
  - `publish_attempt`
  - `platform_post`
- Acceptance:
  - direct publish or draft creation works for `youtube_shorts`
  - retry uses the same `publish_intent`
  - draft and scheduled flows are both idempotent
  - duplicate dispatch is prevented by unique intent semantics and external ID reuse

#### `M4-5 Export package assembly`

- Depends on: `M4-3`
- Owner surface: worker
- Touchpoints:
  - `export_package`
  - export manifest artifact
- Acceptance:
  - TikTok and Instagram export packages assemble without calling their publish APIs
  - export path is idempotent by `(render_variant, platform)`

#### `M4-6 Manual salvage surface`

- Depends on: `M4-1`, `M3-4`
- Owner surface: review console + API
- Touchpoints:
  - manual salvage package endpoint
  - QA findings view
  - edit-plan context
- Acceptance:
  - reviewer can access timestamps, transcript, hook suggestion, caption draft, metadata draft, and QA findings for salvage cases

## M5 Feedback + Ops

### Goal

- Close the loop with metrics, dashboards, and pilot gating.

### Issues

#### `M5-1 Metrics backfill worker`

- Depends on: `M4-4`
- Owner surface: worker
- Touchpoints:
  - `metrics_snapshot`
  - metrics payload artifacts
- Acceptance:
  - metric windows at `1h`, `24h`, `72h`, `7d` are fetched asynchronously
  - unavailable metrics are distinguishable from zero values

#### `M5-2 Observability`

- Depends on: `M0-4`, `M4-4`, `M5-1`
- Owner surface: ops
- Touchpoints:
  - logs
  - dashboards
  - alerts
- Acceptance:
  - dashboards exist for throughput, QA failure distribution, publish success, and cost per approved clip
  - alerts exist for repeated stage failures, publish failures, lease conflicts, and metrics lag

#### `M5-3 Attribution and pilot review`

- Depends on: `M5-1`
- Owner surface: analytics + product
- Touchpoints:
  - score-to-performance reporting
  - prompt/scoring version lineage
- Acceptance:
  - performance can be traced back to render variant and scoring policy
  - pilot thresholds and kill criteria can be evaluated from stored data

## Parallelism Rules

- Parallel-safe:
  - docs and schema work within the same milestone
  - independent read APIs after the underlying tables exist
  - observability work after identifiers are present
- Not parallel-safe:
  - multiple active stage runs for one `(job, stage)`
  - final render before shortlist review
  - publish before QA pass and frozen approval snapshot
  - metrics attribution before platform posts exist

## Exit Criteria

- `M0-M4` complete means the first pilot-ready production loop exists, including the required review console and manual salvage surface.
- `M5` complete means the team can optimize and scale with evidence instead of manual guesswork.
- No implementation phase should start if its predecessor milestone acceptance is still unmet.

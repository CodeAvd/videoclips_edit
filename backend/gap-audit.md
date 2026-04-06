# Backend Gap Audit

## Scope

- Audit target: `backend/` scaffold after the first executable `M0-M2` slice.
- Goal: localize remaining implementation gaps against `specification.md`, `db-schema.md`, `api-contract.md`, and `worker-contracts.md`.
- Review mode:
  - Critic pass: find real contract mismatches and runtime risks.
  - Solution pass: propose the narrowest compatible fix.
  - Arbitration pass: decide whether to keep the scaffold and continue.

## Closed In Current Slice

- Upload sessions now return a real local `upload_url` in filesystem mode.
- `PUT /api/v1/uploads/{upload_id}/content` exists and writes bytes into the active storage backend.
- Upload completion now validates the stored object against both declared upload metadata and completion payload metadata.
- Worker-generated ingest and transcript artifacts are written through the storage layer, not only registered as DB rows.
- Raw source linkage is persisted through `source_video_artifact(role='source_asset')`.
- `source_video.canonical_asset_id` now stays pinned to the original source artifact, while ingest registers normalized video access through `source_video_artifact(role='canonical_video')`.
- Canonical job checksum behavior is covered by tests for stable target-platform ordering.
- First-class API idempotency is implemented for `POST /jobs`, `POST /jobs/{id}/actions/resolve-intake-review`, and `POST /uploads/{id}/complete`.
- Retryable stage failures now close the current `outbox_event` and `stage_run`, then enqueue a new delayed `StageRun` attempt with incremented `attempt_no`.
- Worker execution now commits claims before long-running work, renews both stage and outbox leases while work is active, and deterministically reclaims expired claimed/running `StageRun`s.
- Lease heartbeat renewal now extends execution only for the owning `(worker_id, lease_token)` pair, and expired claimed `outbox_event` rows are covered by regression tests through `process_next_outbox_event`.
- SQLite-backed API/worker regression tests now cover upload completion, idempotent job creation, and retry vs terminal outbox behavior.
- `ingest` now uses real `ffmpeg` processing for normalized audio and proxy generation instead of stub media bytes.
- `transcript` now goes through a provider abstraction with `Groq -> OpenAI -> Stub` fallback and persists normalized `transcript_revision`, `transcript_word`, and `transcript_segment` output plus raw ASR payload artifacts.
- `feature_extract` now writes pause, audio-energy, scene, active-speaker, crop-risk, and summary artifacts to `stage_run_artifact`.
- `ranking` now creates versioned `candidate_set` plus ranked `candidate_clip` rows and exposes them via read APIs.
- `GET /source-videos/{id}` now returns attached artifacts keyed by role plus created-order provenance records.
- `GET /jobs/{id}` now returns the current config snapshot, latest-per-stage execution summary, output counts for current transcript/candidate outputs, and a current approval-state projection for the review console.
- Offline eval support is now implemented through `eval_set`, `eval_set_member`, `candidate_label`, `benchmark_run`, `benchmark_result`, and an internal benchmark runner that persists a comparison artifact.
- Fresh-install migration parity is now verified on disposable Postgres: `docker compose` boot, Alembic `0001 -> 0002 -> 0003 -> 0004`, and the `upload -> ranking` worker smoke path all pass against `ai_shorts_engine_test`.
- Candidate clip APIs now exist:
  - `GET /jobs/{job_id}/candidate-clips`
  - `GET /candidate-clips/{candidate_clip_id}`

## Critic Pass

### P1

- Auth is still a bridge implementation rather than the full contract.
  - Current state: route-level RBAC exists, `development_header` remains available for local work, and backend-side signed `session_cookie` verification now removes the old `501` path for non-dev console auth.
  - Remaining risk: the public contract still targets `OIDC + httpOnly Secure session cookie`, while full session issuance, rotation, revocation, and any internal worker HTTP surface still need production-grade integration.
  - Localized in:
    - `app/core/security.py`
    - `app/core/config.py`
    - `tests/test_auth_rbac.py`

- Idempotency is still partial.
  - Current state: write-path idempotency exists for the most important current endpoints, but not yet for future approval/publish actions.
  - Risk: the current surface is protected, but new mutable write actions can still drift if they ship without the same store.
  - Localized in:
    - `app/api/v1/endpoints/jobs.py`
    - `app/api/v1/endpoints/uploads.py`
    - future approval/publish endpoints

- MinIO path exists only as a storage adapter contract.
  - Current state: `MinioStorageService` now supports read/write parity for object metadata and bytes, but the MinIO path is still not covered by tests or boot checks.
  - Risk: local filesystem mode works while object-storage mode drifts.
  - Localized in:
    - `app/services/storage.py`
    - `.env.example`
    - `README.md`

- Preview/final-render media consumers are not implemented yet, but their source-of-truth is now fixed.
  - Current state: `canonical_asset_id` remains the original source pointer, and normalized video access now flows through `source_video_artifact(role='canonical_video')`.
  - Remaining risk: future `M3` code must read `canonical_video` rather than falling back to the raw source asset.
  - Localized in:
    - `app/models/job.py`
    - `app/api/v1/endpoints/source_videos.py`
    - `app/services/worker_runtime.py`

- Job detail approval state is still a coarse projection until `M3/M4` review tables exist.
  - Current state: `GET /jobs/{id}` now satisfies the pre-`M3` review-console need using current config snapshot, stage summary, output counts, and a status-derived approval-state projection.
  - Remaining risk: once `shortlist_decision`, `approval_payload_snapshot`, and `final_approval` land, the projection must be replaced with a read model backed by the actual review/approval records.
  - Localized in:
    - `app/api/v1/endpoints/jobs.py`
    - `app/schemas/job.py`

- DB-backed benchmark confidence is still only partially proven.
  - Current state: the eval harness persists comparison artifacts and benchmark results, and live disposable-Postgres smoke is now green in this workspace.
  - Remaining risk: the formal pre-`M3` benchmark gate still needs one real frozen eval set with persisted comparison evidence for the active `prompt_version` and `scoring_policy_version`, not just test-generated proof.
  - Localized in:
    - `tests/test_eval_harness.py`
    - `app/services/eval_harness.py`

### P2

- Visual intelligence is still heuristic-only.
  - Current state: `feature_extract` writes real pause/audio-energy features, but scene, active-speaker, and crop-risk are still deterministic heuristics rather than video-model outputs.
  - Risk: ranking works structurally, but multimodal quality lift is still limited until real visual tracks land.
  - Localized in:
    - `app/services/worker_runtime.py`
    - `app/services/feature_extract.py`

## Solution Pass

### Closure Plan 1: Canonical Media Split

- Closed for the current `M0-M2` path.
- `canonical_asset_id` remains the immutable original source pointer.
- Normalized outputs are resolved through `source_video_artifact` roles:
  - `normalized_audio`
  - `proxy_video`
  - `canonical_video`
  - `thumbnails`
- Future preview/final-render stages must consume `canonical_video` rather than `canonical_asset_id`.

### Closure Plan 2: Durable Outbox + Lease Renewal

- Closed for the current worker runtime.
- `outbox_event` now records:
  - `retry_count`
  - `max_retries`
  - `last_error_code`
  - `last_error_message`
- Retryable failures now:
  - mark the current `outbox_event` as failed with error metadata
  - mark the current `StageRun` as `failed_retryable`
  - enqueue a new delayed stage attempt with incremented `attempt_no`
- The worker loop now:
  - commits claims before long-running execution
  - renews stage and outbox leases while work is active
  - reclaims expired claimed/running stage leases deterministically

### Closure Plan 3: First-Class Idempotency

- Add an `idempotency_key` table keyed by:
  - `endpoint_key`
  - `actor_ref`
  - `idempotency_key`
- Persist request hash, response hash, terminal status, and resource reference.
- Apply it first to:
  - `POST /jobs`
  - `POST /jobs/{id}/actions/resolve-intake-review`
  - `POST /uploads/{id}/complete`

### Closure Plan 4: Postgres Integration Harness

- Closed for the current pre-`M3` gate.
- Local compose bootstraps an explicit disposable database `ai_shorts_engine_test` in the same container.
- The smoke harness now:
  - waits for disposable Postgres readiness after `docker compose up -d`
  - disables SSL automatically for localhost disposable URLs
  - migrates cleanly through `0001 -> 0002 -> 0003 -> 0004`
  - proves `upload -> intake -> ingest -> transcript -> feature_extract -> ranking` on real Postgres
- Verified entrypoints:
  - `pytest tests/test_postgres_migration_smoke.py tests/test_eval_harness.py -m postgres -q`
  - `pytest -q` with `POSTGRES_TEST_DATABASE_URL` pointed at `ai_shorts_engine_test`

### Closure Plan 5: Bridge Auth and RBAC

- Partially closed for the current public control plane.
- `development_header` remains available for local development and test harnesses.
- `session_cookie` now validates signed console session claims instead of returning `501`.
- Route-level RBAC continues to flow through `require_role(...)`, with `401 unauthorized` for missing/invalid credentials and `403 forbidden` for insufficient roles.
- Remaining contract gap:
  - full OIDC session issuance and management are still pending;
  - future worker-only HTTP routes must use dedicated worker JWT verification rather than console auth.

### Closure Plan 6: Ranking Eval Harness + Render Prep

- Partially closed for the current `M0-M2` path.
- Eval-set tables, benchmark persistence, and the comparison-artifact gate now exist.
- Live Postgres smoke is now verified.
- Remaining pre-`M3` requirement:
  - run the benchmark harness against a real frozen eval set and persist comparison evidence for the active `prompt_version` and `scoring_policy_version`
- Keep subtitles and B-roll in `M3+`; use current `feature_extract` artifacts as the future subtitle/B-roll input seam.
- Prepare `edit_plan`/`render_variant` only after preview render scope is finalized.

## Arbitration Pass

### Compared Options

- Option A: keep the scaffold and add storage/tests/reliability incrementally.
- Option B: rewrite orchestration/storage before any more feature work.

### Decision

- Keep the scaffold and continue.
- Rationale:
  - the current structure matches the v1 contract closely enough;
  - the main risks are missing reliability layers, not a wrong architecture;
  - rewriting now would reset working progress without reducing the hardest future work.

### Conditions To Continue

- Do not add `M2` ranking work before DB-backed integration tests exist.
- Do not extend `M2` ranking heuristics before DB-backed integration tests and an eval harness exist.
- Do not ship preview/final render before live Postgres smoke exists, the new stages consume `source_video_artifact(role='canonical_video')`, and a persisted benchmark comparison artifact exists for the active `prompt_version` and `scoring_policy_version`.
- Do not expand publish/approval surfaces before first-class idempotency is in place.

# Stage A Pilot Review Protocol

This document freezes the review protocol for the current Stage A pilot cycle.

## Judgment Basis

- Only holdout comparison outcomes count for stop/go judgment.
- Dev results are operational feedback only and do not count as evidence.

## Cycle Freeze

After the first holdout review session is created, do not change:

- proof-harness payload shape
- reject taxonomy
- comparison logic
- shortlist generation config used for this cycle
- reviewer-facing preview format

No ranking or tuning is allowed during holdout.
No baseline re-imports are allowed for a source video after review starts for that source video.

## Review Session Rules

- Each source video is reviewed through one blinded `A/B/C` session.
- Each batch contains exactly `8` candidates.
- Each batch gets the same `10 minute` time budget.
- Each batch uses the same preview format.
- Reviewer must not see system-of-origin.
- Reviewer records one decision per candidate and one batch preference ranking per source video.

## Reject Taxonomy

Use only these reject reasons:

- `weak_opening`
- `late_or_missing_payoff`
- `needs_context`
- `fragmented_cut`
- `duplicate_angle`
- `off_topic_or_low_signal`
- `review_timeout`

## Reviewer Staffing

- One primary reviewer per source video.
- Holdout only: audit `2 of 8` videos.
- Audit reviewer must be independent.
- Audit reviewer must not see the primary outcome.
- Audit reviewer must not be told which cases are audit cases until after submission.

## Execution Order

1. Run all dev reviews first.
2. Fix operational issues only.
3. Start holdout reviews.
4. Run two independent holdout audits after the corresponding primary reviews are complete.
5. Persist one holdout comparison artifact.
6. Make stop/go judgment from holdout only.

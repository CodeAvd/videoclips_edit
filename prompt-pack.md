# Prompt Pack: AI Shorts Engine

## Core Direction

- This pack assumes long-form spoken content is the source of truth.
- The system should over-generate clip options, then narrow aggressively.
- Hooks must optimize for immediate recognition, not abstract cleverness.
- The final ranking must prefer self-contained clips with fast payoff.
- Any uncertain tactic must be framed as an experiment.

## Shared Rules

- Prefer transcript, diarization, pause, and scene evidence over intuition.
- Never accept a clip that needs missing setup from 20 seconds earlier.
- Treat the first second as its own scoring zone.
- Generate 2-3 hook variants only for the top ranked clips.
- Keep human approval between edit completion and scheduled publishing.

## Default Agent Sequence

1. `IngestAgent`
2. `TranscriptionAgent`
3. `SegmentationAgent`
4. `ClipMinerAgent`
5. `EditDirectorAgent`
6. `CaptionCopyAgent`
7. `QAAgent`
8. `SchedulerAgent`
9. `FeedbackAgent`

## Default Outputs

- `5-20` clips per source video
- one score breakdown per clip
- one edit plan per clip
- `2-3` title and headline variants for top clips
- platform-specific caption packages
- a schedule proposal with approval state

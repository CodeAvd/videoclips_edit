# Autoresearch Lane

This directory is reserved for offline experimentation only.

## Rules

- Do not import this lane into the production API runtime.
- Do not let experiments write directly into production scoring policies.
- Only run against frozen eval sets and persisted comparison artifacts.
- Treat canonical reference shorts as analysis-only inputs; do not reuse them as B-roll or footage.
- Prefer a local-first, frames-first pipeline:
  - deterministic metadata, scene, silence, and OCR extraction first
  - sampled frame packs second
  - no full-video VLM passes
  - no per-frame LLM loop
- Use a single external multimodal classifier only when local evidence is insufficient.
- OpenAI vision is the preferred optional frame-pack classifier in v1; keep it limited to sampled frame packs, not whole videos.
- Valid experiment surfaces:
  - ranking weight search
  - prompt variant comparison
  - candidate heuristic comparison
  - subtitle packaging heuristics
  - reference-shorts intelligence and preset synthesis

## Current Status

- `reference_intelligence.py` now provides the first offline executable slice.
- Production runtime remains `FastAPI + workers` only.
- v1 hybrid analysis should remain analysis-only and benchmark-gated; no automatic production mutation is allowed.

## Reference Input Contract

Place each collection under:

```text
references/<collection>/
  manifest.json or manifest.csv
  videos/
    ...
```

Required manifest fields:

- `reference_id`
- `file_name`
- `channel_or_source`
- `theme`
- `language`

Optional fields:

- `platform`
- `notes`
- `style_family`
- `why_reference`
- `subtitle_file`
- `transcript_file`
- `hook_text`
- `cta_text`

## Generated Outputs

Each run writes:

- `reference_manifest.lock.json`
- `reference_sampling_map.json`
- `reference_ocr_report.json`
- `reference_style_report.json`
- `reference_clusters.json`
- `preset_bundle.json`
- `comparison_report.json` when both benchmark payloads already exist

## Usage

From `backend/`:

```bash
REFERENCE_COLLECTION_DIR=..\references\my-pack OUTPUT_DIR=..\references\my-pack\outputs PRESET_NAME=my-pack-v1 PROMPT_VERSION=v1 SCORING_POLICY_VERSION=v1 make reference-intelligence
```

To add an offline comparison report when both benchmark payloads already exist:

```bash
REFERENCE_COLLECTION_DIR=..\references\my-pack OUTPUT_DIR=..\references\my-pack\outputs PRESET_NAME=my-pack-v1 PROMPT_VERSION=v1 SCORING_POLICY_VERSION=preset-my-pack-v1 BASELINE_BENCHMARK_PATH=..\tmp\baseline.json CANDIDATE_BENCHMARK_PATH=..\tmp\candidate.json make reference-intelligence-benchmark
```

Optional providers can be enabled explicitly:

```bash
REFERENCE_COLLECTION_DIR=..\references\my-pack OUTPUT_DIR=..\references\my-pack\outputs PRESET_NAME=my-pack-v1 PROMPT_VERSION=v1 SCORING_POLICY_VERSION=v1 OCR_PROVIDER=auto VLM_PROVIDER=openai VLM_MODEL=<vision-model> OPENAI_API_KEY=<key> make reference-intelligence
```

This lane is intentionally offline-only:

- it may recommend `prompt_version` and `scoring_policy_version`;
- it may synthesize render policy hints such as `caption_style`, `crop_mode`, `silence_trim_level`, and `broll_mode`;
- it may emit `reference_manifest.lock.json`, `reference_sampling_map.json`, and `reference_ocr_report.json` as intermediate artifacts;
- it must not mutate production defaults automatically.
- if a preset touches ranking-adjacent policy, it must be compared against a frozen eval set and persisted comparison artifact before any enablement decision.

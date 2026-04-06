# Canonical Reference Shorts

Canonical short-video references are analysis-only inputs for the offline reference-intelligence lane.

They are never reused as B-roll, footage, or production media assets.
The intended analysis posture is local-first and frames-first: extract deterministic metadata and scene signals locally, then escalate only sampled frame packs to an external multimodal classifier when needed.

## Collection Layout

```text
references/<collection>/
  manifest.json or manifest.csv
  videos/
    short-01.mp4
    short-02.mp4
    ...
```

Optional sidecars can live anywhere under the collection as long as the manifest points to them:

```text
references/<collection>/captions/short-01.srt
references/<collection>/captions/short-02.vtt
references/<collection>/transcripts/short-01.txt
```

## Required Manifest Fields

- `reference_id`
- `file_name`
- `channel_or_source`
- `theme`
- `language`

## Optional Manifest Fields

- `platform`
- `notes`
- `style_family`
- `why_reference`
- `subtitle_file`
- `transcript_file`
- `hook_text`
- `cta_text`

## Example JSON Manifest

```json
{
  "references": [
    {
      "reference_id": "finance-001",
      "file_name": "finance-001.mp4",
      "channel_or_source": "Finance Creator",
      "theme": "finance explainer",
      "language": "en",
      "platform": "youtube_shorts",
      "style_family": "editorial",
      "notes": "Uses B-roll only when it helps explain the point.",
      "why_reference": "Strong first-second hook with readable captions.",
      "subtitle_file": "captions/finance-001.srt",
      "transcript_file": "transcripts/finance-001.txt",
      "hook_text": "Stop doing this with your money.",
      "cta_text": "Follow for the full breakdown."
    }
  ]
}
```

## Outputs

The offline lane writes these files into `references/<collection>/outputs/` by default:

- `reference_manifest.lock.json`
- `reference_sampling_map.json`
- `reference_ocr_report.json`
- `reference_style_report.json`
- `reference_clusters.json`
- `preset_bundle.json`
- `comparison_report.json` when both benchmark payloads already exist

The output set is intentionally analysis-only. It is a source of packaging priors and preset candidates, not a source of reusable footage or automatic production policy mutation.

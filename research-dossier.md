# AI-Powered Shorts Engine Research Dossier

Current through April 4, 2026. This dossier is built for a YouTube Shorts-first system that repurposes long-form talking-head and podcast content into `5-20` short clips, then adapts them for TikTok and Instagram Reels. The evidence bar is tiered: official docs and accepted papers are strongest; tool/vendor docs are capability evidence; creator, Reddit, and X discussions are anecdotal and used mainly for heuristics and failure modes.

## Executive Summary

- The best v1 system is not "pick one AI clipper and trust it." It is a hybrid pipeline: strong transcription and segmentation, custom clip reranking, template-driven editing, human QA, then scheduled publishing.
- The strongest repeated signal is opening-speed discipline. YouTube's own Shorts materials and creator interviews emphasize that the first second matters disproportionately, while community discussions repeatedly show that weak opening frames kill distribution even when later retention is decent.
- The second strongest signal is self-containment. Academic work on summarization, chaptering, and highlight detection repeatedly shows that long-form understanding works best when text and temporal structure are fused with multimodal cues instead of transcript-only heuristics.
- The third strong signal is that tool choice is secondary to ranking logic and testing discipline. Community operators repeatedly report that hooks, specificity, and systematic iteration beat random volume or endless tool comparison.
- Recommended v1 architecture:
  - orchestration in `n8n`
  - ASR with `gpt-4o-transcribe-diarize`, fallback `Whisper + pyannote`
  - segmentation with `PySceneDetect`, VAD, silence markers, and speaker turns
  - editing/rendering via `Vizard` as default, `Descript` and `Captions` for overrides, plus an FFmpeg template fallback
  - human approval before publish
- Evidence-weighted operating rule:
  - strong signal becomes default behavior
  - medium signal becomes configurable behavior
  - weak signal becomes an experiment only

## Viral Shorts Playbook

- Lead with one concrete idea, not an intro. The opening should present tension, proof, or a specific recognition moment immediately. Sources: [YouTube Shorts deep dive](https://blog.youtube/creator-and-artist-stories/youtube-shorts-deep-dive/), [Five tips to master Shorts](https://blog.youtube/creator-and-artist-stories/five-tips-to-master-shorts/).
- Optimize for self-contained clips. The best clips let a cold viewer understand the setup, the point, and the payoff without needing the full episode.
- Put payoff early. A practical target for spoken-content clips is first payoff inside `5-15s`, not at the very end.
- Use specificity over generic intensity. Specific pain, specific behavior, and specific proof outperform vague hype in both creator anecdotes and X workflow threads. Sources: [Adam Fishman on X](https://x.com/fishmanaf/status/1968116125708976354), [John on X](https://x.com/johnvirality/status/2036444247486853261).
- Use pattern interrupts only when they clarify the point. Good interrupts are crop changes, keyword highlights, visual inserts, or a strategic beat of silence. Bad interrupts are random zoom spam and decorative motion.
- Burned captions should be on by default because short-form is frequently consumed muted or semi-muted, but caption density should stay low enough to preserve readability.
- Use opening overlays as promise sharpeners, not clickbait. The overlay should clarify what the viewer is about to get, not restate the title in louder words.
- Prefer narrative compression:
  - problem
  - twist or key claim
  - proof or explanation
  - payoff or action
- For talking-head content, the stable winning pattern is not "constant chaos." It is fast comprehension plus periodic resets.
- Ban list for v1:
  - long setup before thesis
  - clip endings that stop before the actual payoff lands
  - duplicate shortlists that all attack the same angle
  - over-trimmed dead air that makes human speech sound synthetic

## Retention & Hook Frameworks

| Hook family | What it does | Best use case | Risk |
| --- | --- | --- | --- |
| Specific pain recognition | Names a precise lived moment | career, self-improvement, mistakes, interview lessons | generic pain language if not concrete |
| Counterintuitive claim | Creates tension by challenging a default belief | myth-busting, opinion, tactical advice | oversells if payoff is weak |
| Fast proof | Starts with a number, artifact, or direct result | case study, experiment, teardown | empty if proof is not explained |
| Question with immediate answer path | Pulls viewer into a clear payoff sequence | tutorial, explainer, workflow | can sound generic if phrased broadly |
| Authority confession | Opens with "I was wrong" or "I learned this the hard way" | trust-building, debriefs, expert lessons | loses credibility if dramatized |

Retention rules:

- Treat the first second as a separate scoring zone. The system should evaluate not just the first `0-3s`, but whether meaning arrives in the first second. Source: [YouTube Shorts deep dive](https://blog.youtube/creator-and-artist-stories/youtube-shorts-deep-dive/).
- For YouTube Shorts, optimize both opening conversion and watch quality:
  - `viewed vs swiped away`
  - average view duration
  - average percentage viewed
  - rewatch or replay behavior where available
  Sources: [YouTube Shorts analytics tips](https://support.google.com/youtube/answer/12942217?co=YOUTUBE._YTVideoType%3Dshorts&hl=en), [audience retention help](https://support.google.com/youtube/answer/9314415?hl=en).
- For TikTok, user interactions and whether viewers watch or skip are core recommendation inputs. Source: [How TikTok recommends content](https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content).
- For Instagram Reels, keep originality and engagement quality in mind, but use it as a secondary packaging target in v1 instead of the primary optimization loop. Source: [Meta Best Practices education hub announcement](https://about.fb.com/news/2024/10/best-practices-education-hub-creators-instagram/).

Practical pacing defaults for spoken clips:

- visual reset every `1.5-3.0s` when the frame is otherwise static
- hard proof or thesis before `3s`
- first explanatory payoff before `15s`
- keep one main thread per clip
- use loop endings only when the last line naturally echoes the opening

Caption dynamics:

- keep on-screen text in short chunks
- highlight one or two key words, not every word
- place captions to protect face and mouth area
- avoid first-caption latency that hides the opening promise

## Clip Selection Algorithm

### Stage 1: Over-generate candidate windows

Inputs:

- transcript with word timestamps
- speaker diarization
- energy proxies from audio amplitude and speaking rate
- pause markers and VAD boundaries
- scene boundaries from `PySceneDetect`
- crop-relevant metadata such as face or speaker position
- optional topic filters from the brief
- optional replay priors when a platform exposes them

Generation rules:

1. Start candidate windows around strong transcript turns, speaker transitions, scene cuts, silence boundaries, emphatic prosody, and query-matched topics.
2. Allow overlapping windows because the best hook boundary is often not the same as the best payoff boundary.
3. Produce `30-80` raw candidates from a `30-90 min` source.
4. Normalize every candidate into one of three target buckets:
   - `15-25s`
   - `25-40s`
   - `40-60s`

### Stage 2: Weighted reranking

Score each candidate on a `0-10` scale:

| Metric | Weight | What it means |
| --- | --- | --- |
| hook_strength | 25 | does meaning land in the first second and continue through the first `3s` |
| self_containment | 20 | can a cold viewer understand it without missing setup |
| payoff_density | 15 | how quickly the clip delivers useful or emotionally satisfying payoff |
| emotional_or_saliency_peak | 10 | presence of tension, surprise, laughter, emphasis, or strong reaction |
| clarity | 10 | transcript clarity, audio clarity, and argument clarity |
| novelty | 10 | distinctiveness relative to other candidates from the same source |
| editability | 10 | ease of reframing, captioning, trimming, and exporting |

Formula:

`final_score = hook*25 + self_containment*20 + payoff_density*15 + saliency*10 + clarity*10 + novelty*10 + editability*10 - penalties`

Penalties:

- missing_context
- delayed_payoff
- noisy_audio
- crop_risk
- duplicate_topic
- weak_ending
- punchline_after_cut

### Stage 3: Diversification

After ranking:

1. cluster by duplicate group or theme
2. keep the strongest example in each cluster first
3. add remaining clips with max-marginal-relevance logic so the final set covers different angles
4. enforce length-bucket diversity unless the brief says otherwise

### Stage 4: Human-readable rationale

Each selected clip should include:

- why the opening works
- what the payoff is
- what edit risk remains
- why it outranks the next alternative

Why this design is evidence-backed:

- `Rhapsody` shows transcript plus speech features outperform zero-shot LLM prompting for podcast highlight detection. Source: [Rhapsody](https://arxiv.org/abs/2505.19429).
- `Video Summarization with Large Language Models` and `Scaling Up Video Summarization Pretraining with Large Language Models` show semantic text guidance improves long-video summarization when combined with temporal reasoning. Sources: [CVPR 2025 LLMVS](https://openaccess.thecvf.com/content/CVPR2025/papers/Lee_Video_Summarization_with_Large_Language_Models_CVPR_2025_paper.pdf), [CVPR 2024 scaling paper](https://openaccess.thecvf.com/content/CVPR2024/papers/Argaw_Scaling_Up_Video_Summarization_Pretraining_with_Large_Language_Models_CVPR_2024_paper.pdf).
- `Unsupervised Video Highlight Detection by Learning from Audio and Visual Recurrence` argues audio is underused but valuable in highlight detection. Source: [WACV 2025](https://openaccess.thecvf.com/content/WACV2025/papers/Islam_Unsupervised_Video_Highlight_Detection_by_Learning_from_Audio_and_Visual_WACV_2025_paper.pdf).

## AI Editing Strategy

Default edit policy:

- aspect ratio: `9:16`
- captions: on
- opening headline: on for first `1-3s`
- silence tightening: on with guardrails
- auto B-roll: off unless it improves comprehension
- export lengths: `15-25s`, `25-40s`, `40-60s`

Editing rules:

- Use auto-reframing, but block any clip whose crop track loses the speaker during the key line.
- Remove silence only when the cadence remains natural. Both Vizard and Descript expose this because over-trimming creates audible damage. Sources: [Vizard advanced options](https://docs.vizard.ai/docs/advanced), [Descript filler words help](https://help.descript.com/hc/en-us/articles/10164806394509-Filler-words).
- Headline overlays should be declarative or curiosity-driven, but must stay within the claim actually proven by the clip.
- Captions should be readable at mobile size and aligned to phrase groups, not dumped line-by-line from raw transcript.
- Use B-roll only in three cases:
  - to show the artifact being discussed
  - to clarify a process step
  - to reset attention when the spoken point is dense
- Do not add B-roll to fake energy.
- Produce `2-3` hook or title variants for the top clips only. Do not multiply creative permutations on weak base clips.

Tool-specific strategy:

- `Vizard`: fastest baseline for transcript clipping, captioning, templates, silence removal, headlines, and publishing. Sources: [advanced options](https://docs.vizard.ai/docs/advanced), [publish docs](https://docs.vizard.ai/docs/publish-clips-to-social-media).
- `Descript`: strongest human override for transcript correction and natural-feeling cleanup. Sources: [correct transcript](https://help.descript.com/hc/en-us/articles/10119613609229-Correct-your-transcript), [filler words](https://help.descript.com/hc/en-us/articles/10164806394509-Filler-words).
- `Captions`: strongest generative packaging layer when you need more aggressive repurposing or multiple clip outputs from one recording. Source: [Repurpose AI](https://www.captions.ai/features/repurpose-ai).
- `Riverside Magic Clips`: useful for fast first-pass clip suggestions and recording-native creator workflows. Source: [Magic Clips help](https://support.riverside.fm/hc/en-us/articles/26473566830877-Magic-Clips-on-mobile-Made-for-you).
- FFmpeg plus templates: lowest marginal cost and highest control, but requires more internal tooling.

## Multi-Agent Architecture

| Agent | Main job | Inputs | Outputs | Failure mode to guard against |
| --- | --- | --- | --- | --- |
| `IngestAgent` | normalize media and metadata | source URL/file, brief | canonical asset package | unsupported media or bad metadata |
| `TranscriptionAgent` | produce time-aligned transcript | audio/video | `TranscriptSegment[]` | bad speaker labels or missing timestamps |
| `SegmentationAgent` | detect structure | media + transcript | scenes, pauses, turns, crop metadata | transcript-only segmentation |
| `ClipMinerAgent` | over-generate candidates | transcript + segmentation | `CandidateClip[]` | low-recall shortlist |
| `EditDirectorAgent` | assign edit plans | approved candidates | `EditPlan[]` | flashy but low-comprehension edits |
| `CaptionCopyAgent` | write packaging | clip text + edit plan | titles, captions, hashtags | overclaiming copy |
| `QAAgent` | block bad drafts | edited clip + copy | pass/fail + issue list | context debt, crop errors, caption errors |
| `SchedulerAgent` | create drafts and schedules | approved posts | scheduled drafts | accidental autopost without approval |
| `FeedbackAgent` | learn from outcomes | metrics and metadata | pattern updates, test backlog | overfitting to one-off winners |

Message contracts should stay close to the public interfaces defined in the project plan:

- `VideoIngestRequest`
- `TranscriptSegment`
- `CandidateClip`
- `EditPlan`
- `PostDraft`
- `FeedbackEvent`

Human gates:

- Gate 1: intake approved
- Gate 2: shortlist approved
- Gate 3: edited drafts approved
- Gate 4: scheduled posts approved

This architecture is aligned with agent-assisted editing research such as `LAVE`, which found value in agent planning plus direct user refinement rather than full black-box automation. Source: [LAVE](https://arxiv.org/abs/2402.10294).

## End-to-End Workflow

1. Intake
   - fill the brief
   - define platform, clip count, and length policy
2. Ingest
   - normalize media
   - extract audio and metadata
3. Transcribe and segment
   - run ASR with speaker labels
   - detect scenes, silence, turns, and frame cues
4. Generate candidates
   - over-generate windows
   - score and penalize
5. Shortlist
   - diversify by topic and length
   - produce rationale for each candidate
6. Edit
   - create vertical crop plans
   - add captions, overlays, and optional B-roll
7. QA
   - validate captions, context, crop, pacing, copy
8. Schedule
   - create platform drafts
   - wait for human approval
9. Publish
   - schedule or publish approved clips
10. Learn
   - measure outcomes and update the evidence base

Artifacts at the end of one run:

- `5-20` ranked clips
- one score breakdown per clip
- one edit plan per clip
- title, caption, and hashtag package
- suggested schedule
- post-run findings for the evidence log

## Automation Pipeline Design

Recommended `n8n` topology:

1. Trigger
   - manual form, watched folder, or webhook
2. Intake validation
   - validate `VideoIngestRequest`
3. Media prep
   - fetch file or remote media
   - store canonical copy
4. Transcription
   - call `gpt-4o-transcribe-diarize`
   - fallback to `Whisper + pyannote`
5. Segmentation
   - run `PySceneDetect`
   - run silence detection with FFmpeg
   - merge speaker turns and pauses
6. Candidate generation
   - invoke `ClipMinerAgent`
7. Custom reranking
   - compute weighted scores
   - collapse duplicates
8. Editing
   - route to Vizard or FFmpeg template renderer
9. Copy generation
   - produce titles, captions, hashtags, schedule slots
10. QA
   - auto checks plus human approval step
11. Scheduling
   - create drafts or scheduled posts
12. Metrics capture
   - fetch performance snapshots
13. Learning
   - update evidence log and test backlog

Operational notes:

- Store transcript, segmentation, and scoring features separately from rendered outputs so reranking can improve without re-rendering everything.
- Keep vendor substitution easy:
  - ASR layer swappable
  - editing layer swappable
  - publishing layer swappable
- Do not store a vendor-specific "viral score" as the canonical truth. Persist your own features and final score.
- Use queueing or batched processing when scaling beyond one source video at a time.

Why these components:

- `OpenAI` speech-to-text supports verbose timestamp output and diarization options. Sources: [speech-to-text guide](https://developers.openai.com/api/docs/guides/speech-to-text), [API reference snippet on diarize models](https://platform.openai.com/docs/api-reference/realtime-server-events/response/audio/done).
- `pyannote` provides a usable local diarization fallback with timestamp reconciliation features. Source: [pyannote speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1).
- `FFmpeg` exposes `silencedetect` and `silenceremove`, which are useful as features and cautious editing helpers. Source: [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html).
- `PySceneDetect` provides practical content-based scene detection for shot boundaries. Source: [PySceneDetect docs](https://www.scenedetect.com/docs/latest/api.html).

## Prompt Library

The reusable prompts live in [ops/prompt-library/shorts-engine-prompts.md](/Users/grisaavdeev/Downloads/thumbnails/ops/prompt-library/shorts-engine-prompts.md). Core prompt families:

- `ClipMinerAgent`
  - over-generate candidates from transcript, pause, and scene evidence
- `Reranker`
  - apply the fixed weighted formula and penalties
- `EditDirectorAgent`
  - assign crop, subtitle, silence trim, B-roll, and export decisions
- `CaptionCopyAgent`
  - write platform-specific copy without overclaiming
- `QAAgent`
  - reject clips with context debt, crop errors, or misleading packaging
- `FeedbackAgent`
  - analyze winners and losers and classify learnings as adopt, keep testing, or stop

Prompt design principles:

- demand structured outputs
- ask for rationale, not just scores
- force the model to explain uncertainty
- keep topic constraints in the intake, not hidden in downstream prompts
- separate selection from packaging so titles do not contaminate ranking

## Tool Stack Comparison

| Tool | Best for | Strengths | Weaknesses | Recommended role |
| --- | --- | --- | --- | --- |
| `Vizard` | API-first long-video repurposing | clipping, captions, templates, silence trim, headline overlays, publish endpoint | closed scoring logic, template dependence | baseline editor and scheduler integration |
| `Descript` | human refinement | transcript correction, natural cleanup, editorial control | less automation-first than API clippers | QA override and manual polish |
| `Captions` | aggressive repurposing and packaging | multi-clip repurpose flow, subtitles, AI packaging | can push toward generic templated outputs | alternative packaging layer |
| `Riverside Magic Clips` | creator-native recording workflows | fast clip suggestions tied to recording workflow | lighter control surface for custom ranking | ingest-side acceleration |
| `OpusClip` | creator-facing clipping and caption tooling | mature short-form positioning and packaging | ranking logic is mostly opaque | compare against, not depend on |
| `FFmpeg + templates` | lowest marginal cost, max control | deterministic, scriptable, cheap at scale | more engineering effort | final fallback and cost-control lane |
| `n8n` | orchestration | flexible integrations and approval steps | requires workflow discipline | backbone orchestrator |

Recommendation:

- v1 default: `n8n + OpenAI ASR + PySceneDetect + Vizard + human QA`
- v1 fallback lane: `n8n + Whisper + pyannote + FFmpeg templates`
- use `Descript` for exception handling, not as the main batch engine

## Scaling Strategy

### Phase 1: Assisted operation

- one source video at a time
- `5-10` clips target
- strongest human QA
- goal: establish pattern library and failure taxonomy

### Phase 2: Batch repurposing

- multiple source videos per week
- `10-20` clips target
- partial auto-scheduling after approval
- compare vendors against the custom reranker

### Phase 3: Content engine

- dedicated content backlog
- topic clustering and reuse of validated hook families
- schedule by platform and audience segment
- post-level learning loop updates prompts and candidate heuristics

### Phase 4: Model advantage

- train a domain-specific reranker or preference model on accepted versus rejected clips
- learn per-niche hook priors
- learn crop-risk and context-debt predictors

Scaling rule:

- scale only on validated patterns
- never increase output volume faster than QA capacity
- keep one stable structure while testing one major variable at a time

## KPI & Optimization Loop

Primary KPIs:

- clip yield per source video
- approval rate after QA
- viewed vs swiped away or equivalent opening metric
- average view duration
- average percentage viewed
- completion rate
- rewatches
- shares
- saves
- profile or long-form clicks

Operational KPIs:

- time from ingest to approved drafts
- render failure rate
- caption correction rate
- crop failure rate
- duplicate-clip rejection rate

Recommended read windows:

- `1 hour`: early opening performance and obvious duds
- `24 hours`: first platform distribution signal
- `72 hours`: stable first-pass comparison set
- `7 days`: delayed pickup and replay behavior

Optimization loop:

1. compare clips by hook family
2. compare by length bucket
3. compare by caption style
4. compare by edit density
5. compare by topic cluster
6. classify each tactic:
   - adopt
   - keep testing
   - stop

Guardrails:

- do not chase views if context quality falls
- do not keep a pattern if it lifts opening conversion but hurts completion badly
- do not infer a permanent rule from one winner

## Failure Modes

| Failure mode | Why it happens | Detection | Mitigation |
| --- | --- | --- | --- |
| Transcript hallucination | bad ASR or noisy audio | low-confidence words, reviewer catches meaning drift | correction pass, fallback ASR, reject weak clip |
| Broken diarization | overlapping speakers or crosstalk | speaker turns look implausible | pyannote fallback, manual repair |
| Context debt | clip starts after key setup | QA confusion or low self-containment score | expand boundary or reject |
| Crop failure | auto-reframe misses the active speaker | face exits frame or mouth covered by captions | lock crop track or reject |
| Over-trimmed silence | silence removal becomes choppy | unnatural cadence | cap trim aggressiveness and keep pauses |
| Duplicate shortlist | many clips from same moment | low novelty score | duplicate groups and diversification |
| Weak ending | clip stops before payoff lands | low payoff score, user confusion | extend or reject |
| Misleading packaging | headline promises more than the clip proves | QA copy review | rewrite title and overlay |
| Vendor lock-in | hidden scoring logic shapes output | inability to explain ranking | persist your own features and score |
| Autoposting mistake | schedule posts without review | wrong caption, wrong crop, off-brand | human approval gate |

## Implementation Roadmap

### Sprint 1: Research pack and operating assets

- ship this dossier
- ship the workflow, prompt library, intake template, and evidence log
- align on one baseline stack

### Sprint 2: Ingest, ASR, and segmentation

- implement `VideoIngestRequest`
- wire `gpt-4o-transcribe-diarize`
- add fallback ASR path
- add scene, pause, and speaker segmentation

Acceptance:

- one `30-90 min` source returns a clean transcript plus structural features

### Sprint 3: Candidate generation and reranking

- implement over-generation
- implement weighted scoring and penalties
- implement duplicate collapse and diversification

Acceptance:

- one source produces `30-80` candidates and a diversified `5-20` shortlist

### Sprint 4: Editing and packaging

- connect Vizard and FFmpeg fallback
- generate edit plans
- generate title, caption, and hashtag variants
- build QA checks

Acceptance:

- every shortlisted clip includes score breakdown, edit plan, and platform copy

### Sprint 5: Scheduling and feedback

- create draft publishing workflow
- capture `1h`, `24h`, `72h`, and `7d` metrics
- update pattern and evidence files after each batch

Acceptance:

- post-performance traces back to source segment and hook variant

## Source Map

Signal legend:

- `Strong`: official docs or accepted papers with direct relevance
- `Medium`: vendor docs or creator reports with direct workflow relevance
- `Weak`: anecdotal workflow evidence useful for experiments only

### Official Docs and Product Sources

| Source | Type | Signal | Used for |
| --- | --- | --- | --- |
| [YouTube Shorts deep dive](https://blog.youtube/creator-and-artist-stories/youtube-shorts-deep-dive/) | official platform blog | Strong | first-second hook importance |
| [Five tips to master Shorts](https://blog.youtube/creator-and-artist-stories/five-tips-to-master-shorts/) | official platform blog | Strong | authenticity, storytelling, creator patterns |
| [YouTube Help: audience retention](https://support.google.com/youtube/answer/9314415?hl=en) | official help | Strong | Shorts retention metrics |
| [YouTube Help: Shorts analytics tips](https://support.google.com/youtube/answer/12942217?co=YOUTUBE._YTVideoType%3Dshorts&hl=en) | official help | Strong | `viewed vs swiped away`, opening analytics |
| [How TikTok recommends content](https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content) | official help | Strong | recommendation factors and skip/watch behavior |
| [TikTok Studio](https://support.tiktok.com/en/using-tiktok/creating-videos/tiktok-studio/) | official help | Strong | trend and inspiration workflow |
| [Meta Best Practices education hub announcement](https://about.fb.com/news/2024/10/best-practices-education-hub-creators-instagram/) | official platform announcement | Medium | Instagram best-practice posture |
| [OpenAI speech-to-text guide](https://developers.openai.com/api/docs/guides/speech-to-text) | official docs | Strong | timestamps and ASR integration |
| [OpenAI API reference snippet on diarize models](https://platform.openai.com/docs/api-reference/realtime-server-events/response/audio/done) | official docs | Strong | diarization-capable transcription model |
| [pyannote speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) | official model card | Strong | fallback diarization path |
| [Vizard advanced options](https://docs.vizard.ai/docs/advanced) | vendor docs | Medium | captions, silence removal, templates, clip counts |
| [Vizard publish docs](https://docs.vizard.ai/docs/publish-clips-to-social-media) | vendor docs | Medium | scheduling and publishing integration |
| [Descript correct transcript](https://help.descript.com/hc/en-us/articles/10119613609229-Correct-your-transcript) | vendor docs | Medium | transcript cleanup workflow |
| [Descript filler words](https://help.descript.com/hc/en-us/articles/10164806394509-Filler-words) | vendor docs | Medium | safe filler-word removal |
| [Riverside Magic Clips help](https://support.riverside.fm/hc/en-us/articles/26473566830877-Magic-Clips-on-mobile-Made-for-you) | vendor docs | Medium | first-pass clip extraction capability |
| [Captions Repurpose AI](https://www.captions.ai/features/repurpose-ai) | vendor product page | Medium | multi-clip repurpose capability |
| [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html) | official docs | Strong | silence detection and removal |
| [PySceneDetect docs](https://www.scenedetect.com/docs/latest/api.html) | official docs | Strong | content-based scene segmentation |

### Academic Research

| Source | Type | Signal | Used for |
| --- | --- | --- | --- |
| [LAVE: LLM-Powered Agent Assistance and Language Augmentation for Video Editing](https://arxiv.org/abs/2402.10294) | IUI 2024 | Strong | agent-assisted editing pattern |
| [Scaling Up Video Summarization Pretraining with Large Language Models](https://openaccess.thecvf.com/content/CVPR2024/papers/Argaw_Scaling_Up_Video_Summarization_Pretraining_with_Large_Language_Models_CVPR_2024_paper.pdf) | CVPR 2024 | Strong | long-video summarization with LLM guidance |
| [Unleash the Potential of CLIP for Video Highlight Detection](https://openaccess.thecvf.com/content/CVPR2024W/ELVM/papers/Han_Unleash_the_Potential_of_CLIP_for_Video_Highlight_Detection_CVPRW_2024_paper.pdf) | CVPRW 2024 | Strong | highlight detection features and benchmarking |
| [Unsupervised Video Highlight Detection by Learning from Audio and Visual Recurrence](https://openaccess.thecvf.com/content/WACV2025/papers/Islam_Unsupervised_Video_Highlight_Detection_by_Learning_from_Audio_and_Visual_WACV_2025_paper.pdf) | WACV 2025 | Strong | audio plus visual highlight priors |
| [Video Summarization with Large Language Models](https://openaccess.thecvf.com/content/CVPR2025/papers/Lee_Video_Summarization_with_Large_Language_Models_CVPR_2025_paper.pdf) | CVPR 2025 | Strong | local-to-global LLM summarization |
| [Chapter-Llama: Efficient Chaptering in Hour-Long Videos with LLMs](https://openaccess.thecvf.com/content/CVPR2025/papers/Ventura_Chapter-Llama_Efficient_Chaptering_in_Hour-Long_Videos_with_LLMs_CVPR_2025_paper.pdf) | CVPR 2025 | Strong | hour-long segmentation and chaptering |
| [Rhapsody: A Dataset for Highlight Detection in Podcasts](https://arxiv.org/abs/2505.19429) | COLM 2025 | Strong | podcast-specific highlight detection limits |
| [StreamHover: Livestream Transcript Summarization and Annotation](https://aclanthology.org/2021.emnlp-main.520/) | EMNLP 2021 | Strong | transcript summarization for spoken media |

### Creator, Community, and Workflow Signals

| Source | Type | Signal | Used for |
| --- | --- | --- | --- |
| [Adam Fishman on X](https://x.com/fishmanaf/status/1968116125708976354) | creator thread | Medium | clip suggestions plus social draft workflow |
| [John on X](https://x.com/johnvirality/status/2036444247486853261) | creator thread | Weak | specificity, hook testing, watch-through framing |
| [r/n8n: automated shorts and reels creation](https://www.reddit.com/r/n8n/comments/1h09744/automated_shorts_and_reels_creation_with_n8n_full/) | community workflow | Weak | n8n orchestration pattern |
| [r/n8n: bot finds viral moments and schedules](https://www.reddit.com/r/n8n/comments/1oanfs8/) | community workflow | Weak | end-to-end automation pattern |
| [r/n8n: full Shorts and Reels automation system](https://www.reddit.com/r/n8n/comments/1lcrni6/i_built_a_full_shorts_reels_automation_system/) | community workflow | Weak | local-first automation stack |
| [r/n8n: viral reels script generator](https://www.reddit.com/r/n8n/comments/1lw54l2/viral_reels_script_generator_workflow_n8n/) | community workflow | Weak | hook generation and iteration flow |
| [r/n8n: trend analysis to script ideas](https://www.reddit.com/r/n8n/comments/1on7hl3/i_built_a_workflow_that_analyzes_trending_instagram_reels_and_auto_generates_viral_script_ideas/) | community workflow | Weak | trend ingestion workflow |
| [r/NewTubers: viewed vs swiped away dropped](https://www.reddit.com/r/NewTubers/comments/1dvjtay/shorts_viewed_vs_swiped_away_dropped_recently/) | creator discussion | Weak | opening metric behavior in practice |
| [r/NewTubers: short views are non existent](https://www.reddit.com/r/NewTubers/comments/1pg17hm/short_views_are_non_existent/) | creator discussion | Weak | first `3s` hook iteration heuristic |
| [r/NewTubers: views dropping despite quality](https://www.reddit.com/r/NewTubers/comments/1r62msl/why_are_my_views_dropping_even_though_my_videos/) | creator discussion | Weak | topic fidelity and distribution |

### Workflow, Blog, and Case Study Sources

| Source | Type | Signal | Used for |
| --- | --- | --- | --- |
| [n8n workflow: convert Reddit threads into short vertical videos](https://n8n.io/workflows/3407-convert-reddit-threads-into-short-vertical-videos-with-ai/) | workflow template | Weak | pipeline composition example |
| [n8n workflow: daily AI and automation content digest](https://n8n.io/workflows/12703-create-a-daily-ai-and-automation-content-digest-from-youtube-reddit-x-and-perplexity-with-openai-and-airtable/) | workflow template | Weak | multi-source content research ingestion |
| [n8n workflow: monitor social media trends across Reddit, Instagram, and TikTok](https://n8n.io/workflows/8450-monitor-social-media-trends-across-reddit-instagram-and-tiktok-with-apify/) | workflow template | Weak | trend monitoring input layer |
| [Flowpast: Firecrawl to Instagram Reels posts ready to publish](https://flowpast.com/n8n/firecrawl-to-instagram-reels-posts-ready-to-publish/) | workflow article | Weak | automated article-to-reels pipeline design |
| [OpusClip blog: video captioning tools](https://www.opus.pro/blog/video-captioning-tools) | vendor blog | Weak | market positioning and captioning workflow context |

Bottom line:

- Strong evidence supports multimodal understanding, custom ranking, and human QA.
- Medium evidence supports using commercial AI editors for speed.
- Weak evidence suggests testing disciplined hook libraries, trend ingestion, and batch automation, but only as experiments until channel data confirms them.

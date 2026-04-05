# Notes

## Locked Defaults

- Primary source material: talking-head interviews, podcasts, webinars, and educational conversations.
- Primary optimization target: YouTube Shorts.
- Secondary packaging targets: TikTok and Instagram Reels.
- Publish mode: human approval before any live post.
- Core stack shape: hybrid SaaS plus automation, with a custom ranking layer.

## Evidence Policy

- Official platform and product docs are the source of truth for metrics, APIs, limits, and recommendation logic.
- Accepted academic papers inform segmentation, summarization, highlight detection, and agent design.
- Creator threads, Reddit discussions, and workflow showcases are heuristic inputs only.
- Vendor "viral score" claims are capability signals, not ranking truth.

## Non-Negotiables

- Do not let a vendor score decide the final shortlist by itself.
- Do not autopost without a human QA gate.
- Do not ship clips that require missing context from the long-form video.
- Do not over-trim silence to the point that speech sounds synthetic or frantic.
- Do not mix short-form pattern memory with the thumbnail pattern library.

## Open Questions For V2

- Whether to train a domain-specific reranker on accepted and rejected clips.
- Whether to support code-heavy screen demo sources as a first-class content type.
- Whether to store face tracks and crop tracks in a lightweight feature store for later model training.

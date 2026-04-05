from dataclasses import dataclass


@dataclass(slots=True)
class StubTranscriptWord:
    seq_no: int
    start_ms: int
    end_ms: int
    token: str
    speaker: str
    confidence: float


@dataclass(slots=True)
class StubTranscriptSegment:
    seq_no: int
    start_ms: int
    end_ms: int
    speaker: str
    text: str
    pause_before_ms: int
    pause_after_ms: int
    energy_score: float


@dataclass(slots=True)
class StubTranscriptPayload:
    provider: str
    provider_version: str
    words: list[StubTranscriptWord]
    segments: list[StubTranscriptSegment]


def build_stub_transcript(*, language: str | None, speaker_count_estimate: int | None) -> StubTranscriptPayload:
    speaker = "spk_01"
    segments_text = [
        "The first second decides whether a short survives the swipe.",
        "Most editors waste time polishing weak moments instead of finding stronger openings.",
        "Transcript cues, pauses, and audio energy usually beat raw visual analysis for talking head content.",
        "A good clipping system should over generate candidates, rank them, and keep only the tightest payoff windows.",
    ]
    text = " ".join(segments_text)
    tokens = text.split()
    words: list[StubTranscriptWord] = []
    current_ms = 0
    for index, token in enumerate(tokens, start=1):
        duration_ms = 320 if len(token) < 8 else 420
        words.append(
            StubTranscriptWord(
                seq_no=index,
                start_ms=current_ms,
                end_ms=current_ms + duration_ms,
                token=token,
                speaker=speaker,
                confidence=0.99,
            )
        )
        current_ms += duration_ms + 40

    segments: list[StubTranscriptSegment] = []
    offset = 0
    for seq_no, segment_text in enumerate(segments_text, start=1):
        segment_tokens = segment_text.split()
        segment_words = words[offset : offset + len(segment_tokens)]
        segments.append(
            StubTranscriptSegment(
                seq_no=seq_no,
                start_ms=segment_words[0].start_ms,
                end_ms=segment_words[-1].end_ms,
                speaker=speaker,
                text=segment_text,
                pause_before_ms=120 if seq_no == 1 else 240,
                pause_after_ms=160 if seq_no < len(segments_text) else 90,
                energy_score=(0.62 + seq_no * 0.05) if language else (0.52 + seq_no * 0.04),
            )
        )
        offset += len(segment_tokens)
    provider_version = "stub-v1-2spk" if (speaker_count_estimate or 1) > 1 else "stub-v1-1spk"
    return StubTranscriptPayload(
        provider="stub",
        provider_version=provider_version,
        words=words,
        segments=segments,
    )

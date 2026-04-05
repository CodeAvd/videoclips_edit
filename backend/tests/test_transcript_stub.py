from app.services.transcript_stub import build_stub_transcript


def test_stub_transcript_produces_words_and_segments() -> None:
    payload = build_stub_transcript(language="en", speaker_count_estimate=1)
    assert payload.provider == "stub"
    assert payload.words
    assert payload.segments
    assert payload.words[0].start_ms == 0
    assert payload.segments[0].text

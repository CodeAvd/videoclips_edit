import httpx

from app.core.config import Settings
from app.services.transcript_provider import build_transcript_provider_chain, transcribe_with_fallback


def build_verbose_payload() -> dict:
    return {
        "language": "en",
        "words": [
            {"word": "This", "start": 0.0, "end": 0.3},
            {"word": "is", "start": 0.31, "end": 0.45},
            {"word": "working.", "start": 0.46, "end": 0.9},
        ],
        "segments": [
            {"id": 0, "start": 0.0, "end": 0.9, "text": "This is working.", "no_speech_prob": 0.05}
        ],
    }


async def test_groq_adapter_normalizes_verbose_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer groq-key"
        return httpx.Response(200, json=build_verbose_payload())

    settings = Settings(
        groq_api_key="groq-key",
        asr_provider_primary="groq",
        asr_provider_fallback="",
    )
    payload = await transcribe_with_fallback(
        filename="audio.wav",
        content_type="audio/wav",
        body=b"wav-bytes",
        language_hint="en",
        settings=settings,
        transport=httpx.MockTransport(handler),
    )
    assert payload.provider == "groq"
    assert payload.words[0].token == "This"
    assert payload.segments[0].text == "This is working."


async def test_openai_fallback_is_used_when_primary_unconfigured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer openai-key"
        return httpx.Response(200, json=build_verbose_payload())

    settings = Settings(
        asr_provider_primary="groq",
        asr_provider_fallback="openai",
        openai_api_key="openai-key",
    )
    providers = build_transcript_provider_chain(settings=settings, transport=httpx.MockTransport(handler))
    assert [provider.provider_name for provider in providers] == ["openai"]

    payload = await transcribe_with_fallback(
        filename="audio.wav",
        content_type="audio/wav",
        body=b"wav-bytes",
        language_hint="en",
        settings=settings,
        transport=httpx.MockTransport(handler),
    )
    assert payload.provider == "openai"
    assert payload.words[-1].token == "working."

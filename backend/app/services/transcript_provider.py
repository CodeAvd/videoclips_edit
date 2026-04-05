from __future__ import annotations

import asyncio
from dataclasses import dataclass
from math import isfinite
from typing import Protocol
from uuid import uuid4

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.services.transcript_stub import build_stub_transcript


@dataclass(slots=True)
class TranscriptWordItem:
    seq_no: int
    start_ms: int
    end_ms: int
    token: str
    speaker: str | None
    confidence: float | None


@dataclass(slots=True)
class TranscriptSegmentItem:
    seq_no: int
    start_ms: int
    end_ms: int
    speaker: str | None
    text: str
    pause_before_ms: int | None
    pause_after_ms: int | None
    energy_score: float | None


@dataclass(slots=True)
class TranscriptRevisionPayload:
    provider: str
    provider_version: str
    language: str | None
    adapter_metadata: dict
    raw_payload: dict
    words: list[TranscriptWordItem]
    segments: list[TranscriptSegmentItem]


class TranscriptProvider(Protocol):
    provider_name: str

    async def transcribe_bytes(
        self,
        *,
        filename: str,
        content_type: str,
        body: bytes,
        language_hint: str | None,
        diarization_mode: str | None,
    ) -> TranscriptRevisionPayload:
        ...


def clamp_score(value: float | None, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    if not isfinite(value):
        return default
    return max(0.0, min(1.0, value))


def seconds_to_ms(value: float | int | str | None) -> int:
    if value is None:
        return 0
    return max(0, int(round(float(value) * 1000)))


def build_segments_from_words(words: list[TranscriptWordItem]) -> list[TranscriptSegmentItem]:
    if not words:
        return []
    segment_words: list[list[TranscriptWordItem]] = []
    current_segment: list[TranscriptWordItem] = []
    for word in words:
        current_segment.append(word)
        token = word.token.strip()
        if token.endswith((".", "?", "!")) or len(current_segment) >= 18:
            segment_words.append(current_segment)
            current_segment = []
    if current_segment:
        segment_words.append(current_segment)

    items: list[TranscriptSegmentItem] = []
    for seq_no, group in enumerate(segment_words, start=1):
        text = " ".join(word.token for word in group).strip()
        items.append(
            TranscriptSegmentItem(
                seq_no=seq_no,
                start_ms=group[0].start_ms,
                end_ms=group[-1].end_ms,
                speaker=group[0].speaker,
                text=text,
                pause_before_ms=None,
                pause_after_ms=None,
                energy_score=None,
            )
        )
    return with_segment_pauses(items)


def with_segment_pauses(segments: list[TranscriptSegmentItem]) -> list[TranscriptSegmentItem]:
    if not segments:
        return []
    normalized: list[TranscriptSegmentItem] = []
    for index, segment in enumerate(segments):
        previous = segments[index - 1] if index > 0 else None
        following = segments[index + 1] if index + 1 < len(segments) else None
        pause_before_ms = None if previous is None else max(0, segment.start_ms - previous.end_ms)
        pause_after_ms = None if following is None else max(0, following.start_ms - segment.end_ms)
        normalized.append(
            TranscriptSegmentItem(
                seq_no=segment.seq_no,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                speaker=segment.speaker,
                text=segment.text,
                pause_before_ms=pause_before_ms,
                pause_after_ms=pause_after_ms,
                energy_score=segment.energy_score,
            )
        )
    return normalized


def normalize_verbose_json_payload(
    *,
    provider_name: str,
    provider_version: str,
    language_hint: str | None,
    raw_payload: dict,
) -> TranscriptRevisionPayload:
    raw_words = raw_payload.get("words") or []
    words: list[TranscriptWordItem] = []
    for seq_no, raw_word in enumerate(raw_words, start=1):
        token = str(raw_word.get("word") or raw_word.get("token") or "").strip()
        if not token:
            continue
        words.append(
            TranscriptWordItem(
                seq_no=seq_no,
                start_ms=seconds_to_ms(raw_word.get("start")),
                end_ms=seconds_to_ms(raw_word.get("end")),
                token=token,
                speaker=raw_word.get("speaker"),
                confidence=clamp_score(raw_word.get("confidence")),
            )
        )
    if not words:
        raise AppError(
            code="transcript_unusable",
            message="ASR provider did not return usable word timestamps.",
            http_status=422,
        )

    raw_segments = raw_payload.get("segments") or []
    segments: list[TranscriptSegmentItem] = []
    for seq_no, raw_segment in enumerate(raw_segments, start=1):
        text = str(raw_segment.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            TranscriptSegmentItem(
                seq_no=seq_no,
                start_ms=seconds_to_ms(raw_segment.get("start")),
                end_ms=seconds_to_ms(raw_segment.get("end")),
                speaker=raw_segment.get("speaker"),
                text=text,
                pause_before_ms=None,
                pause_after_ms=None,
                energy_score=clamp_score(1.0 - float(raw_segment.get("no_speech_prob", 0.5)), default=None),
            )
        )
    if not segments:
        segments = build_segments_from_words(words)
    else:
        segments = with_segment_pauses(segments)

    language = raw_payload.get("language") or language_hint
    return TranscriptRevisionPayload(
        provider=provider_name,
        provider_version=provider_version,
        language=language,
        adapter_metadata={
            "response_format": "verbose_json",
            "timestamp_granularities": ["word", "segment"],
            "language_hint": language_hint,
        },
        raw_payload=raw_payload,
        words=words,
        segments=segments,
    )


class StubTranscriptProvider:
    provider_name = "stub"

    async def transcribe_bytes(
        self,
        *,
        filename: str,
        content_type: str,
        body: bytes,
        language_hint: str | None,
        diarization_mode: str | None,
    ) -> TranscriptRevisionPayload:
        stub = build_stub_transcript(language=language_hint, speaker_count_estimate=1)
        return TranscriptRevisionPayload(
            provider=stub.provider,
            provider_version=stub.provider_version,
            language=language_hint,
            adapter_metadata={
                "filename": filename,
                "content_type": content_type,
                "diarization_mode": diarization_mode,
                "stub": True,
            },
            raw_payload={
                "provider": stub.provider,
                "provider_version": stub.provider_version,
                "stub": True,
            },
            words=[
                TranscriptWordItem(
                    seq_no=word.seq_no,
                    start_ms=word.start_ms,
                    end_ms=word.end_ms,
                    token=word.token,
                    speaker=word.speaker,
                    confidence=word.confidence,
                )
                for word in stub.words
            ],
            segments=[
                TranscriptSegmentItem(
                    seq_no=segment.seq_no,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    speaker=segment.speaker,
                    text=segment.text,
                    pause_before_ms=segment.pause_before_ms,
                    pause_after_ms=segment.pause_after_ms,
                    energy_score=segment.energy_score,
                )
                for segment in stub.segments
            ],
        )


class HttpTranscriptProvider:
    provider_name = "http"

    @staticmethod
    def _build_multipart_body(
        *,
        filename: str,
        content_type: str,
        body: bytes,
        fields: list[tuple[str, str]],
    ) -> tuple[bytes, str]:
        boundary = f"----ai-shorts-{uuid4().hex}"
        chunks: list[bytes] = []
        for key, value in fields:
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                body,
                b"\r\n",
                f"--{boundary}--\r\n".encode("utf-8"),
            ]
        )
        return b"".join(chunks), boundary

    def __init__(
        self,
        *,
        provider_name: str,
        api_key: str,
        endpoint_url: str,
        model: str,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider_name = provider_name
        self._api_key = api_key
        self._endpoint_url = endpoint_url
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def _post_transcription(
        self,
        *,
        filename: str,
        content_type: str,
        body: bytes,
        language_hint: str | None,
        diarization_mode: str | None,
    ) -> httpx.Response:
        data: list[tuple[str, str]] = [
            ("model", self._model),
            ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
        ]
        if language_hint:
            data.append(("language", language_hint))
        if diarization_mode:
            data.append(("diarization_mode", diarization_mode))
        multipart_body, boundary = self._build_multipart_body(
            filename=filename,
            content_type=content_type,
            body=body,
            fields=data,
        )
        with httpx.Client(timeout=self._timeout_seconds, transport=self._transport) as client:
            return client.post(
                self._endpoint_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
                content=multipart_body,
            )

    async def transcribe_bytes(
        self,
        *,
        filename: str,
        content_type: str,
        body: bytes,
        language_hint: str | None,
        diarization_mode: str | None,
    ) -> TranscriptRevisionPayload:
        try:
            response = await asyncio.to_thread(
                self._post_transcription,
                filename=filename,
                content_type=content_type,
                body=body,
                language_hint=language_hint,
                diarization_mode=diarization_mode,
            )
        except httpx.TimeoutException as exc:
            raise AppError(
                code="asr_timeout",
                message=f"{self.provider_name} transcription timed out.",
                http_status=503,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                code="asr_transport_error",
                message=f"{self.provider_name} transcription request failed.",
                http_status=503,
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            retryable = response.status_code in {408, 409, 429, 500, 502, 503, 504}
            error_payload: dict
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = {"text": response.text}
            raise AppError(
                code="asr_provider_error",
                message=f"{self.provider_name} transcription failed.",
                http_status=503 if retryable else 422,
                details={"provider": self.provider_name, "status_code": response.status_code, "payload": error_payload},
                retryable=retryable,
            )

        payload = response.json()
        normalized = normalize_verbose_json_payload(
            provider_name=self.provider_name,
            provider_version=self._model,
            language_hint=language_hint,
            raw_payload=payload,
        )
        normalized.adapter_metadata["diarization_mode"] = diarization_mode
        normalized.adapter_metadata["endpoint_url"] = self._endpoint_url
        return normalized


class GroqTranscriptProvider(HttpTranscriptProvider):
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not settings.groq_api_key:
            raise AppError(
                code="asr_provider_unconfigured",
                message="Groq ASR provider is not configured.",
                http_status=500,
            )
        super().__init__(
            provider_name="groq",
            api_key=settings.groq_api_key,
            endpoint_url=settings.groq_base_url,
            model=settings.groq_asr_model,
            timeout_seconds=settings.asr_timeout_seconds,
            transport=transport,
        )


class OpenAiTranscriptProvider(HttpTranscriptProvider):
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not settings.openai_api_key:
            raise AppError(
                code="asr_provider_unconfigured",
                message="OpenAI ASR provider is not configured.",
                http_status=500,
            )
        super().__init__(
            provider_name="openai",
            api_key=settings.openai_api_key,
            endpoint_url=settings.openai_base_url,
            model=settings.openai_asr_model,
            timeout_seconds=settings.asr_timeout_seconds,
            transport=transport,
        )


def build_transcript_provider_chain(
    *,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[TranscriptProvider]:
    active_settings = settings or get_settings()
    order = [active_settings.asr_provider_primary, active_settings.asr_provider_fallback]
    providers: list[TranscriptProvider] = []
    for provider_name in order:
        if not provider_name:
            continue
        if provider_name == "stub":
            providers.append(StubTranscriptProvider())
            continue
        if provider_name == "groq":
            try:
                providers.append(GroqTranscriptProvider(active_settings, transport=transport))
            except AppError:
                continue
            continue
        if provider_name == "openai":
            try:
                providers.append(OpenAiTranscriptProvider(active_settings, transport=transport))
            except AppError:
                continue
            continue
    if not providers:
        raise AppError(
            code="asr_provider_unconfigured",
            message="No transcript providers are configured.",
            http_status=500,
        )
    return providers


async def transcribe_with_fallback(
    *,
    filename: str,
    content_type: str,
    body: bytes,
    language_hint: str | None,
    diarization_mode: str | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> TranscriptRevisionPayload:
    chain = build_transcript_provider_chain(settings=settings, transport=transport)
    last_error: AppError | None = None
    for provider in chain:
        try:
            return await provider.transcribe_bytes(
                filename=filename,
                content_type=content_type,
                body=body,
                language_hint=language_hint,
                diarization_mode=diarization_mode,
            )
        except AppError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise AppError(
        code="transcript_unavailable",
        message="Transcript providers did not return a usable result.",
        http_status=503,
        retryable=True,
    )

from __future__ import annotations

import asyncio
import json
import mimetypes
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import AppError


@dataclass(slots=True)
class MediaProbe:
    duration_ms: int | None
    has_video: bool
    has_audio: bool
    width: int | None
    height: int | None


@dataclass(slots=True)
class IngestOutput:
    normalized_audio_bytes: bytes
    proxy_video_bytes: bytes
    thumbnails_payload: dict
    probe: MediaProbe


async def run_command(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        return
    raise AppError(
        code="media_processing_failed",
        message="ffmpeg media processing failed.",
        http_status=422,
        details={
            "command": list(args),
            "stdout": stdout.decode("utf-8", errors="ignore"),
            "stderr": stderr.decode("utf-8", errors="ignore"),
        },
    )


async def probe_media(input_path: Path) -> MediaProbe:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height",
        "-of",
        "json",
        str(input_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise AppError(
            code="media_probe_failed",
            message="ffprobe could not inspect the source media.",
            http_status=422,
            details={"stderr": stderr.decode("utf-8", errors="ignore")},
        )
    payload = json.loads(stdout.decode("utf-8") or "{}")
    streams = payload.get("streams") or []
    has_video = any(stream.get("codec_type") == "video" for stream in streams)
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    first_video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    duration_seconds = payload.get("format", {}).get("duration")
    duration_ms = int(round(float(duration_seconds) * 1000)) if duration_seconds else None
    return MediaProbe(
        duration_ms=duration_ms,
        has_video=has_video,
        has_audio=has_audio,
        width=first_video.get("width"),
        height=first_video.get("height"),
    )


def extension_for_filename(filename: str, content_type: str) -> str:
    suffix = Path(filename).suffix
    if suffix:
        return suffix
    guessed = mimetypes.guess_extension(content_type or "")
    return guessed or ".bin"


async def build_ingest_outputs(*, filename: str, content_type: str, body: bytes) -> IngestOutput:
    with tempfile.TemporaryDirectory(prefix="ai-shorts-ingest-") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / f"source{extension_for_filename(filename, content_type)}"
        input_path.write_bytes(body)

        probe = await probe_media(input_path)
        if not probe.has_audio:
            raise AppError(
                code="media_missing_audio",
                message="Source media must contain an audio track.",
                http_status=422,
            )

        audio_path = temp_path / "normalized_audio.wav"
        await run_command(
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(audio_path),
        )

        proxy_path = temp_path / "proxy.mp4"
        if probe.has_video:
            await run_command(
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-vf",
                "scale='min(720,iw)':-2",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-an",
                str(proxy_path),
            )
            proxy_video_bytes = proxy_path.read_bytes()
        else:
            proxy_video_bytes = b""

        thumbnails_payload = {
            "probe": {
                "duration_ms": probe.duration_ms,
                "has_video": probe.has_video,
                "has_audio": probe.has_audio,
                "width": probe.width,
                "height": probe.height,
            },
            "frames": [],
        }
        return IngestOutput(
            normalized_audio_bytes=audio_path.read_bytes(),
            proxy_video_bytes=proxy_video_bytes,
            thumbnails_payload=thumbnails_payload,
            probe=probe,
        )

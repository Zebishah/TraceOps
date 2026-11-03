"""Bounded, transient Groq voice operations. Never create or mutate incidents."""

import asyncio
import io
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

import httpx
from fastapi import HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ops_pilot.cache.redis import get_redis_client
from ops_pilot.core.config import get_settings
from ops_pilot.schemas.voice import VoiceTranscriptionResponse

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_SPEECH_BYTES = 4 * 1024 * 1024
MAX_TRANSCRIPT_BYTES = 256 * 1024
GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio"
TTS_MODEL = "canopylabs/orpheus-v1-english"
_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return {count, redis.call('TTL', KEYS[1])}
"""


class _Transcript(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=50000)


def require_voice_enabled(*, speech: bool = False) -> None:
    settings = get_settings()
    if not settings.voice_enabled or (speech and not settings.voice_tts_enabled):
        raise HTTPException(status_code=503, detail="Requested voice capability is disabled")


async def enforce_voice_limit(*, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
    settings = get_settings()
    key = f"{settings.redis_key_prefix}:voice:{organization_id}:{user_id}"
    try:
        result = await get_redis_client().eval(_LIMIT_SCRIPT, 1, key)
        count, ttl = int(result[0]), max(1, int(result[1]))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Voice rate limiting unavailable") from exc
    if count > settings.voice_requests_per_minute:
        raise HTTPException(
            status_code=429,
            detail="Too many voice requests",
            headers={"Retry-After": str(ttl)},
        )


@lru_cache
def _voice_slots() -> asyncio.Semaphore:
    return asyncio.Semaphore(2)


@asynccontextmanager
async def _voice_slot() -> AsyncIterator[None]:
    # Bound active provider work and reject excess work instead of building a queue.
    try:
        await asyncio.wait_for(_voice_slots().acquire(), timeout=0.1)
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail="Voice service is busy") from exc
    try:
        yield
    finally:
        _voice_slots().release()


def detect_audio(data: bytes | bytearray) -> tuple[str, str]:
    """Recognize supported container signatures rather than trusting file names."""
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "wav", "audio/wav"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm", "audio/webm"
    if data.startswith(b"OggS"):
        return "ogg", "audio/ogg"
    if data.startswith(b"fLaC"):
        return "flac", "audio/flac"
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224):
        return "mp3", "audio/mpeg"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "m4a", "audio/mp4"
    raise HTTPException(status_code=415, detail="Unsupported audio container")


async def _read_response(response: httpx.Response, *, limit: int) -> bytes:
    if response.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="Voice provider rate limit reached",
            headers={"Retry-After": "60"},
        )
    if response.status_code in {400, 413, 415, 422}:
        raise HTTPException(status_code=422, detail="Voice provider rejected the input")
    if response.status_code >= 300:
        raise HTTPException(status_code=502, detail="Voice provider unavailable")
    chunks = bytearray()
    async for chunk in response.aiter_bytes():
        if len(chunks) + len(chunk) > limit:
            raise HTTPException(status_code=502, detail="Voice provider response exceeds limit")
        chunks.extend(chunk)
    return bytes(chunks)


async def transcribe_audio(*, file: UploadFile, language: str | None) -> VoiceTranscriptionResponse:
    settings = get_settings()
    data = bytearray()
    try:
        while chunk := await file.read(64 * 1024):
            if len(data) + len(chunk) > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail="Audio exceeds 10 MiB limit")
            data.extend(chunk)
        if not data:
            raise HTTPException(status_code=422, detail="Audio recording is empty")
        extension, mime_type = detect_audio(data)
        fields = {"model": settings.voice_transcription_model, "response_format": "json"}
        if language is not None:
            fields["language"] = language
        async with _voice_slot(), asyncio.timeout(settings.voice_timeout_seconds):
            async with httpx.AsyncClient(
                timeout=settings.voice_timeout_seconds, follow_redirects=False
            ) as client:
                with io.BytesIO(data) as audio:
                    async with client.stream(
                        "POST",
                        f"{GROQ_AUDIO_URL}/transcriptions",
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                        files={"file": (f"recording.{extension}", audio, mime_type)},
                        data=fields,
                    ) as response:
                        raw = await _read_response(response, limit=MAX_TRANSCRIPT_BYTES)
        try:
            transcript = _Transcript.model_validate_json(raw)
        except ValidationError as exc:
            raise HTTPException(status_code=502, detail="Invalid transcription response") from exc
        return VoiceTranscriptionResponse(
            text=transcript.text, model=settings.voice_transcription_model
        )
    except (httpx.RequestError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="Voice provider request failed") from exc
    finally:
        await file.close()


async def synthesize_speech(*, text: str) -> bytes:
    settings = get_settings()
    async with _voice_slot():
        try:
            async with asyncio.timeout(settings.voice_timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=settings.voice_timeout_seconds, follow_redirects=False
                ) as client:
                    async with client.stream(
                        "POST",
                        f"{GROQ_AUDIO_URL}/speech",
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                        json={
                            "model": TTS_MODEL,
                            "voice": settings.voice_tts_voice,
                            "input": text,
                            "response_format": "wav",
                        },
                    ) as response:
                        audio = await _read_response(response, limit=MAX_SPEECH_BYTES)
            if not (audio.startswith(b"RIFF") and audio[8:12] == b"WAVE"):
                raise HTTPException(status_code=502, detail="Invalid speech response")
            return audio
        except (httpx.RequestError, TimeoutError) as exc:
            raise HTTPException(status_code=503, detail="Voice provider request failed") from exc

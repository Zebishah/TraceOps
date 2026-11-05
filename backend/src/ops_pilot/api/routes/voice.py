"""Authenticated voice I/O only; transcripts require explicit user confirmation."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile

from ops_pilot.api.dependencies import CurrentUser, IncidentCreatorMembership
from ops_pilot.core.config import get_settings
from ops_pilot.schemas.voice import (
    VoiceCapabilitiesResponse,
    VoiceSpeechRequest,
    VoiceTranscriptionResponse,
)
from ops_pilot.services.voice import (
    MAX_AUDIO_BYTES,
    enforce_voice_limit,
    require_voice_enabled,
    synthesize_speech,
    transcribe_audio,
)

router = APIRouter(prefix="/organizations/{organization_id}/voice", tags=["voice"])


@router.get("/capabilities", response_model=VoiceCapabilitiesResponse)
async def capabilities(
    organization_id: uuid.UUID,
    current_user: CurrentUser,
    membership: IncidentCreatorMembership,
    response: Response,
) -> VoiceCapabilitiesResponse:
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    return VoiceCapabilitiesResponse(
        enabled=settings.voice_enabled,
        speech_enabled=settings.voice_enabled and settings.voice_tts_enabled,
        transcription_model=settings.voice_transcription_model,
        max_audio_bytes=MAX_AUDIO_BYTES,
        requests_per_minute=settings.voice_requests_per_minute,
        supported_containers=["wav", "webm", "ogg", "flac", "mp3", "m4a"],
    )


@router.post("/transcriptions", response_model=VoiceTranscriptionResponse)
async def transcribe(
    organization_id: uuid.UUID,
    current_user: CurrentUser,
    membership: IncidentCreatorMembership,
    file: Annotated[UploadFile, File()],
    language: Annotated[str | None, Form(pattern=r"^[a-z]{2}$")] = None,
) -> Response:
    require_voice_enabled()
    await enforce_voice_limit(organization_id=organization_id, user_id=current_user.id)
    result = await transcribe_audio(file=file, language=language)
    return Response(
        content=result.model_dump_json(exclude_none=True),
        media_type="application/json",
        headers={
            "Cache-Control": "no-store",
        },
    )


@router.post("/speech", response_class=Response, responses={200: {"content": {"audio/wav": {}}}})
async def speak(
    organization_id: uuid.UUID,
    payload: VoiceSpeechRequest,
    current_user: CurrentUser,
    membership: IncidentCreatorMembership,
) -> Response:
    require_voice_enabled(speech=True)
    await enforce_voice_limit(organization_id=organization_id, user_id=current_user.id)
    audio = await synthesize_speech(text=payload.text)
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="opspilot-speech.wav"',
        },
    )

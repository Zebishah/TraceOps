"""Voice requests remain separate from incident creation and approval."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VoiceTranscriptionResponse(BaseModel):
    text: str
    model: str
    requires_confirmation: Literal[True] = True
    detected_language: str | None = None
    warning: str | None = None


class VoiceCapabilitiesResponse(BaseModel):
    enabled: bool
    speech_enabled: bool
    transcription_model: str
    max_audio_bytes: int
    requests_per_minute: int
    supported_containers: list[str]
    max_speech_characters: int = 200
    requires_confirmation: Literal[True] = True


class VoiceSpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Current Orpheus provider limit. No silent truncation of an investigation.
    text: str = Field(min_length=1, max_length=200)

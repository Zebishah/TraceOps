"""Voice requests remain separate from incident creation and approval."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VoiceTranscriptionResponse(BaseModel):
    text: str
    model: str
    requires_confirmation: Literal[True] = True


class VoiceSpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Current Orpheus provider limit. No silent truncation of an investigation.
    text: str = Field(min_length=1, max_length=200)

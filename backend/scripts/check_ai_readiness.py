"""Explicit live smoke checks. Never creates incidents or approves a model release."""

import argparse
import asyncio
import os
import re
import uuid
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field

from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from ops_pilot.schemas.voice import VoiceCapabilitiesResponse, VoiceTranscriptionResponse
from ops_pilot.services.voice import MAX_AUDIO_BYTES


class SetupCheckError(ValueError):
    """Safe operator messages containing no inputs, tokens or provider response bodies."""


class WorkerReadiness(BaseModel):
    ready: bool = Field(strict=True)
    release_id: str = Field(pattern=r"^[a-f0-9]{64}$")


def safe_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
    ):
        raise SetupCheckError("Use HTTPS, or localhost HTTP, without credentials/query/fragment")
    return value.rstrip("/")


def secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SetupCheckError(f"Set {name} in your shell; do not put secrets in command arguments")
    return value


async def bounded_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    token: str,
    *,
    limit: int = 256 * 1024,
    files: dict[str, tuple[str, BinaryIO, str]] | None = None,
    data: dict[str, str] | None = None,
    json_body: dict[str, str] | None = None,
) -> tuple[bytes, httpx.Headers]:
    async with client.stream(
        method,
        url,
        headers={"Authorization": f"Bearer {token}"},
        files=files,
        data=data,
        json=json_body,
    ) as response:
        if response.status_code != 200:
            raise SetupCheckError(
                f"Service returned HTTP {response.status_code}; check server settings"
            )
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > limit:
                raise SetupCheckError("Service response exceeds the expected limit")
            body.extend(chunk)
        return bytes(body), response.headers


async def check_voice(
    client: httpx.AsyncClient,
    *,
    api_url: str,
    organization_id: uuid.UUID,
    token: str,
    audio: Path | None,
    language: str | None,
) -> None:
    base = safe_url(api_url)
    if urlsplit(base).path:
        raise SetupCheckError("API URL must be the backend origin without /api/v1 or another path")
    prefix = f"{base}/api/v1/organizations/{organization_id}/voice"
    raw, _ = await bounded_request(client, "GET", prefix + "/capabilities", token, limit=8192)
    capabilities = VoiceCapabilitiesResponse.model_validate_json(raw)
    if not capabilities.enabled:
        raise SetupCheckError(
            "Voice is disabled: set VOICE_ENABLED=true on the backend and restart"
        )
    print("PASS voice capability, account access and deployed route")
    if audio is None:
        print("SKIP actual transcription: supply --audio with a short real recording")
        return
    if not audio.is_file() or not 0 < audio.stat().st_size <= MAX_AUDIO_BYTES:
        raise SetupCheckError("Audio must be a nonempty file no larger than 10 MiB")
    if language is not None and not re.fullmatch(r"[a-z]{2}", language):
        raise SetupCheckError("Language must be a two-letter lowercase code")
    with audio.open("rb") as recording:
        raw, _ = await bounded_request(
            client,
            "POST",
            prefix + "/transcriptions",
            token,
            files={"file": (audio.name, recording, "application/octet-stream")},
            data={"language": language} if language else {},
        )
    result = VoiceTranscriptionResponse.model_validate_json(raw)
    if not result.text.strip():
        raise SetupCheckError("Provider returned an empty transcript")
    # A transcript may contain personal data. Do not print or persist it.
    print("PASS actual transcription and confirmation contract; review accuracy in the UI")


async def check_worker(
    client: httpx.AsyncClient, *, worker_url: str, token: str, release: str
) -> None:
    url = safe_url(worker_url)
    if not re.fullmatch(r"[a-f0-9]{64}", release):
        raise SetupCheckError("Worker smoke check requires an approved production release ID")
    parsed = urlsplit(url)
    if parsed.path != "/classify":
        raise SetupCheckError("Worker URL must end in /classify without an extra path prefix")
    health = urlunsplit((parsed.scheme, parsed.netloc, "/health/ready", "", ""))
    raw, _ = await bounded_request(client, "GET", health, token, limit=8192)
    ready = WorkerReadiness.model_validate_json(raw)
    if not ready.ready or ready.release_id != release:
        raise SetupCheckError("Worker readiness or approved release ID does not match")
    raw, headers = await bounded_request(
        client,
        "POST",
        url,
        token,
        limit=4096,
        json_body={
            "title": "Duplicate charge reported",
            "description": "One order produced two completed charges for the customer.",
        },
    )
    ClassifierLabels.model_validate_json(raw)
    if headers.get("X-Classifier-Release") != release:
        raise SetupCheckError("Prediction release ID does not match")
    print("PASS worker readiness, authenticated prediction and release identity")
    print("NOTE one valid prediction does not prove model quality or authorize production")


async def run(args: argparse.Namespace) -> None:
    async with (
        asyncio.timeout(120),
        httpx.AsyncClient(timeout=60, follow_redirects=False) as client,
    ):
        if args.api_url:
            if args.organization_id is None:
                raise SetupCheckError("--organization-id is required with --api-url")
            await check_voice(
                client,
                api_url=args.api_url,
                organization_id=args.organization_id,
                token=secret("OPSPILOT_SMOKE_TOKEN"),
                audio=args.audio,
                language=args.language,
            )
        if args.worker_url:
            await check_worker(
                client,
                worker_url=args.worker_url,
                token=secret("FINETUNED_CLASSIFIER_TOKEN"),
                release=secret("FINETUNED_CLASSIFIER_RELEASE_ID"),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", help="Backend origin, without /api/v1")
    parser.add_argument("--organization-id", type=uuid.UUID)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--language")
    parser.add_argument("--worker-url", help="Private model URL ending in /classify")
    args = parser.parse_args()
    if not args.api_url and not args.worker_url:
        parser.error("Supply --api-url and/or --worker-url")
    if args.audio and not args.api_url:
        parser.error("--audio requires --api-url")
    try:
        asyncio.run(run(args))
    except SetupCheckError as exc:
        print(f"FAIL {exc}")
        raise SystemExit(1) from None
    except (ValueError, OSError, httpx.HTTPError, TimeoutError):
        # Neither provider bodies, environment values, transcripts nor credentials are logged.
        print("FAIL AI smoke check. Check flags, access, credentials, limits and service logs.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

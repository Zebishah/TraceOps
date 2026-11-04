import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from ops_pilot.api.dependencies import get_current_membership, get_current_user
from ops_pilot.api.routes import voice as routes
from ops_pilot.api.voice_limit import VoiceBodyLimitMiddleware
from ops_pilot.core.config import get_settings
from ops_pilot.db.session import get_db_session
from ops_pilot.main import app
from ops_pilot.models.membership import MembershipRole
from ops_pilot.services import voice

ORG = uuid.uuid4()
USER = uuid.uuid4()
PATH = f"/api/v1/organizations/{ORG}/voice"
WAV = b"RIFF" + (40).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 32


@pytest.fixture
def enabled(monkeypatch):
    settings = get_settings().model_copy(update={"voice_enabled": True, "voice_tts_enabled": True})
    monkeypatch.setattr(voice, "get_settings", lambda: settings)
    voice._voice_slots.cache_clear()
    yield settings
    voice._voice_slots.cache_clear()


@pytest.fixture
def client(monkeypatch, enabled):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=USER)
    app.dependency_overrides[get_current_membership] = lambda: SimpleNamespace(
        organization_id=ORG,
        user_id=USER,
        role=MembershipRole.OPERATOR,
    )
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    limit = AsyncMock()
    monkeypatch.setattr(routes, "enforce_voice_limit", limit)
    result = TestClient(app)
    try:
        yield result
    finally:
        result.close()
        app.dependency_overrides.clear()


def provider(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        voice.httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw)
    )


def test_transcription_returns_confirmation_without_creating_incident(client, monkeypatch):
    async def handler(request):
        assert request.url.path.endswith("/audio/transcriptions")
        body = await request.aread()
        assert b"whisper-large-v3-turbo" in body
        assert b"recording.wav" in body
        assert b"unsafe-name.exe" not in body
        return httpx.Response(200, json={"text": "Customer reports two charges."})

    provider(monkeypatch, handler)
    response = client.post(f"{PATH}/transcriptions", files={"file": ("unsafe-name.exe", WAV)})
    assert response.status_code == 200
    assert response.json() == {
        "text": "Customer reports two charges.",
        "model": "whisper-large-v3-turbo",
        "requires_confirmation": True,
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("data,status", [(b"", 422), (b"not audio", 415)])
def test_invalid_audio_never_reaches_provider(client, monkeypatch, data, status):
    def unexpected(request):
        pytest.fail("Invalid audio reached provider")

    provider(monkeypatch, unexpected)
    response = client.post(f"{PATH}/transcriptions", files={"file": ("fake.wav", data)})
    assert response.status_code == status


def test_voice_is_opt_in(client, enabled, monkeypatch):
    enabled.voice_enabled = False
    call = AsyncMock()
    monkeypatch.setattr(routes, "transcribe_audio", call)
    response = client.post(f"{PATH}/transcriptions", files={"file": ("test.wav", WAV)})
    assert response.status_code == 503
    call.assert_not_awaited()


@pytest.mark.parametrize("role", [MembershipRole.VIEWER, MembershipRole.REVIEWER])
def test_voice_requires_incident_creator_role(client, role):
    app.dependency_overrides[get_current_membership] = lambda: SimpleNamespace(role=role)
    assert client.post(f"{PATH}/speech", json={"text": "Summary"}).status_code == 403


def test_voice_requires_authentication(enabled):
    client = TestClient(app)
    assert client.post(f"{PATH}/speech", json={"text": "Summary"}).status_code in {401, 403}


def test_voice_rejects_foreign_organization(enabled):
    session = AsyncMock()
    session.execute.return_value.scalar_one_or_none = lambda: None
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=USER)
    app.dependency_overrides[get_db_session] = lambda: session
    try:
        client = TestClient(app)
        assert client.post(f"{PATH}/speech", json={"text": "Summary"}).status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("status,expected", [(429, 429), (401, 502), (503, 502), (400, 422)])
def test_provider_errors_are_sanitized(client, monkeypatch, status, expected):
    provider(monkeypatch, lambda request: httpx.Response(status, text="secret provider diagnostic"))
    response = client.post(f"{PATH}/transcriptions", files={"file": ("test.wav", WAV)})
    assert response.status_code == expected
    assert "secret" not in response.text


@pytest.mark.parametrize("payload", [{"text": ""}, {"wrong": "field"}])
def test_invalid_transcript_rejected(client, monkeypatch, payload):
    provider(monkeypatch, lambda request: httpx.Response(200, json=payload))
    assert (
        client.post(f"{PATH}/transcriptions", files={"file": ("test.wav", WAV)}).status_code == 502
    )


def test_speech_returns_wav(client, monkeypatch):
    def handler(request):
        assert request.url.path.endswith("/speech")
        assert b"canopylabs/orpheus-v1-english" in request.content
        return httpx.Response(200, content=WAV)

    provider(monkeypatch, handler)
    response = client.post(f"{PATH}/speech", json={"text": "Investigation requires human review."})
    assert response.status_code == 200
    assert response.content == WAV
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"


def test_speech_is_separately_gated(client, enabled):
    enabled.voice_tts_enabled = False
    assert client.post(f"{PATH}/speech", json={"text": "Summary"}).status_code == 503


@pytest.mark.parametrize("text", ["", " ", "x" * 201])
def test_speech_text_limits(client, text):
    assert client.post(f"{PATH}/speech", json={"text": text}).status_code == 422


def test_language_validation(client):
    response = client.post(
        f"{PATH}/transcriptions",
        files={"file": ("test.wav", WAV)},
        data={"language": "not-a-language"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("active", [False, True])
def test_voice_capabilities_allow_ui_to_discover_flags(client, enabled, monkeypatch, active):
    enabled.voice_enabled = active
    monkeypatch.setattr(routes, "get_settings", lambda: enabled)
    response = client.get(f"{PATH}/capabilities")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "enabled": active,
        "speech_enabled": active,
        "transcription_model": "whisper-large-v3-turbo",
        "max_audio_bytes": 10 * 1024 * 1024,
        "requests_per_minute": 10,
        "supported_containers": ["wav", "webm", "ogg", "flac", "mp3", "m4a"],
        "max_speech_characters": 200,
        "requires_confirmation": True,
    }
    assert "token" not in response.text


@pytest.mark.parametrize("role", [MembershipRole.VIEWER, MembershipRole.REVIEWER])
def test_voice_capabilities_enforce_creator_role(client, role):
    app.dependency_overrides[get_current_membership] = lambda: SimpleNamespace(role=role)
    assert client.get(f"{PATH}/capabilities").status_code == 403


def test_browser_webm_upload_and_language_are_forwarded(client, monkeypatch):
    async def handler(request):
        body = await request.aread()
        assert b"recording.webm" in body
        assert b"audio/webm" in body
        assert b'name="language"' in body and b"ur" in body
        return httpx.Response(200, json={"text": "Customer reports a payment issue."})

    provider(monkeypatch, handler)
    response = client.post(
        f"{PATH}/transcriptions",
        files={"file": ("recording.webm", b"\x1a\x45\xdf\xa3" + b"test recording", "audio/webm")},
        data={"language": "ur"},
    )
    assert response.status_code == 200
    assert response.json()["requires_confirmation"] is True


@pytest.mark.asyncio
async def test_voice_rate_limit_fails_closed(monkeypatch, enabled):
    redis = SimpleNamespace(eval=AsyncMock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr(voice, "get_redis_client", lambda: redis)
    with pytest.raises(HTTPException) as error:
        await voice.enforce_voice_limit(organization_id=ORG, user_id=USER)
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_voice_rate_limit_is_user_and_tenant_scoped(monkeypatch, enabled):
    redis = SimpleNamespace(eval=AsyncMock(return_value=[11, 30]))
    monkeypatch.setattr(voice, "get_redis_client", lambda: redis)
    with pytest.raises(HTTPException) as error:
        await voice.enforce_voice_limit(organization_id=ORG, user_id=USER)
    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "30"}
    key = redis.eval.await_args.args[2]
    assert str(ORG) in key and str(USER) in key


@pytest.mark.asyncio
async def test_file_closed_after_oversized_upload(monkeypatch, enabled):
    monkeypatch.setattr(voice, "MAX_AUDIO_BYTES", 10)
    upload = UploadFile(io.BytesIO(WAV), filename="test.wav", headers=Headers())
    with pytest.raises(HTTPException) as error:
        await voice.transcribe_audio(file=upload, language=None)
    assert error.value.status_code == 413
    assert upload.file.closed


@pytest.mark.asyncio
async def test_response_size_is_bounded():
    response = httpx.Response(200, content=b"x" * 20)
    with pytest.raises(HTTPException) as error:
        await voice._read_response(response, limit=10)
    assert error.value.status_code == 502


def test_voice_body_limit_before_json_parsing(client):
    response = client.post(
        f"{PATH}/speech", content=b"x" * 5000, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert client.get("/api/v1/health").status_code == 200


@pytest.mark.asyncio
async def test_chunked_upload_limit():
    downstream = AsyncMock()
    middleware = VoiceBodyLimitMiddleware(downstream)
    receive = AsyncMock(side_effect=[{"type": "http.request", "body": b"x" * 4097}])
    send = AsyncMock()
    await middleware(
        {"type": "http", "method": "POST", "path": f"{PATH}/speech", "headers": []}, receive, send
    )
    assert send.await_args_list[0].args[0]["status"] == 413
    downstream.assert_not_awaited()

import uuid

import httpx
import pytest

from scripts.check_ai_readiness import bounded_request, check_voice, check_worker, safe_url


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.example",
        "https://user:secret@example.com",
        "https://example.com?token=secret",
        "https://example.com/#fragment",
        "file:///tmp/model",
    ],
)
def test_readiness_does_not_send_credentials_to_unsafe_urls(url):
    with pytest.raises(ValueError):
        safe_url(url)


@pytest.mark.asyncio
async def test_live_voice_check_uses_actual_upload_contract_without_logging_text(tmp_path, capsys):
    audio = tmp_path / "short.wav"
    audio.write_bytes(b"RIFF0000WAVEdata")
    paths = []

    async def handler(request):
        paths.append(request.url.path)
        assert request.headers["authorization"] == "Bearer test-session"
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "enabled": True,
                    "speech_enabled": False,
                    "transcription_model": "whisper-large-v3-turbo",
                    "max_audio_bytes": 10485760,
                    "requests_per_minute": 10,
                    "supported_containers": ["wav"],
                },
            )
        assert b"RIFF0000WAVEdata" in await request.aread()
        return httpx.Response(
            200,
            json={
                "text": "private customer information",
                "model": "whisper-large-v3-turbo",
                "requires_confirmation": True,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await check_voice(
            client,
            api_url="https://api.example",
            organization_id=uuid.uuid4(),
            token="test-session",
            audio=audio,
            language="en",
        )
    assert len(paths) == 2
    output = capsys.readouterr().out
    assert "PASS actual transcription" in output
    assert "private customer" not in output and "test-session" not in output


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_stage", ["readiness", "prediction"])
async def test_worker_readiness_check_rejects_release_mismatch(wrong_stage):
    release = "a" * 64
    calls = []

    def handler(request):
        calls.append(request.url.path)
        assert request.headers["authorization"] == "Bearer worker-secret"
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "ready": True,
                    "release_id": "b" * 64 if wrong_stage == "readiness" else release,
                },
            )
        return httpx.Response(
            200,
            json={"category": "payment", "priority": "high"},
            headers={"X-Classifier-Release": "b" * 64},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="release"):
            await check_worker(
                client,
                worker_url="https://worker.example/classify",
                token="worker-secret",
                release=release,
            )
    assert len(calls) == (1 if wrong_stage == "readiness" else 2)


@pytest.mark.asyncio
async def test_worker_readiness_check_exercises_private_prediction(capsys):
    release = "a" * 64

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"ready": True, "release_id": release})
        return httpx.Response(
            200,
            json={"category": "payment", "priority": "high"},
            headers={"X-Classifier-Release": release},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await check_worker(
            client,
            worker_url="https://worker.example/classify",
            token="worker-secret",
            release=release,
        )
    assert "does not prove model quality" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_smoke_check_never_follows_redirect_or_prints_provider_diagnostic():
    def handler(request):
        return httpx.Response(
            307, headers={"Location": "https://attacker.example"}, text="secret upstream diagnostic"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="HTTP 307") as error:
            await bounded_request(client, "GET", "https://api.example", "session")
    assert "secret upstream" not in str(error.value)


@pytest.mark.asyncio
async def test_smoke_response_is_bounded():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 20))
    ) as client:
        with pytest.raises(ValueError, match="limit"):
            await bounded_request(client, "GET", "https://api.example", "session", limit=10)

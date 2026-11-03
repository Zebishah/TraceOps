import asyncio
import uuid

import httpx
import pytest

from ops_pilot.evaluation.identity import discover_evaluation_organizations, evaluation_backend_url


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://api.example.test/", "https://api.example.test"),
        ("https://api.example.test/api/v1", "https://api.example.test"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
    ],
)
def test_evaluation_api_url_validation(value, expected):
    assert evaluation_backend_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://user:secret@api.example.test",
        "http://external.example.test",
        "file:///tmp",
        "https://api.example.test/docs",
        "https://api.example.test/?key=secret",
    ],
)
def test_evaluation_api_rejects_unsafe_urls(value):
    with pytest.raises(ValueError):
        evaluation_backend_url(value)


def test_organization_is_discovered_from_authenticated_me_without_an_id_setting():
    owner_id, viewer_id = uuid.uuid4(), uuid.uuid4()
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "synthetic-test-token"})
        assert request.headers["Authorization"] == "Bearer synthetic-test-token"
        return httpx.Response(
            200,
            json={
                "memberships": [
                    {"organization_id": str(owner_id), "role": "owner"},
                    {"organization_id": str(viewer_id), "role": "viewer"},
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(
            base_url="https://api.example.test", transport=httpx.MockTransport(respond)
        ) as client:
            return await discover_evaluation_organizations(
                client, email="demo@example.test", password="synthetic-test-value"
            )

    organizations = asyncio.run(run())
    assert [item.organization_id for item in organizations] == [owner_id]
    assert calls == ["/api/v1/auth/login", "/api/v1/auth/me"]


@pytest.mark.parametrize("status", [401, 302, 500])
def test_failed_login_does_not_call_me_or_start_evaluations(status):
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(status, json={"detail": "unavailable"})

    async def run():
        async with httpx.AsyncClient(
            base_url="https://api.example.test", transport=httpx.MockTransport(respond)
        ) as client:
            await discover_evaluation_organizations(
                client, email="demo@example.test", password="synthetic-test-value"
            )

    with pytest.raises(ValueError):
        asyncio.run(run())
    assert calls == ["/api/v1/auth/login"]


def test_viewer_account_cannot_publish_evaluation_reports():
    def respond(request):
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"access_token": "synthetic-test-token"})
        return httpx.Response(
            200, json={"memberships": [{"organization_id": str(uuid.uuid4()), "role": "viewer"}]}
        )

    async def run():
        async with httpx.AsyncClient(
            base_url="https://api.example.test", transport=httpx.MockTransport(respond)
        ) as client:
            await discover_evaluation_organizations(
                client, email="demo@example.test", password="synthetic-test-value"
            )

    with pytest.raises(ValueError, match="owner or administrator"):
        asyncio.run(run())

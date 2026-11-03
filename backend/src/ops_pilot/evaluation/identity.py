"""Discover evaluation workspaces through the same authenticated /auth/me API as the UI."""

import uuid
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel


class EvaluationOrganization(BaseModel):
    organization_id: uuid.UUID
    role: str


class EvaluationAccount(BaseModel):
    memberships: list[EvaluationOrganization]


def evaluation_backend_url(value: str) -> str:
    try:
        url = urlsplit(value.strip())
        valid_scheme = url.scheme == "https" or (
            url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        if (
            not valid_scheme
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/", "/api/v1", "/api/v1/"}
        ):
            raise ValueError
        # Access validates the optional port, too.
        _ = url.port
    except ValueError:
        raise ValueError("Use an HTTPS backend root URL, or HTTP on localhost.") from None
    return urlunsplit((url.scheme, url.netloc, "", "", ""))


async def discover_evaluation_organizations(
    client: httpx.AsyncClient, *, email: str, password: str
) -> list[EvaluationOrganization]:
    """Keep the short-lived login token in memory; never print or persist credentials."""
    try:
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        if login.status_code != 200:
            raise ValueError("Sign-in failed. Check your backend URL and account credentials.")
        try:
            payload = login.json()
        except ValueError:
            raise ValueError("The backend returned an invalid sign-in response.") from None
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError("The backend returned an invalid sign-in response.")
        response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        if response.status_code != 200:
            raise ValueError("Could not read the signed-in account's organization memberships.")
        try:
            account = EvaluationAccount.model_validate(response.json())
        except ValueError:
            raise ValueError("The backend returned invalid organization memberships.") from None
    except httpx.HTTPError:
        raise ValueError(
            "The configured backend could not be reached. No evaluation was started."
        ) from None
    except (TypeError, KeyError):
        raise ValueError("The backend returned an invalid authentication response.") from None
    organizations = [item for item in account.memberships if item.role in {"owner", "admin"}]
    if not organizations:
        raise ValueError("Evaluation reports require an owner or administrator membership.")
    return organizations

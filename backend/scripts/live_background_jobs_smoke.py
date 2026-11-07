import asyncio
import time
import uuid

import httpx

API_BASE_URL = "http://127.0.0.1:8000/api/v1"

EMAIL = f"background-smoke-{uuid.uuid4()}@example.com"
PASSWORD = "StrongPassword123!"
FULL_NAME = "Background Smoke Test"

ORGANIZATION_NAME = f"Background Smoke {uuid.uuid4()}"

ORGANIZATION_SLUG = f"background-smoke-{uuid.uuid4()}"


async def register_user(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        f"{API_BASE_URL}/auth/register",
        json={
            "email": EMAIL,
            "full_name": FULL_NAME,
            "password": PASSWORD,
            "organization_name": (ORGANIZATION_NAME),
            "organization_slug": (ORGANIZATION_SLUG),
        },
    )

    response.raise_for_status()

    print("=== USER REGISTERED ===")


async def login(
    client: httpx.AsyncClient,
) -> str:
    response = await client.post(
        f"{API_BASE_URL}/auth/login",
        json={
            "email": EMAIL,
            "password": PASSWORD,
        },
    )

    response.raise_for_status()

    token = response.json()["access_token"]

    print("=== LOGIN OK ===")

    return str(token)


async def get_organization_id(
    client: httpx.AsyncClient,
    token: str,
) -> str:
    response = await client.get(
        f"{API_BASE_URL}/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    response.raise_for_status()

    body = response.json()

    memberships = body["memberships"]

    if not memberships:
        raise RuntimeError("Registered user has no organization membership")

    organization_id = str(memberships[0]["organization_id"])

    print(
        "Organization:",
        organization_id,
    )

    return organization_id


async def upload_document(
    client: httpx.AsyncClient,
    *,
    token: str,
    organization_id: str,
) -> str:
    content = (
        "IncidentIQ background processing smoke test.\n\n"
        "A customer reported a duplicate payment.\n"
        "Duplicate payments must be investigated "
        "before a refund is issued.\n"
        "This document exists only to verify the "
        "Inngest background document pipeline."
    )

    response = await client.post(
        (f"{API_BASE_URL}/organizations/{organization_id}/documents"),
        headers={
            "Authorization": f"Bearer {token}",
        },
        files={
            "file": (
                "background-smoke.txt",
                content.encode("utf-8"),
                "text/plain",
            )
        },
    )

    response.raise_for_status()

    body = response.json()

    document_id = str(body["id"])

    print("=== DOCUMENT UPLOADED ===")
    print(
        "Document:",
        document_id,
    )
    print(
        "Initial status:",
        body["status"],
    )

    return document_id


async def enqueue_processing(
    client: httpx.AsyncClient,
    *,
    token: str,
    organization_id: str,
    document_id: str,
) -> str:
    response = await client.post(
        (f"{API_BASE_URL}/organizations/{organization_id}/documents/{document_id}/process"),
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    if response.status_code != 202:
        raise RuntimeError(
            f"Expected 202 from background enqueue, got {response.status_code}: {response.text}"
        )

    body = response.json()

    job_id = str(body["id"])

    print("=== BACKGROUND JOB ENQUEUED ===")
    print(
        "Job:",
        job_id,
    )
    print(
        "Status:",
        body["status"],
    )
    print(
        "Progress:",
        body["progress_percent"],
    )

    return job_id


async def wait_for_job(
    client: httpx.AsyncClient,
    *,
    token: str,
    organization_id: str,
    job_id: str,
) -> None:
    deadline = time.monotonic() + 180

    last_status: str | None = None
    last_progress: int | None = None

    while time.monotonic() < deadline:
        response = await client.get(
            (f"{API_BASE_URL}/organizations/{organization_id}/jobs/{job_id}"),
            headers={
                "Authorization": (f"Bearer {token}"),
            },
        )

        response.raise_for_status()

        body = response.json()

        status_value = str(body["status"])
        progress = int(body["progress_percent"])

        if status_value != last_status or progress != last_progress:
            print(
                "Job:",
                status_value,
                f"{progress}%",
            )

            last_status = status_value
            last_progress = progress

        if status_value == "succeeded":
            print("=== BACKGROUND JOB SUCCEEDED ===")
            return

        if status_value == "failed":
            raise RuntimeError(f"Background job failed: {body.get('error_message')}")

        await asyncio.sleep(2)

    raise TimeoutError("Background job did not finish within 180 seconds")


async def main() -> None:
    async with httpx.AsyncClient(
        timeout=30,
    ) as client:
        await register_user(
            client,
        )

        token = await login(
            client,
        )

        organization_id = await get_organization_id(
            client,
            token,
        )

        document_id = await upload_document(
            client,
            token=token,
            organization_id=organization_id,
        )

        job_id = await enqueue_processing(
            client,
            token=token,
            organization_id=organization_id,
            document_id=document_id,
        )

        await wait_for_job(
            client,
            token=token,
            organization_id=organization_id,
            job_id=job_id,
        )

        print()
        print("11G LIVE DOCUMENT BACKGROUND PROCESSING TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())

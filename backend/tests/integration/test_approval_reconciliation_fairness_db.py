"""PostgreSQL proof that quarantined jobs cannot starve newer work.

Uses only the dedicated Neon TEST database.
All fixture rows are rolled back.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

import ops_pilot.services.approval_resume_reconciliation as reconciliation


def dedicated_test_url() -> str:
    if os.environ.get("OPSPILOT_DEDICATED_TEST_DB") != "YES":
        pytest.skip("Explicit dedicated test DB confirmation required")

    env = dotenv_values(".env")
    main = env.get("DATABASE_URL")
    test = env.get("OPSPILOT_TEST_DATABASE_URL")

    if not main or not test:
        pytest.fail("Main and test database URLs must be configured")

    main_identity = make_url(main)
    test_identity = make_url(test)

    def identity(url):
        return (
            url.host,
            url.port or 5432,
            url.database,
            url.username,
        )

    if identity(main_identity) == identity(test_identity):
        pytest.fail("Refusing to connect to the main database")

    if "us-east-2.aws.neon.tech" not in (test_identity.host or ""):
        pytest.fail("Unexpected Neon test database endpoint")

    return test


@pytest.mark.anyio
async def test_newer_recovery_job_is_not_starved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(dedicated_test_url())

    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    approval_ids = [uuid.uuid4() for _ in range(22)]
    job_ids = [uuid.uuid4() for _ in range(22)]

    try:
        async with engine.connect() as connection:
            outer_transaction = await connection.begin()

            try:
                await connection.execute(
                    text("""
                        INSERT INTO organizations (id, name, slug)
                        VALUES (:id, :name, :slug)
                    """),
                    {
                        "id": organization_id,
                        "name": "Reconciliation fairness test",
                        "slug": f"fairness-{uuid.uuid4().hex}",
                    },
                )

                await connection.execute(
                    text("""
                        INSERT INTO users (
                            id, email, full_name, password_hash
                        )
                        VALUES (
                            :id, :email, 'Fairness Test', 'not-a-real-hash'
                        )
                    """),
                    {
                        "id": user_id,
                        "email": f"fairness-{uuid.uuid4().hex}@example.test",
                    },
                )

                await connection.execute(
                    text("""
                        INSERT INTO incidents (
                            id, organization_id, created_by_user_id,
                            title, description, status
                        )
                        VALUES (
                            :id, :org, :user_id,
                            'Fairness test', 'Temporary test incident', 'new'
                        )
                    """),
                    {
                        "id": incident_id,
                        "org": organization_id,
                        "user_id": user_id,
                    },
                )

                now = datetime.now(UTC)

                for index, (approval_id, job_id) in enumerate(
                    zip(approval_ids, job_ids, strict=True)
                ):
                    await connection.execute(
                        text("""
                            INSERT INTO approval_requests (
                                id, organization_id, incident_id,
                                workflow_thread_id, action_type,
                                action_payload, reason, status
                            )
                            VALUES (
                                :id, :org, :incident,
                                :thread, 'refund_transaction',
                                CAST(:payload AS jsonb),
                                'Test only', 'rejected'
                            )
                        """),
                        {
                            "id": approval_id,
                            "org": organization_id,
                            "incident": incident_id,
                            "thread": f"fairness-{uuid.uuid4()}",
                            "payload": "{}",
                        },
                    )

                    await connection.execute(
                        text("""
                            INSERT INTO approval_resume_jobs (
                                id, organization_id, incident_id,
                                approval_request_id, status, attempts,
                                last_error, next_attempt_at
                            )
                            VALUES (
                                :id, :org, :incident, :approval,
                                'failed', 5, 'Test quarantine', :due
                            )
                        """),
                        {
                            "id": job_id,
                            "org": organization_id,
                            "incident": incident_id,
                            "approval": approval_id,
                            "due": now - timedelta(minutes=120 - index),
                        },
                    )

                # Use the same database connection, with
                # savepoints for reconciliation commits.
                session_factory = async_sessionmaker(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )

                monkeypatch.setattr(
                    reconciliation,
                    "async_session_factory",
                    session_factory,
                )

                newest_job = job_ids[-1]

                async def verify(*, job_id: uuid.UUID) -> bool:
                    # Record that the newer job was considered.
                    # Keep every job unresolved to isolate R02 fairness
                    # from R04 completion and checkpoint logic.
                    return False

                verifier = AsyncMock(side_effect=verify)

                monkeypatch.setattr(
                    reconciliation,
                    "verify_quarantined_job",
                    verifier,
                )
                # First sweep: selects the 20 oldest jobs.
                first = await reconciliation.reconcile_quarantined_jobs(
                    limit=20,
                )

                assert first.inspected == 20
                assert first.completed == 0

                first_ids = [call.kwargs["job_id"] for call in verifier.await_args_list]

                # The newest job was not among the first 20.
                assert newest_job not in first_ids

                # Second sweep: the old 20 are cooling down,
                # so the remaining two should be considered.
                second = await reconciliation.reconcile_quarantined_jobs(
                    limit=20,
                )

                assert second.inspected == 2
                assert second.completed == 0

                all_verified_ids = [call.kwargs["job_id"] for call in verifier.await_args_list]

                # All 22 jobs received a verification attempt.
                assert len(all_verified_ids) == 22
                assert len(set(all_verified_ids)) == 22

                # Most importantly, the newer job was reached.
                assert newest_job in all_verified_ids

                # We deliberately return False from verification,
                # so no job must be marked completed.
                status = await connection.scalar(
                    text("""
                        SELECT status
                        FROM approval_resume_jobs
                        WHERE id = :id
                    """),
                    {"id": newest_job},
                )

                assert status == "failed"

            finally:
                await outer_transaction.rollback()

    finally:
        await engine.dispose()

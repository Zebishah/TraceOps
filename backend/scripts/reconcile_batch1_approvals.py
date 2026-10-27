"""Reconcile three known duplicate OpsPilot approvals.

Read-only by default.

Usage:
    uv run python scripts/reconcile_batch1_approvals.py

To apply after backup and preflight:
    uv run python scripts/reconcile_batch1_approvals.py \
        --apply --confirm-reconciliation

Requires schema revision e7c1a19b20f4.
Must run before revision f8c1a19b20f5.

No refund execution, webhooks or workflow resumes occur.
"""

import argparse
import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from ops_pilot.core.config import get_settings


@dataclass(frozen=True)
class ReconciliationGroup:
    organization_id: uuid.UUID
    incident_id: uuid.UUID
    keeper_id: uuid.UUID
    superseded_ids: tuple[uuid.UUID, ...]
    expected_status: str
    transaction_id: str
    amount: Decimal
    currency: str


GROUPS = (
    ReconciliationGroup(
        organization_id=uuid.UUID("d5d2a37c-5538-4783-8f42-a285d8534b7a"),
        incident_id=uuid.UUID("51488561-8410-4ee8-a839-543062b10a55"),
        keeper_id=uuid.UUID("ea6527a1-1f1f-44e3-b61c-06cea66fc807"),
        superseded_ids=(
            uuid.UUID("da349591-32dd-4457-b2c5-82b81e12d947"),
            uuid.UUID("752867b7-6fea-4d42-ba54-a73c8d3fbe6d"),
        ),
        expected_status="pending",
        transaction_id="TXN-MCP-HITL-B-ca264692",
        amount=Decimal("12000.00"),
        currency="PKR",
    ),
    ReconciliationGroup(
        organization_id=uuid.UUID("22ab8cb4-715f-46ba-a406-a2a6c2ef3dc6"),
        incident_id=uuid.UUID("7f960ca7-6545-445d-bc92-958d1c29012e"),
        keeper_id=uuid.UUID("23db9f03-094f-4250-b5ff-20a8fab6b48a"),
        superseded_ids=(uuid.UUID("5e3d854a-4129-4c2f-99ee-19da01b36124"),),
        expected_status="approved",
        transaction_id=("CHARGE-9bfc0cc5d5f84314ad31e134f5fe3272"),
        amount=Decimal("100.00"),
        currency="USD",
    ),
)


def fail(message: str) -> None:
    raise RuntimeError(f"Approval reconciliation blocked: {message}")


async def validate_group(
    conn: AsyncConnection,
    group: ReconciliationGroup,
) -> None:
    params = {
        "organization_id": group.organization_id,
        "incident_id": group.incident_id,
        "transaction_id": group.transaction_id,
    }

    incident = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, status
                FROM incidents
                WHERE id = :incident_id
                  AND organization_id = :organization_id
                FOR UPDATE
                """
                ),
                params,
            )
        )
        .mappings()
        .one_or_none()
    )

    if incident is None:
        fail(f"incident missing: {group.incident_id}")

    if incident["status"] != "awaiting_approval":
        fail(f"incident state changed: {group.incident_id}")

    approvals = (
        (
            await conn.execute(
                text(
                    """
                SELECT
                    id,
                    status,
                    action_type,
                    action_payload,
                    workflow_thread_id,
                    decided_by_user_id,
                    decided_at,
                    executed_at,
                    superseded_by_approval_id,
                    superseded_at,
                    supersession_reason
                FROM approval_requests
                WHERE organization_id = :organization_id
                  AND incident_id = :incident_id
                ORDER BY id
                FOR UPDATE
                """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )

    expected = {
        group.keeper_id,
        *group.superseded_ids,
    }

    actual = {row["id"] for row in approvals}

    # Refuse even if an additional rejected or executed
    # approval appears. This is a precise one-time cleanup.
    if actual != expected:
        fail(
            f"approval set changed for {group.incident_id}: "
            f"expected {len(expected)}, found {len(actual)}"
        )

    if len(approvals) != len(expected):
        fail("approval count mismatch")

    # Every record must still refer to the same exact
    # previously inspected financial action.
    keeper = next(
        (row for row in approvals if row["id"] == group.keeper_id),
        None,
    )

    if keeper is None:
        fail("keeper approval missing")

    for row in approvals:
        payload = row["action_payload"]

        if (
            row["status"] != group.expected_status
            or row["action_type"] != "refund_transaction"
            or not isinstance(payload, dict)
            or payload.get("external_transaction_id") != group.transaction_id
            or payload.get("currency") != group.currency
            or row["executed_at"] is not None
            or row["superseded_by_approval_id"] is not None
            or row["superseded_at"] is not None
            or row["supersession_reason"] is not None
        ):
            fail(f"approval state changed: {row['id']}")

        try:
            amount = Decimal(str(payload.get("amount")))
        except (ValueError, ArithmeticError, TypeError):
            fail(f"invalid approval amount: {row['id']}")

        if not amount.is_finite() or amount != group.amount:
            fail(f"approval amount mismatch: {row['id']}")

        if group.expected_status == "pending":
            if row["decided_by_user_id"] is not None or row["decided_at"] is not None:
                fail(f"pending approval was decided: {row['id']}")
        else:
            if row["decided_by_user_id"] is None or row["decided_at"] is None:
                fail(f"approved record lacks decision: {row['id']}")

    if group.expected_status == "approved":
        # These two records were inspected with the same
        # reviewer and the same decision timestamp.
        for row in approvals:
            if row["decided_by_user_id"] != keeper["decided_by_user_id"]:
                fail("approved duplicates have different reviewers")
            if row["decided_at"] != keeper["decided_at"]:
                fail("approved duplicates have different decision times")

    # A keeper must have a usable thread identity, and
    # every obsolete record must be a different workflow.
    threads = [row["workflow_thread_id"] for row in approvals]

    if any(not thread for thread in threads):
        fail("missing workflow thread identity")

    if len(threads) != len(set(threads)):
        fail("duplicate workflow thread identities")

    # Never supersede anything linked to durable recovery.
    jobs = (
        await conn.execute(
            text(
                """
                SELECT count(*)
                FROM approval_resume_jobs
                WHERE incident_id = :incident_id
                  AND organization_id = :organization_id
                """
            ),
            params,
        )
    ).scalar_one()

    if jobs:
        fail(f"resume jobs exist for {group.incident_id}")

    source = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, amount, currency,
                       transaction_type, status
                FROM operational_payment_transactions
                WHERE organization_id = :organization_id
                  AND external_transaction_id = :transaction_id
                FOR UPDATE
                """
                ),
                params,
            )
        )
        .mappings()
        .one_or_none()
    )

    if source is None:
        fail(f"source charge missing: {group.transaction_id}")

    if (
        source["transaction_type"] != "charge"
        or source["status"] != "succeeded"
        or source["amount"] != group.amount
        or source["currency"] != group.currency
    ):
        fail(f"source charge changed: {group.transaction_id}")

    refunds = (
        await conn.execute(
            text(
                """
                SELECT count(*)
                FROM operational_payment_transactions
                WHERE source_transaction_id = :source_id
                """
            ),
            {"source_id": source["id"]},
        )
    ).scalar_one()

    if refunds:
        fail(f"refund already exists for {group.transaction_id}")

    print(
        f"VALID: incident={group.incident_id}, "
        f"keeper={group.keeper_id}, "
        f"supersede={len(group.superseded_ids)}"
    )


async def apply_group(
    conn: AsyncConnection,
    group: ReconciliationGroup,
) -> None:
    for approval_id in group.superseded_ids:
        reason = (
            "Administrative reconciliation of duplicate "
            "approval requests for the same verified "
            "financial action. Original reviewer decision "
            "and timestamps preserved. No refund executed."
        )

        result = await conn.execute(
            text(
                """
                UPDATE approval_requests
                SET status = 'superseded',
                    superseded_by_approval_id = :keeper_id,
                    superseded_at = :now,
                    supersession_reason = :reason,
                    updated_at = :now
                WHERE id = :approval_id
                  AND incident_id = :incident_id
                  AND organization_id = :organization_id
                  AND status = :expected_status
                  AND executed_at IS NULL
                """
            ),
            {
                "keeper_id": group.keeper_id,
                "approval_id": approval_id,
                "incident_id": group.incident_id,
                "organization_id": group.organization_id,
                "expected_status": group.expected_status,
                "reason": reason,
                "now": datetime.now(UTC),
            },
        )

        if result.rowcount != 1:
            fail(f"supersession failed for {approval_id}")


async def run(*, apply: bool) -> None:
    settings = get_settings()

    engine = create_async_engine(str(settings.database_url))

    try:
        async with engine.connect() as conn:
            async with conn.begin():
                # This lock serializes concurrent runs of
                # this reconciliation script.
                await conn.execute(
                    text(
                        """
                        SELECT pg_advisory_xact_lock(
                            hashtext('opspilot-batch1-reconciliation')
                        )
                        """
                    )
                )

                revision = (
                    await conn.execute(
                        text(
                            """
                            SELECT version_num
                            FROM alembic_version
                            """
                        )
                    )
                ).scalar_one()

                if revision != "e7c1a19b20f4":
                    fail(f"Expected schema revision e7c1a19b20f4, got {revision}")

                # Check both groups before modifying either.
                for group in GROUPS:
                    await validate_group(conn, group)

                if not apply:
                    print("DRY RUN PASSED: no approval records changed.")
                    return

                for group in GROUPS:
                    await apply_group(conn, group)

                conflicts = (
                    await conn.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM (
                                SELECT incident_id
                                FROM approval_requests
                                WHERE status IN ('pending', 'approved')
                                GROUP BY incident_id
                                HAVING count(*) > 1
                            ) AS conflicts
                            """
                        )
                    )
                ).scalar_one()

                if conflicts:
                    fail(f"{conflicts} active approval conflicts remain")

                print("RECONCILIATION VALIDATED: three duplicate approvals superseded.")

        print("Transaction completed. No refunds or webhooks were executed.")

    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and reconcile known Batch 1 approvals")

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply guarded approval supersession",
    )

    parser.add_argument(
        "--confirm-reconciliation",
        action="store_true",
        help="Explicitly authorize this one-time data change",
    )

    args = parser.parse_args()

    if args.apply and not args.confirm_reconciliation:
        parser.error("--apply requires --confirm-reconciliation")

    asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    main()

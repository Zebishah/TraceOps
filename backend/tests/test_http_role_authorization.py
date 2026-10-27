"""HTTP organization authorization policy regression tests."""

import inspect
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from ops_pilot.api.dependencies import (
    APPROVAL_DECISION_ROLES,
    DOCUMENT_WRITE_ROLES,
    INCIDENT_CREATE_ROLES,
    INCIDENT_INVESTIGATION_ROLES,
    ApprovalReviewerMembership,
    CurrentMembership,
    DocumentWriterMembership,
    IncidentCreatorMembership,
    IncidentInvestigatorMembership,
    enforce_membership_role,
)
from ops_pilot.api.routes.documents import router as documents_router
from ops_pilot.api.routes.incidents import router as incidents_router
from ops_pilot.models.membership import MembershipRole


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        (MembershipRole.OWNER, True),
        (MembershipRole.ADMIN, True),
        (MembershipRole.OPERATOR, True),
        (MembershipRole.REVIEWER, False),
        (MembershipRole.VIEWER, False),
    ],
)
def test_incident_creation_policy(
    role: MembershipRole,
    allowed: bool,
) -> None:
    membership = SimpleNamespace(
        id=uuid.uuid4(),
        role=role,
    )

    if allowed:
        assert (
            enforce_membership_role(
                membership,  # type: ignore[arg-type]
                INCIDENT_CREATE_ROLES,
            )
            is membership
        )
    else:
        with pytest.raises(HTTPException) as exc:
            enforce_membership_role(
                membership,  # type: ignore[arg-type]
                INCIDENT_CREATE_ROLES,
            )
        assert exc.value.status_code == 403


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        (MembershipRole.OWNER, True),
        (MembershipRole.ADMIN, True),
        (MembershipRole.OPERATOR, True),
        (MembershipRole.REVIEWER, True),
        (MembershipRole.VIEWER, False),
    ],
)
def test_investigation_policy(
    role: MembershipRole,
    allowed: bool,
) -> None:
    membership = SimpleNamespace(role=role)

    if allowed:
        assert (
            enforce_membership_role(
                membership,  # type: ignore[arg-type]
                INCIDENT_INVESTIGATION_ROLES,
            )
            is membership
        )
    else:
        with pytest.raises(HTTPException) as exc:
            enforce_membership_role(
                membership,  # type: ignore[arg-type]
                INCIDENT_INVESTIGATION_ROLES,
            )
        assert exc.value.status_code == 403


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        (MembershipRole.OWNER, True),
        (MembershipRole.ADMIN, True),
        (MembershipRole.OPERATOR, True),
        (MembershipRole.REVIEWER, False),
        (MembershipRole.VIEWER, False),
    ],
)
def test_document_write_policy(
    role: MembershipRole,
    allowed: bool,
) -> None:
    membership = SimpleNamespace(role=role)

    if allowed:
        assert (
            enforce_membership_role(
                membership,  # type: ignore[arg-type]
                DOCUMENT_WRITE_ROLES,
            )
            is membership
        )
    else:
        with pytest.raises(HTTPException) as exc:
            enforce_membership_role(
                membership,  # type: ignore[arg-type]
                DOCUMENT_WRITE_ROLES,
            )
        assert exc.value.status_code == 403


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        (MembershipRole.OWNER, True),
        (MembershipRole.ADMIN, True),
        (MembershipRole.OPERATOR, False),
        (MembershipRole.REVIEWER, True),
        (MembershipRole.VIEWER, False),
    ],
)
def test_approval_decision_policy(
    role: MembershipRole,
    allowed: bool,
) -> None:
    membership = SimpleNamespace(role=role)

    if allowed:
        assert (
            enforce_membership_role(
                membership,  # type: ignore[arg-type]
                APPROVAL_DECISION_ROLES,
            )
            is membership
        )
    else:
        with pytest.raises(HTTPException) as exc:
            enforce_membership_role(
                membership,  # type: ignore[arg-type]
                APPROVAL_DECISION_ROLES,
            )
        assert exc.value.status_code == 403


@pytest.mark.parametrize(
    ("router", "path", "method", "expected_dependency"),
    [
        (
            incidents_router,
            "/organizations/{organization_id}/incidents",
            "POST",
            IncidentCreatorMembership,
        ),
        (
            incidents_router,
            "/organizations/{organization_id}/incidents/{incident_id}/classify",
            "POST",
            IncidentInvestigatorMembership,
        ),
        (
            incidents_router,
            "/organizations/{organization_id}/incidents/{incident_id}/retrieve-evidence",
            "POST",
            IncidentInvestigatorMembership,
        ),
        (
            incidents_router,
            "/organizations/{organization_id}/incidents/{incident_id}/investigate",
            "POST",
            IncidentInvestigatorMembership,
        ),
        (
            incidents_router,
            "/organizations/{organization_id}/incidents/{incident_id}/approvals/{approval_request_id}/decision",
            "POST",
            ApprovalReviewerMembership,
        ),
        (
            incidents_router,
            "/organizations/{organization_id}/incidents/{incident_id}/resolve-no-action",
            "POST",
            ApprovalReviewerMembership,
        ),
        (
            documents_router,
            "/organizations/{organization_id}/documents",
            "POST",
            DocumentWriterMembership,
        ),
        (
            documents_router,
            "/organizations/{organization_id}/documents/{document_id}/process",
            "POST",
            DocumentWriterMembership,
        ),
        (
            documents_router,
            "/organizations/{organization_id}/documents/{document_id}/index",
            "POST",
            DocumentWriterMembership,
        ),
        (
            documents_router,
            "/organizations/{organization_id}/documents/{document_id}/chunks",
            "GET",
            CurrentMembership,
        ),
    ],
)
def test_route_declares_required_membership_dependency(
    router: object,
    path: str,
    method: str,
    expected_dependency: object,
) -> None:
    routes = router.routes

    matches = [
        route
        for route in routes
        if isinstance(route, APIRoute) and route.path == path and method in route.methods
    ]

    assert len(matches) == 1

    endpoint = matches[0].endpoint
    annotation = inspect.get_annotations(
        endpoint,
        eval_str=True,
    )["membership"]

    assert annotation == expected_dependency


def test_all_role_sets_exclude_viewer() -> None:
    for roles in (
        INCIDENT_CREATE_ROLES,
        INCIDENT_INVESTIGATION_ROLES,
        DOCUMENT_WRITE_ROLES,
        APPROVAL_DECISION_ROLES,
    ):
        assert MembershipRole.VIEWER not in roles


def test_no_read_only_dependency_is_used_for_incident_mutations() -> None:
    for route in incidents_router.routes:
        if not isinstance(route, APIRoute):
            continue

        if "POST" not in route.methods:
            continue

        annotation = inspect.get_annotations(
            route.endpoint,
            eval_str=True,
        )["membership"]

        assert annotation != CurrentMembership


def test_no_read_only_dependency_is_used_for_document_mutations() -> None:
    for route in documents_router.routes:
        if not isinstance(route, APIRoute):
            continue

        if "POST" not in route.methods:
            continue

        annotation = inspect.get_annotations(
            route.endpoint,
            eval_str=True,
        )["membership"]

        assert annotation != CurrentMembership

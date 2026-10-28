import uuid
from types import SimpleNamespace

import pytest

from ops_pilot.services.retrieval import (
    parse_retrieval_candidate,
)


def make_point(
    organization_id: uuid.UUID,
    **overrides: object,
) -> SimpleNamespace:
    payload: dict[str, object] = {
        "organization_id": str(organization_id),
        "document_id": str(uuid.uuid4()),
        "chunk_index": 0,
        "page_number": 1,
        "text": "Approved payment policy",
        "source_filename": "policy.pdf",
    }
    payload.update(overrides)

    return SimpleNamespace(
        id=str(uuid.uuid4()),
        score=0.85,
        payload=payload,
    )


def test_valid_point_is_accepted() -> None:
    organization_id = uuid.uuid4()
    point = make_point(organization_id)

    candidate = parse_retrieval_candidate(
        point=point,
        organization_id=organization_id,
    )

    assert candidate is not None
    assert candidate.text == "Approved payment policy"
    assert candidate.vector_score == 0.85


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_id", "not-a-uuid"),
        ("chunk_index", "zero"),
        ("chunk_index", -1),
        ("page_number", 0),
        ("page_number", True),
        ("text", ""),
        ("text", None),
        ("source_filename", None),
    ],
)
def test_malformed_payload_is_skipped(
    field: str,
    value: object,
) -> None:
    organization_id = uuid.uuid4()
    point = make_point(
        organization_id,
        **{field: value},
    )

    assert (
        parse_retrieval_candidate(
            point=point,
            organization_id=organization_id,
        )
        is None
    )


def test_cross_tenant_payload_is_rejected() -> None:
    requesting_org = uuid.uuid4()
    other_org = uuid.uuid4()

    point = make_point(other_org)

    assert (
        parse_retrieval_candidate(
            point=point,
            organization_id=requesting_org,
        )
        is None
    )


@pytest.mark.parametrize(
    "score",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_nonfinite_scores_are_skipped(score: float) -> None:
    organization_id = uuid.uuid4()
    point = make_point(organization_id)
    point.score = score

    assert (
        parse_retrieval_candidate(
            point=point,
            organization_id=organization_id,
        )
        is None
    )


def test_missing_payload_is_skipped() -> None:
    organization_id = uuid.uuid4()

    point = SimpleNamespace(
        id=str(uuid.uuid4()),
        score=0.5,
        payload=None,
    )

    assert (
        parse_retrieval_candidate(
            point=point,
            organization_id=organization_id,
        )
        is None
    )

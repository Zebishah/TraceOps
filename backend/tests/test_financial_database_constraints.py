"""Financial relationship and database constraint regression tests."""

from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from ops_pilot.models.order import OperationalOrder
from ops_pilot.models.payment_transaction import PaymentTransaction


def test_customer_order_relationship_prevents_cascade_delete() -> None:
    """Both customer foreign keys must prevent cascade deletion."""

    customer_constraints = [
        constraint
        for constraint in OperationalOrder.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and any(element.target_fullname == "customers.id" for element in constraint.elements)
    ]

    # Original ID foreign key + new organization-aware foreign key.
    assert len(customer_constraints) == 2

    assert all(constraint.ondelete == "RESTRICT" for constraint in customer_constraints)

    # The composite constraint must also enforce tenant consistency.
    composite_constraints = [
        constraint
        for constraint in customer_constraints
        if constraint.name == "fk_operational_orders_customer_tenant"
    ]

    assert len(composite_constraints) == 1

    composite = composite_constraints[0]

    assert {column.name for column in composite.columns} == {
        "customer_id",
        "organization_id",
    }


def test_order_payment_relationship_prevents_cascade_delete() -> None:
    """Both order foreign keys must prevent cascade deletion."""

    order_constraints = [
        constraint
        for constraint in PaymentTransaction.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and any(
            element.target_fullname == "operational_orders.id" for element in constraint.elements
        )
    ]

    # Original ID foreign key + new organization-aware foreign key.
    assert len(order_constraints) == 2

    assert all(constraint.ondelete == "RESTRICT" for constraint in order_constraints)

    composite_constraints = [
        constraint
        for constraint in order_constraints
        if constraint.name == "fk_payment_transactions_order_tenant"
    ]

    assert len(composite_constraints) == 1

    composite = composite_constraints[0]

    assert {column.name for column in composite.columns} == {
        "order_id",
        "organization_id",
    }


def test_payment_amount_has_positive_check_constraint() -> None:
    """Payment and refund amounts must always be positive."""

    checks = [
        constraint
        for constraint in PaymentTransaction.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    ]

    assert any(
        constraint.name == "ck_payment_transactions_amount_positive"
        and "amount > 0" in str(constraint.sqltext)
        for constraint in checks
    )

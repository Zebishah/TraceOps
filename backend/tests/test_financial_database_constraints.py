from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from ops_pilot.models.order import OperationalOrder
from ops_pilot.models.payment_transaction import PaymentTransaction


def test_customer_order_relationship_prevents_cascade_delete() -> None:
    constraints = [
        constraint
        for constraint in OperationalOrder.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]

    customer_constraints = [
        constraint
        for constraint in constraints
        if any(element.target_fullname == "customers.id" for element in constraint.elements)
    ]

    assert len(customer_constraints) == 1
    assert customer_constraints[0].ondelete == "RESTRICT"


def test_order_payment_relationship_prevents_cascade_delete() -> None:
    constraints = [
        constraint
        for constraint in PaymentTransaction.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]

    order_constraints = [
        constraint
        for constraint in constraints
        if any(
            element.target_fullname == "operational_orders.id" for element in constraint.elements
        )
    ]

    assert len(order_constraints) == 1
    assert order_constraints[0].ondelete == "RESTRICT"


def test_payment_amount_has_positive_check_constraint() -> None:
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

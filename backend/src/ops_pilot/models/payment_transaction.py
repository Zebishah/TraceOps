import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ops_pilot.db.base import Base


class PaymentTransactionStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentTransactionType(StrEnum):
    CHARGE = "charge"
    REFUND = "refund"


class PaymentTransaction(Base):
    __tablename__ = "operational_payment_transactions"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "external_transaction_id",
            name="uq_payment_transactions_organization_external_transaction",
        ),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'refunded')",
            name="ck_payment_transactions_status",
        ),
        CheckConstraint(
            "transaction_type IN ('charge', 'refund')",
            name="ck_payment_transactions_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "operational_orders.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    external_transaction_id: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    transaction_type: Mapped[PaymentTransactionType] = mapped_column(
        Enum(
            PaymentTransactionType,
            name="payment_transaction_type",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [transaction_type.value for transaction_type in enum],
        ),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    status: Mapped[PaymentTransactionStatus] = mapped_column(
        Enum(
            PaymentTransactionStatus,
            name="payment_transaction_status",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [status.value for status in enum],
        ),
        nullable=False,
    )

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

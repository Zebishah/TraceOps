from enum import StrEnum

from pydantic import BaseModel, Field

from ops_pilot.models.incident import IncidentPriority


class IncidentCategory(StrEnum):
    PAYMENT = "payment"
    ACCOUNT = "account"
    ACCESS = "access"
    DATA = "data"
    INTEGRATION = "integration"
    SYSTEM = "system"
    SECURITY = "security"
    OTHER = "other"


class IncidentClassification(BaseModel):
    category: IncidentCategory = Field(
        description="The main operational category of the incident.",
    )

    priority: IncidentPriority = Field(
        description="The operational urgency of the incident.",
    )

    confidence: float | None = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Provider-reported confidence from 0 to 1; null when unavailable or uncalibrated."
        ),
    )

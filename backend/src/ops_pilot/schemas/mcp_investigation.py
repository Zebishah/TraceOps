from pydantic import BaseModel

from ops_pilot.schemas.incidents import (
    IncidentInvestigationResponse,
)


class MCPIncidentInvestigationResponse(BaseModel):
    investigation: IncidentInvestigationResponse

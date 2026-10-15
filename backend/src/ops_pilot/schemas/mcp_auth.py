import uuid

from pydantic import BaseModel

from ops_pilot.models.membership import MembershipRole


class MCPAuthenticatedContext(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: MembershipRole


class MCPOrganizationSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: MembershipRole


class MCPOrganizationsResponse(BaseModel):
    organizations: list[MCPOrganizationSummary]

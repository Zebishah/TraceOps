import uuid

from pydantic import BaseModel, EmailStr, Field

from ops_pilot.models.membership import MembershipRole


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=128)
    organization_name: str = Field(min_length=1, max_length=200)
    organization_slug: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    email_verified: bool = False
    verification_required: bool = False
    verification_email_sent: bool = False


class MembershipResponse(BaseModel):
    organization_id: uuid.UUID
    role: MembershipRole


class MeResponse(BaseModel):
    user: UserResponse
    memberships: list[MembershipResponse]


class VerificationEmailRequest(BaseModel):
    email: EmailStr = Field(max_length=320)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]{43}$")


class VerificationMessage(BaseModel):
    message: str


class EmailVerifiedResponse(BaseModel):
    verified: bool = True
    message: str = "Email verified. You can now sign in."

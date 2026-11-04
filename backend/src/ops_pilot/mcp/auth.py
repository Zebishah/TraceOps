import uuid

import jwt
from mcp.server.auth.provider import (
    AccessToken,
)

from ops_pilot.core.config import get_settings
from ops_pilot.core.security import (
    decode_mcp_access_token,
)
from ops_pilot.db.session import async_session_factory
from ops_pilot.services.email_verification import mcp_subject_allowed
from ops_pilot.services.mcp_token_revocation import (
    is_mcp_access_token_revoked,
)


class OpsPilotMCPTokenVerifier:
    async def verify_token(
        self,
        token: str,
    ) -> AccessToken | None:
        try:
            payload = decode_mcp_access_token(
                token,
            )
            jti = payload.get(
                "jti",
            )

            if not isinstance(
                jti,
                str,
            ):
                return None
            subject = payload.get("sub")
            client_id = payload.get(
                "client_id",
            )

            if not isinstance(
                client_id,
                str,
            ):
                return None
            if subject is None:
                return None

            user_id = uuid.UUID(
                str(subject),
            )

            scope_value = payload.get(
                "scope",
                "",
            )

            if not isinstance(
                scope_value,
                str,
            ):
                return None

            scopes = scope_value.split()

            settings = get_settings()

            if settings.mcp_required_scope not in scopes:
                return None

            expires_at = payload.get("exp")
            jti = payload.get("jti")
            if not isinstance(
                expires_at,
                int,
            ):
                return None

            if not isinstance(
                jti,
                str,
            ):
                return None
            if await is_mcp_access_token_revoked(
                jti=jti,
            ):
                return None

            if settings.email_verification_enabled:
                async with async_session_factory() as session:
                    if not await mcp_subject_allowed(session, user_id):
                        return None

            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=scopes,
                expires_at=expires_at,
                resource=str(settings.mcp_resource_url),
                subject=str(user_id),
                claims={
                    "iss": str(
                        settings.mcp_authorization_server_url,
                    ),
                    "jti": jti,
                },
            )

        except (
            jwt.PyJWTError,
            ValueError,
        ):
            return None

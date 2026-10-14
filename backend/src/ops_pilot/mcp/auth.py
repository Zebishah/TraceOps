import uuid

import jwt
from mcp.server.auth.provider import (
    AccessToken,
)

from ops_pilot.core.config import get_settings
from ops_pilot.core.security import (
    decode_mcp_access_token,
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

            if not isinstance(
                expires_at,
                int,
            ):
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
                },
            )

        except (
            jwt.PyJWTError,
            ValueError,
        ):
            return None

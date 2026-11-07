import json
import uuid
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthToken,
)
from pydantic import AnyUrl

from ops_pilot.core.config import get_settings
from ops_pilot.core.mcp_scopes import (
    READ_SCOPE,
    validate_mcp_scope_grant,
)
from ops_pilot.core.security import (
    create_mcp_access_token,
    decode_mcp_access_token,
)
from ops_pilot.db.session import async_session_factory
from ops_pilot.models.oauth_client import OAuthClient
from ops_pilot.services.email_verification import mcp_subject_allowed
from ops_pilot.services.mcp_token_revocation import (
    is_mcp_access_token_revoked,
    revoke_mcp_access_token,
)
from ops_pilot.services.oauth import (
    consume_authorization_code,
    create_refresh_token,
    get_oauth_client,
    load_authorization_code,
    load_refresh_token,
    oauth_client_redirect_uris,
    revoke_refresh_token,
)


class OpsPilotOAuthProvider(
    OAuthAuthorizationServerProvider[
        AuthorizationCode,
        RefreshToken,
        AccessToken,
    ]
):
    async def get_client(
        self,
        client_id: str,
    ) -> OAuthClientInformationFull | None:
        async with async_session_factory() as session:
            client = await get_oauth_client(
                session=session,
                client_id=client_id,
            )

            if client is None:
                return None

            return OAuthClientInformationFull(
                client_id=client.client_id,
                client_name=client.client_name,
                redirect_uris=[AnyUrl(uri) for uri in oauth_client_redirect_uris(client)],
                grant_types=json.loads(client.grant_types_json),
                response_types=json.loads(client.response_types_json),
                token_endpoint_auth_method=(client.token_endpoint_auth_method),
                scope=client.scope,
            )

    async def register_client(
        self,
        client_info: OAuthClientInformationFull,
    ) -> None:
        if client_info.client_secret is not None:
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description=(
                    "IncidentIQ currently supports public OAuth clients "
                    "with token_endpoint_auth_method=none."
                ),
            )

        if client_info.token_endpoint_auth_method not in {
            None,
            "none",
        }:
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description=("token_endpoint_auth_method must be 'none'."),
            )

        if not client_info.redirect_uris:
            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description=("At least one redirect URI is required."),
            )

        settings = get_settings()

        requested_scope = client_info.scope or settings.mcp_required_scope

        try:
            validated_scopes = validate_mcp_scope_grant(
                requested=requested_scope,
                registered=requested_scope,
            )
        except ValueError as exc:
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description=str(exc),
            ) from exc

        # Preserve canonical scopes in the registration.
        requested_scope = " ".join(validated_scopes)

        async with async_session_factory() as session:
            existing = await get_oauth_client(
                session=session,
                client_id=client_info.client_id,
            )

            if existing is not None:
                return

            client = OAuthClient(
                client_id=client_info.client_id,
                client_secret_hash=None,
                client_name=client_info.client_name,
                redirect_uris_json=json.dumps([str(uri) for uri in client_info.redirect_uris]),
                grant_types_json=json.dumps(client_info.grant_types),
                response_types_json=json.dumps(client_info.response_types),
                token_endpoint_auth_method="none",
                scope=requested_scope,
            )

            session.add(client)
            await session.commit()

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        settings = get_settings()

        if params.resource != str(settings.mcp_resource_url):
            from mcp.server.auth.provider import AuthorizeError

            raise AuthorizeError(
                error="invalid_target",
                error_description=("Invalid MCP resource."),
            )

        if client.client_id is None:
            from mcp.server.auth.provider import AuthorizeError

            raise AuthorizeError(
                error="invalid_request",
                error_description=("OAuth client ID is required."),
            )

        requested_scopes = params.scopes or [READ_SCOPE]

        try:
            validated_scopes = validate_mcp_scope_grant(
                requested=" ".join(requested_scopes),
                registered=client.scope or READ_SCOPE,
            )
        except ValueError as exc:
            from mcp.server.auth.provider import AuthorizeError

            raise AuthorizeError(
                error="invalid_scope",
                error_description=str(exc),
            ) from exc

        query = urlencode(
            {
                "client_id": client.client_id,
                "redirect_uri": str(params.redirect_uri),
                "state": params.state or "",
                "scope": " ".join(validated_scopes),
                "code_challenge": (params.code_challenge),
                "resource": (params.resource or str(settings.mcp_resource_url)),
                "redirect_uri_explicit": (
                    "true" if params.redirect_uri_provided_explicitly else "false"
                ),
            }
        )

        return f"{str(settings.mcp_authorization_server_url).rstrip('/')}/oauth/login?{query}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        async with async_session_factory() as session:
            code = await load_authorization_code(
                session=session,
                raw_code=authorization_code,
                client_id=client.client_id,
            )

            if code is None:
                return None

            return AuthorizationCode(
                code=authorization_code,
                scopes=code.scopes.split(),
                expires_at=code.expires_at.timestamp(),
                client_id=code.client_id,
                code_challenge=code.code_challenge,
                redirect_uri=AnyUrl(code.redirect_uri),
                redirect_uri_provided_explicitly=(code.redirect_uri_provided_explicitly),
                resource=code.resource,
                subject=str(code.user_id),
            )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        settings = get_settings()

        if not client.client_id:
            raise TokenError(
                error="invalid_client",
                error_description="OAuth client ID is required.",
            )

        async with async_session_factory() as session:
            try:
                stored_code = await load_authorization_code(
                    session=session,
                    raw_code=authorization_code.code,
                    client_id=client.client_id,
                )

                if stored_code is None:
                    raise TokenError(
                        error="invalid_grant",
                        error_description="Authorization code is invalid.",
                    )

                # The server-side record is authoritative.
                # Never trust subject/scopes supplied in the
                # AuthorizationCode object passed by the caller.
                user_id = stored_code.user_id
                trusted_scopes = stored_code.scopes.split()
                if not await mcp_subject_allowed(session, user_id):
                    raise TokenError(
                        error="invalid_grant", error_description="Account verification required."
                    )

                claimed = await consume_authorization_code(
                    session=session,
                    code=stored_code,
                )

                if not claimed:
                    raise TokenError(
                        error="invalid_grant",
                        error_description="Authorization code was already used.",
                    )

                refresh_token = await create_refresh_token(
                    session=session,
                    client_id=client.client_id,
                    user_id=user_id,
                    scopes=trusted_scopes,
                    resource=stored_code.resource,
                    commit=False,
                )

                await session.commit()

            except Exception:
                await session.rollback()
                raise

        access_token = create_mcp_access_token(
            subject=str(user_id),
            client_id=client.client_id,
            scopes=trusted_scopes,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=settings.mcp_access_token_expire_minutes * 60,
            scope=" ".join(trusted_scopes),
            refresh_token=refresh_token,
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        async with async_session_factory() as session:
            stored = await load_refresh_token(
                session=session,
                raw_token=refresh_token,
                client_id=client.client_id,
            )

            if stored is None:
                return None

            return RefreshToken(
                token=refresh_token,
                client_id=stored.client_id,
                scopes=stored.scopes.split(),
                expires_at=int(stored.expires_at.timestamp()),
                resource=stored.resource,
                subject=str(stored.user_id),
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        settings = get_settings()

        if not client.client_id:
            raise TokenError(
                error="invalid_client",
                error_description="OAuth client ID is required.",
            )

        async with async_session_factory() as session:
            try:
                stored = await load_refresh_token(
                    session=session,
                    raw_token=refresh_token.token,
                    client_id=client.client_id,
                )

                if stored is None:
                    raise TokenError(
                        error="invalid_grant",
                        error_description="Refresh token is invalid.",
                    )

                # Grant persisted by the authorization server.
                granted_scopes = set(stored.scopes.split())

                # An empty request preserves the original grant.
                requested_scopes = list(dict.fromkeys(scopes)) if scopes else stored.scopes.split()

                if not requested_scopes or not set(requested_scopes).issubset(granted_scopes):
                    raise TokenError(
                        error="invalid_scope",
                        error_description=("Requested scopes exceed the original grant."),
                    )

                # Never trust a caller-supplied token object's
                # subject, resource or scopes.
                trusted_user_id = stored.user_id
                trusted_resource = stored.resource
                if not await mcp_subject_allowed(session, trusted_user_id):
                    raise TokenError(
                        error="invalid_grant", error_description="Account verification required."
                    )

                revoked = await revoke_refresh_token(
                    session=session,
                    token=stored,
                    commit=False,
                )

                if not revoked:
                    raise TokenError(
                        error="invalid_grant",
                        error_description="Refresh token already used.",
                    )

                new_refresh_token = await create_refresh_token(
                    session=session,
                    client_id=client.client_id,
                    user_id=trusted_user_id,
                    scopes=requested_scopes,
                    resource=trusted_resource,
                    commit=False,
                )

                await session.commit()

            except Exception:
                await session.rollback()
                raise

        access_token = create_mcp_access_token(
            subject=str(trusted_user_id),
            client_id=client.client_id,
            scopes=requested_scopes,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=settings.mcp_access_token_expire_minutes * 60,
            scope=" ".join(requested_scopes),
            refresh_token=new_refresh_token,
        )

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        if isinstance(
            token,
            RefreshToken,
        ):
            async with async_session_factory() as session:
                stored = await load_refresh_token(
                    session=session,
                    raw_token=token.token,
                    client_id=token.client_id,
                )

                if stored is not None:
                    await revoke_refresh_token(
                        session=session,
                        token=stored,
                    )

                    return

        if isinstance(
            token,
            AccessToken,
        ):
            claims = token.claims

            if claims is None:
                return

            jti = claims.get(
                "jti",
            )

            if not isinstance(
                jti,
                str,
            ):
                return
            if await is_mcp_access_token_revoked(
                jti=jti,
            ):
                return None
            if token.expires_at is None:
                return

            await revoke_mcp_access_token(
                jti=jti,
                expires_at=int(token.expires_at),
            )

    async def load_access_token(
        self,
        token: str,
    ) -> AccessToken | None:
        try:
            payload = decode_mcp_access_token(token)
        except Exception:
            return None

        subject = payload.get("sub")
        client_id = payload.get("client_id")
        scope_value = payload.get(
            "scope",
            "",
        )
        expires_at = payload.get("exp")
        jti = payload.get("jti")
        if not isinstance(
            subject,
            str,
        ):
            return None

        if not isinstance(
            client_id,
            str,
        ):
            return None

        if not isinstance(
            scope_value,
            str,
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
        if not isinstance(
            expires_at,
            int,
        ):
            return None

        if get_settings().email_verification_enabled:
            try:
                user_id = uuid.UUID(subject)
            except ValueError:
                return None
            async with async_session_factory() as session:
                if not await mcp_subject_allowed(session, user_id):
                    return None

        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scope_value.split(),
            expires_at=expires_at,
            resource=str(get_settings().mcp_resource_url),
            subject=subject,
            claims={
                "iss": str(get_settings().mcp_authorization_server_url),
                "jti": jti,
            },
        )

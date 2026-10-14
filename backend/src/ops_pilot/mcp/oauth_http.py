from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.routes import (
    build_metadata,
    cors_middleware,
    create_auth_routes,
)
from mcp.server.auth.settings import (
    ClientRegistrationOptions,
    RevocationOptions,
)
from starlette.routing import (
    BaseRoute,
    Route,
)

from ops_pilot.core.config import get_settings
from ops_pilot.mcp.oauth_login import (
    oauth_login_page,
    oauth_login_submit,
)
from ops_pilot.mcp.oauth_provider import (
    OpsPilotOAuthProvider,
)

oauth_provider = OpsPilotOAuthProvider()


def build_oauth_routes() -> list[BaseRoute]:
    settings = get_settings()

    registration_options = ClientRegistrationOptions(
        enabled=True,
        valid_scopes=[
            settings.mcp_required_scope,
        ],
        default_scopes=[
            settings.mcp_required_scope,
        ],
    )

    revocation_options = RevocationOptions(
        enabled=True,
    )

    sdk_routes = list(
        create_auth_routes(
            provider=oauth_provider,
            issuer_url=settings.mcp_authorization_server_url,
            client_registration_options=registration_options,
            revocation_options=revocation_options,
        )
    )

    metadata = build_metadata(
        issuer_url=settings.mcp_authorization_server_url,
        service_documentation_url=None,
        client_registration_options=registration_options,
        revocation_options=revocation_options,
    )

    metadata.token_endpoint_auth_methods_supported = [
        "none",
    ]

    metadata.revocation_endpoint_auth_methods_supported = [
        "none",
    ]

    routes: list[BaseRoute] = [
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=cors_middleware(
                MetadataHandler(metadata).handle,
                [
                    "GET",
                    "OPTIONS",
                ],
            ),
            methods=[
                "GET",
                "OPTIONS",
            ],
        )
    ]

    routes.extend(
        route
        for route in sdk_routes
        if getattr(
            route,
            "path",
            None,
        )
        != "/.well-known/oauth-authorization-server"
    )

    routes.extend(
        [
            Route(
                "/oauth/login",
                endpoint=oauth_login_page,
                methods=[
                    "GET",
                ],
            ),
            Route(
                "/oauth/login",
                endpoint=oauth_login_submit,
                methods=[
                    "POST",
                ],
            ),
        ]
    )

    return routes

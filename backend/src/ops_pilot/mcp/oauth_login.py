import html

from mcp.server.auth.provider import (
    construct_redirect_uri,
)
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    RedirectResponse,
    Response,
)

from ops_pilot.core.config import get_settings
from ops_pilot.db.session import async_session_factory
from ops_pilot.services.auth import authenticate_user
from ops_pilot.services.oauth import (
    create_authorization_code,
    get_oauth_client,
    oauth_client_redirect_uris,
)


async def oauth_login_page(
    request: Request,
) -> Response:
    params = request.query_params

    required = [
        "client_id",
        "redirect_uri",
        "scope",
        "code_challenge",
        "resource",
        "redirect_uri_explicit",
    ]

    if any(not params.get(name) for name in required):
        return HTMLResponse(
            "Invalid OAuth authorization request.",
            status_code=400,
        )

    # state = params.get(
    #     "state",
    #     "",
    # )

    hidden_inputs = ""

    for key in [
        "client_id",
        "redirect_uri",
        "state",
        "scope",
        "code_challenge",
        "resource",
        "redirect_uri_explicit",
    ]:
        hidden_inputs += (
            f'<input type="hidden" '
            f'name="{html.escape(key)}" '
            f'value="{html.escape(params.get(key, ""))}">'
        )

    return HTMLResponse(
        f"""
        <!doctype html>
        <html>
        <head>
            <title>Authorize OpsPilot</title>
        </head>
        <body>
            <h1>Authorize OpsPilot</h1>
            <p>
                Sign in to allow this MCP client
                to access your OpsPilot account.
            </p>

            <form method="post" action="/oauth/login">
                {hidden_inputs}

                <label>Email</label><br>
                <input
                    type="email"
                    name="email"
                    required
                ><br><br>

                <label>Password</label><br>
                <input
                    type="password"
                    name="password"
                    required
                ><br><br>

                <button type="submit">
                    Sign in and authorize
                </button>
            </form>
        </body>
        </html>
        """
    )


async def oauth_login_submit(
    request: Request,
) -> Response:
    form = await request.form()

    values = {
        key: form.get(key)
        for key in [
            "email",
            "password",
            "client_id",
            "redirect_uri",
            "state",
            "scope",
            "code_challenge",
            "resource",
            "redirect_uri_explicit",
        ]
    }

    if not all(
        isinstance(
            values[key],
            str,
        )
        and values[key]
        for key in [
            "email",
            "password",
            "client_id",
            "redirect_uri",
            "scope",
            "code_challenge",
            "resource",
            "redirect_uri_explicit",
        ]
    ):
        return HTMLResponse(
            "Invalid OAuth authorization request.",
            status_code=400,
        )

    settings = get_settings()

    client_id = str(values["client_id"])
    redirect_uri = str(values["redirect_uri"])
    scope = str(values["scope"])
    resource = str(values["resource"])
    code_challenge = str(values["code_challenge"])
    state = (
        str(values["state"])
        if isinstance(
            values["state"],
            str,
        )
        else None
    )

    if resource != str(settings.mcp_resource_url):
        return HTMLResponse(
            "Invalid OAuth resource.",
            status_code=400,
        )

    scopes = scope.split()

    if scopes != [settings.mcp_required_scope]:
        return HTMLResponse(
            "Invalid OAuth scope.",
            status_code=400,
        )

    async with async_session_factory() as session:
        client = await get_oauth_client(
            session=session,
            client_id=client_id,
        )

        if client is None:
            return HTMLResponse(
                "Unknown OAuth client.",
                status_code=400,
            )

        if redirect_uri not in (oauth_client_redirect_uris(client)):
            return HTMLResponse(
                "Invalid redirect URI.",
                status_code=400,
            )

        user = await authenticate_user(
            session,
            str(values["email"]),
            str(values["password"]),
        )

        if user is None:
            return HTMLResponse(
                "Invalid email or password.",
                status_code=401,
            )

        code = await create_authorization_code(
            session=session,
            client_id=client_id,
            user_id=user.id,
            redirect_uri=redirect_uri,
            scopes=scopes,
            code_challenge=code_challenge,
            resource=resource,
        )

    location = construct_redirect_uri(
        redirect_uri,
        code=code,
        state=state,
        iss=str(settings.mcp_authorization_server_url),
    )

    return RedirectResponse(
        url=location,
        status_code=302,
        headers={
            "Cache-Control": "no-store",
        },
    )

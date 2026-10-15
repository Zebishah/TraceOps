from starlette.types import (
    ASGIApp,
    Message,
    Receive,
    Scope,
    Send,
)

from ops_pilot.core.request_context import (
    normalize_request_id,
    reset_request_id,
    set_request_id,
)


class RequestContextMiddleware:
    def __init__(
        self,
        app: ASGIApp,
    ) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(
                scope,
                receive,
                send,
            )
            return

        headers = dict(
            scope.get(
                "headers",
                [],
            )
        )

        incoming_request_id = headers.get(b"x-request-id")

        request_id = normalize_request_id(
            incoming_request_id.decode(
                "utf-8",
                errors="ignore",
            )
            if incoming_request_id
            else None
        )

        token = set_request_id(request_id)

        async def send_with_request_id(
            message: Message,
        ) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(
                    message.get(
                        "headers",
                        [],
                    )
                )

                response_headers.append(
                    (
                        b"x-request-id",
                        request_id.encode("utf-8"),
                    )
                )

                message["headers"] = response_headers

            await send(message)

        try:
            await self.app(
                scope,
                receive,
                send_with_request_id,
            )
        finally:
            reset_request_id(token)

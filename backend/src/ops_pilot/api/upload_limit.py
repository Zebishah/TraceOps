"""Limit document upload requests before multipart parsing."""

from collections import deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_DOCUMENT_UPLOAD_REQUEST_BYTES = 10 * 1024 * 1024 + 512 * 1024


def is_document_upload(scope: Scope) -> bool:
    """Match POST /api/v1/organizations/{id}/documents."""
    if scope["type"] != "http" or scope.get("method") != "POST":
        return False

    parts = scope.get("path", "").strip("/").split("/")

    return (
        len(parts) == 5
        and parts[0] == "api"
        and parts[1] == "v1"
        and parts[2] == "organizations"
        and bool(parts[3])
        and parts[4] == "documents"
    )


async def send_error(
    send: Send,
    *,
    status_code: int,
    message: bytes,
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(message)).encode()),
            ],
        }
    )

    await send(
        {
            "type": "http.response.body",
            "body": message,
            "more_body": False,
        }
    )


class DocumentUploadLimitMiddleware:
    """Bound upload body memory before FastAPI handles multipart data."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if not is_document_upload(scope):
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value for key, value in scope.get("headers", []) if key.lower() == b"content-length"
        ]

        if len(content_lengths) > 1:
            await send_error(
                send,
                status_code=400,
                message=b'{"detail":"Invalid Content-Length"}',
            )
            return

        if content_lengths:
            try:
                raw_length = content_lengths[0].decode("ascii")

                if not raw_length.isdecimal():
                    raise ValueError

                declared_length = int(raw_length)

            except (UnicodeError, ValueError):
                await send_error(
                    send,
                    status_code=400,
                    message=b'{"detail":"Invalid Content-Length"}',
                )
                return

            if declared_length > MAX_DOCUMENT_UPLOAD_REQUEST_BYTES:
                await send_error(
                    send,
                    status_code=413,
                    message=b'{"detail":"Document upload too large"}',
                )
                return

        messages: deque[Message] = deque()
        total_bytes = 0

        # Fully bound the body before invoking multipart parsing.
        while True:
            message = await receive()

            if message["type"] == "http.disconnect":
                return

            if message["type"] != "http.request":
                await send_error(
                    send,
                    status_code=400,
                    message=b'{"detail":"Invalid upload request"}',
                )
                return

            body = message.get("body", b"")
            total_bytes += len(body)

            if total_bytes > MAX_DOCUMENT_UPLOAD_REQUEST_BYTES:
                await send_error(
                    send,
                    status_code=413,
                    message=b'{"detail":"Document upload too large"}',
                )
                return

            messages.append(message)

            if not message.get("more_body", False):
                break

        if content_lengths and total_bytes != declared_length:
            await send_error(
                send,
                status_code=400,
                message=b'{"detail":"Content-Length mismatch"}',
            )
            return

        async def replay_receive() -> Message:
            if messages:
                return messages.popleft()

            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        await self.app(scope, replay_receive, send)

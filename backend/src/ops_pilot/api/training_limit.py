"""Bound dashboard training JSON before FastAPI parses it. Artifacts stream separately."""

import asyncio
from collections import deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ops_pilot.api.upload_limit import send_error


class TrainingBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        parts = scope.get("path", "").strip("/").split("/")
        organization = (
            len(parts) >= 5
            and parts[:3] == ["api", "v1", "organizations"]
            and parts[4] == "training"
        )
        internal = parts[:4] == ["api", "v1", "internal", "training"]
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not (organization or internal)
        ):
            await self.app(scope, receive, send)
            return
        limit = 512 * 1024 if organization and parts[-1] == "runs" else 8192
        messages: deque[Message] = deque()
        total = 0
        try:
            async with asyncio.timeout(30):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    total += len(message.get("body", b""))
                    if total > limit:
                        await send_error(
                            send, status_code=413, message=b'{"detail":"Training body too large"}'
                        )
                        return
                    messages.append(message)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await send_error(
                send, status_code=408, message=b'{"detail":"Training upload timed out"}'
            )
            return

        async def replay() -> Message:
            return messages.popleft() if messages else {"type": "http.disconnect"}

        await self.app(scope, replay, send)

"""Bound voice bodies before multipart/JSON parsing, without changing other routes."""

import asyncio
from collections import deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ops_pilot.api.upload_limit import send_error
from ops_pilot.services.voice import MAX_AUDIO_BYTES


class VoiceBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        parts = scope.get("path", "").strip("/").split("/")
        if not (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and len(parts) == 6
            and parts[:3] == ["api", "v1", "organizations"]
            and parts[4] == "voice"
            and parts[5] in {"transcriptions", "speech"}
        ):
            await self.app(scope, receive, send)
            return
        limit = MAX_AUDIO_BYTES + 512 * 1024 if parts[5] == "transcriptions" else 4096
        lengths = [v for k, v in scope.get("headers", []) if k.lower() == b"content-length"]
        declared: int | None = None
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit():
                await send_error(
                    send, status_code=400, message=b'{"detail":"Invalid Content-Length"}'
                )
                return
            try:
                declared = int(lengths[0])
            except ValueError:
                await send_error(
                    send, status_code=400, message=b'{"detail":"Invalid Content-Length"}'
                )
                return
            if declared > limit:
                await send_error(
                    send, status_code=413, message=b'{"detail":"Voice body too large"}'
                )
                return
        messages: deque[Message] = deque()
        size = 0
        try:
            async with asyncio.timeout(30):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    if message["type"] != "http.request":
                        await send_error(
                            send, status_code=400, message=b'{"detail":"Invalid body"}'
                        )
                        return
                    size += len(message.get("body", b""))
                    if size > limit:
                        await send_error(
                            send, status_code=413, message=b'{"detail":"Voice body too large"}'
                        )
                        return
                    messages.append(message)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await send_error(send, status_code=408, message=b'{"detail":"Voice upload timed out"}')
            return
        if declared is not None and size != declared:
            await send_error(send, status_code=400, message=b'{"detail":"Content-Length mismatch"}')
            return

        async def replay() -> Message:
            return messages.popleft() if messages else {"type": "http.disconnect"}

        await self.app(scope, replay, send)

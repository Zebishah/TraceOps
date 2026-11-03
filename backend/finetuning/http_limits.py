"""Bound private worker requests before JSON parsing, including chunked bodies."""

import asyncio
from collections import deque


class WorkerBodyLimitMiddleware:
    def __init__(self, app, max_bytes=64 * 1024, timeout_seconds=5):
        self.app = app
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        async def reject(code, message):
            await send(
                {
                    "type": "http.response.start",
                    "status": code,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": message})

        lengths = [
            value for key, value in scope.get("headers", []) if key.lower() == b"content-length"
        ]
        if lengths and (len(lengths) != 1 or not lengths[0].isdigit() or len(lengths[0]) > 12):
            await reject(400, b'{"detail":"Invalid Content-Length"}')
            return
        declared = int(lengths[0]) if lengths else None
        if declared is not None and declared > self.max_bytes:
            await reject(413, b'{"detail":"Worker request too large"}')
            return
        messages = deque()
        size = 0
        try:
            async with asyncio.timeout(self.timeout_seconds):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    if message["type"] != "http.request":
                        await reject(400, b'{"detail":"Invalid body"}')
                        return
                    size += len(message.get("body", b""))
                    if size > self.max_bytes:
                        await reject(413, b'{"detail":"Worker request too large"}')
                        return
                    messages.append(message)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await reject(408, b'{"detail":"Worker upload timed out"}')
            return
        if declared is not None and declared != size:
            await reject(400, b'{"detail":"Content-Length mismatch"}')
            return

        async def replay():
            return messages.popleft() if messages else {"type": "http.disconnect"}

        await self.app(scope, replay, send)

"""ASGI middleware that enforces a per-request timeout."""

import asyncio
import logging

logger = logging.getLogger(__name__)


class RequestTimeoutMiddleware:
    """Wraps an ASGI app and cancels requests that exceed timeout_seconds.

    Returns 504 Gateway Timeout if the inner app does not complete in time.
    """

    def __init__(self, app, timeout_seconds: float = 120.0):
        self.app = app
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers_sent = False

        async def guarded_send(message):
            nonlocal headers_sent
            if message["type"] == "http.response.start":
                headers_sent = True
            await send(message)

        try:
            await asyncio.wait_for(
                self.app(scope, receive, guarded_send),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            path = scope.get("path", "?")
            logger.warning("Request timed out after %.0fs: %s", self.timeout_seconds, path)
            if not headers_sent:
                await send({
                    "type": "http.response.start",
                    "status": 504,
                    "headers": [[b"content-type", b"text/plain"]],
                })
                await send({
                    "type": "http.response.body",
                    "body": b"Request timed out. Please try again.",
                })

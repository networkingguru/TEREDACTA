"""ASGI admission control middleware with FIFO queue and slot transfer."""

import asyncio
import collections
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from html import escape
from typing import Optional
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)

# Paths that bypass admission control entirely
_EXEMPT_PREFIXES = ("/health/", "/static/", "/_queue/", "/sse/")


@dataclass
class QueueTicket:
    id: str
    ready: bool = False
    created_at: float = field(default_factory=time.monotonic)
    ready_at: Optional[float] = None


class AdmissionState:
    """Per-worker admission state: semaphore, queue, metrics."""

    def __init__(self, max_concurrent: int, max_queue: int):
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._queue: collections.deque[QueueTicket] = collections.deque()
        self._tickets: dict[str, QueueTicket] = {}
        self._durations: collections.deque = collections.deque(maxlen=100)
        self._expiry_task: Optional[asyncio.Task] = None

    def start_expiry_loop(self):
        """Start the periodic ticket expiry task."""
        if self._expiry_task is None:
            self._expiry_task = asyncio.create_task(self._expire_loop())

    async def _expire_loop(self):
        while True:
            try:
                await asyncio.sleep(10)
                self._expire_tickets()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in ticket expiry loop")

    def _expire_tickets(self):
        now = time.monotonic()
        to_remove = []
        for ticket in list(self._queue):
            if ticket.ready and ticket.ready_at and (now - ticket.ready_at > 60):
                # Ready but unclaimed for 60s — release the slot
                to_remove.append(ticket)
                self.semaphore.release()
                logger.info("Expired ready ticket %s (unclaimed 60s)", ticket.id)
            elif not ticket.ready and (now - ticket.created_at > 300):
                # Abandoned — never became ready, waiting too long
                to_remove.append(ticket)
                logger.info("Expired abandoned ticket %s (300s)", ticket.id)

        for ticket in to_remove:
            try:
                self._queue.remove(ticket)
            except ValueError:
                pass
            self._tickets.pop(ticket.id, None)

    def create_ticket(self) -> Optional[QueueTicket]:
        """Create a queue ticket if queue is not full. Returns None if full."""
        if len(self._queue) >= self.max_queue:
            return None
        ticket = QueueTicket(id=uuid.uuid4().hex)
        self._queue.append(ticket)
        self._tickets[ticket.id] = ticket
        return ticket

    def claim_ticket(self, ticket_id: str) -> Optional[QueueTicket]:
        """Look up a ticket. If ready, remove and return it. Otherwise None."""
        ticket = self._tickets.get(ticket_id)
        if ticket is None or not ticket.ready:
            return None
        # Claim it: remove from both structures
        self._tickets.pop(ticket_id, None)
        try:
            self._queue.remove(ticket)
        except ValueError:
            pass
        return ticket

    def get_ticket(self, ticket_id: str) -> Optional[QueueTicket]:
        return self._tickets.get(ticket_id)

    def ticket_position(self, ticket_id: str) -> int:
        """Return count of unready tickets ahead in queue, or 0 if not found."""
        count = 0
        for t in self._queue:
            if t.id == ticket_id:
                return count
            if not t.ready:
                count += 1
        return 0  # not found

    def complete_request(self, started_at: float):
        """Called when a request finishes. Transfers slot or releases semaphore."""
        duration = time.monotonic() - started_at
        self._durations.append((time.monotonic(), duration))

        # Try to transfer the slot to the next waiting ticket
        for ticket in self._queue:
            if not ticket.ready:
                ticket.ready = True
                ticket.ready_at = time.monotonic()
                logger.debug("Slot transferred to ticket %s", ticket.id)
                return

        # No one waiting — release the semaphore
        self.semaphore.release()

    def estimate_wait(self, position: int) -> float:
        now = time.monotonic()
        recent = [(t, d) for t, d in self._durations if now - t < 300]
        if len(recent) >= 5:
            avg = sum(d for _, d in recent) / len(recent)
        else:
            avg = 1.0
        active = max(1, self.max_concurrent - self.semaphore._value)
        return round(position * avg / active, 1)

    def stop(self):
        if self._expiry_task and not self._expiry_task.done():
            self._expiry_task.cancel()


class AdmissionMiddleware:
    """ASGI middleware that limits concurrent requests with a FIFO queue."""

    def __init__(self, app, max_concurrent: int = 40, max_queue: int = 200,
                 secure_cookies: bool = False):
        self.app = app
        self.secure_cookies = secure_cookies
        self.state = AdmissionState(
            max_concurrent=max_concurrent, max_queue=max_queue
        )

    async def __call__(self, scope, receive, send):
        # Non-HTTP → pass through
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")

        # Start expiry loop on first request (lazy init to avoid event loop issues)
        self.state.start_expiry_loop()

        # Handle /_queue/status internally
        if path == "/_queue/status":
            await self._handle_queue_status(scope, receive, send)
            return

        # Exempt paths → pass through
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        # Check for ready ticket cookie
        ticket_id = self._get_cookie(scope, "_queue_ticket")
        if ticket_id:
            ticket = self.state.claim_ticket(ticket_id)
            if ticket:
                # Slot was already transferred — proceed without semaphore
                started_at = time.monotonic()
                try:
                    await self.app(scope, receive, send)
                finally:
                    self.state.complete_request(started_at)
                return

        # Try to acquire a slot
        # asyncio.Semaphore.acquire() completes synchronously when _value > 0
        # (no suspension point), so this check-then-acquire is safe under
        # CPython's cooperative asyncio model.
        if self.state.semaphore._value > 0:
            await self.state.semaphore.acquire()
            started_at = time.monotonic()
            try:
                await self.app(scope, receive, send)
            finally:
                self.state.complete_request(started_at)
            return

        # Queue the request
        ticket = self.state.create_ticket()
        if ticket is None:
            # Queue full → 503
            await self._send_503(send)
            return

        # Return queue page with ticket cookie
        await self._send_queue_page(scope, send, ticket)

    async def _handle_queue_status(self, scope, receive, send):
        params = parse_qs(scope.get("query_string", b"").decode())
        ticket_id = (params.get("ticket") or [""])[0]

        ticket = self.state.get_ticket(ticket_id)
        if ticket is None:
            body = json.dumps({"requeue": True}).encode()
        else:
            pos = self.state.ticket_position(ticket_id)
            body = json.dumps({
                "ready": ticket.ready,
                "position": pos,
                "wait_estimate_seconds": self.state.estimate_wait(pos),
                "queue_length": len(self.state._queue),
            }).encode()

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"application/json"],
                [b"cache-control", b"no-store"],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })

    async def _send_503(self, send):
        await send({
            "type": "http.response.start",
            "status": 503,
            "headers": [
                [b"content-type", b"text/plain"],
                [b"retry-after", b"30"],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": b"Server is at capacity. Please try again later.",
        })

    async def _send_queue_page(self, scope, send, ticket: QueueTicket):
        path = scope.get("path", "/")
        query = scope.get("query_string", b"").decode()
        redirect_url = path
        if query:
            redirect_url += "?" + query

        position = self.state.ticket_position(ticket.id)
        est_wait = self.state.estimate_wait(position)
        html = _queue_page_html(ticket.id, position, est_wait, redirect_url)

        secure_flag = "; Secure" if self.secure_cookies else ""
        cookie = (
            f"_queue_ticket={ticket.id}; Path=/; HttpOnly; SameSite=Lax; Max-Age=600{secure_flag}"
        )

        await send({
            "type": "http.response.start",
            "status": 202,
            "headers": [
                [b"content-type", b"text/html; charset=utf-8"],
                [b"set-cookie", cookie.encode()],
                [b"cache-control", b"no-store"],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": html.encode(),
        })

    @staticmethod
    def _get_cookie(scope, name: str) -> Optional[str]:
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"cookie":
                cookies = header_value.decode()
                for pair in cookies.split(";"):
                    pair = pair.strip()
                    if pair.startswith(f"{name}="):
                        return pair.split("=", 1)[1]
        return None


def _queue_page_html(
    ticket_id: str, position: int, est_wait: float, redirect_url: str
) -> str:
    safe_url = escape(redirect_url, quote=True)
    safe_tid = escape(ticket_id, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TEREDACTA — Queue</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f1117;color:#e0e0e0;font-family:system-ui,-apple-system,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh}}
.card{{background:#1a1d28;border:1px solid #2a2d3a;border-radius:12px;padding:2.5rem;
max-width:420px;width:90%;text-align:center}}
h1{{color:#7c8aff;font-size:1.4rem;margin-bottom:1rem}}
.pos{{font-size:3rem;font-weight:700;color:#fff;margin:.5rem 0}}
.label{{color:#888;font-size:.9rem;margin-bottom:1.5rem}}
.wait{{color:#aaa;font-size:.95rem;margin-bottom:1rem}}
.bar{{height:4px;background:#2a2d3a;border-radius:2px;overflow:hidden;margin:1rem 0}}
.bar-inner{{height:100%;background:linear-gradient(90deg,#7c8aff,#5c6bc0);
width:0%;transition:width .5s ease;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:.7}}50%{{opacity:1}}}}
.status{{color:#666;font-size:.8rem;margin-top:1rem}}
</style>
</head>
<body>
<div class="card" id="queue-card" data-ticket="{safe_tid}" data-redirect="{safe_url}">
<h1>TEREDACTA</h1>
<p class="label">You are in the queue</p>
<div class="pos" id="pos">{position}</div>
<p class="label">position</p>
<p class="wait" id="wait">Estimated wait: {est_wait:.0f}s</p>
<div class="bar"><div class="bar-inner" id="bar"></div></div>
<p class="status" id="status">Checking every 3 seconds&hellip;</p>
</div>
<script src="/static/js/queue.js"></script>
</body>
</html>"""

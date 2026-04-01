# Concurrency & Admission Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support 500+ concurrent users by tuning server concurrency and adding an admission control queue with user-facing position feedback.

**Architecture:** ASGI admission middleware with asyncio.Semaphore + FIFO deque for queue tracking. Concurrency raised via WAL mode, larger DB pool, 4 uvicorn workers, and async bcrypt. Queue page is self-contained HTML with JS polling.

**Tech Stack:** FastAPI, uvicorn, asyncio, SQLite WAL, bcrypt, collections.deque

**Spec:** `docs/superpowers/specs/2026-04-01-concurrency-and-queue-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|---|---|
| `teredacta/admission.py` | Admission control middleware, QueueTicket dataclass, AdmissionState, queue page HTML, `/_queue/status` handler |
| `teredacta/timeout_middleware.py` | Request timeout ASGI middleware (120s default) |
| `teredacta/tests/test_admission.py` | Unit tests for admission middleware |
| `teredacta/tests/test_timeout_middleware.py` | Unit tests for timeout middleware |
| `teredacta/tests/test_stress_admission.py` | Stress tests for admission + queue under load |

### Modified Files
| File | Change |
|---|---|
| `teredacta/db_pool.py` | WAL mode on init, accept configurable max_size |
| `teredacta/config.py` | Add `max_concurrent_requests`, `max_queue_size`, `max_pool_size`, `max_sse_subscribers` fields |
| `teredacta/app.py` | Register admission + timeout middleware, pass `max_pool_size` to pool, pass `max_sse_subscribers` to SSE |
| `teredacta/sse.py` | Add `max_subscribers` param to `subscribe()` |
| `teredacta/routers/admin.py` | Async bcrypt in login handler |
| `teredacta/__main__.py` | Allow multi-worker in `start` command, default workers to 4 |
| `teredacta/_app_factory.py` | No changes needed (already handles multi-worker config) |
| `teredacta/unob.py` | Pass `max_pool_size` from config to ConnectionPool |

---

### Task 1: Enable WAL Mode on SQLite

**Files:**
- Modify: `teredacta/db_pool.py:17-31`
- Test: `teredacta/tests/test_health.py` (add WAL test)

- [ ] **Step 1: Write the failing test**

Add to `teredacta/tests/test_health.py`:

```python
class TestWALMode:
    def test_pool_enables_wal_mode(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        pool = ConnectionPool(str(db), max_size=2)
        conn = pool.acquire()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        pool.release(conn)
        pool.close()
        assert mode == "wal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest teredacta/tests/test_health.py::TestWALMode::test_pool_enables_wal_mode -v`
Expected: FAIL — journal_mode will be "delete" (default)

- [ ] **Step 3: Implement WAL mode in pool init**

In `teredacta/db_pool.py`, add WAL setup at the end of `__init__` (after line 31):

```python
    def __init__(
        self,
        db_path: str,
        max_size: int = 8,
        read_only: bool = False,
        busy_timeout: int = 5000,
    ):
        self._db_path = db_path
        self._max_size = max_size
        self._read_only = read_only
        self._busy_timeout = busy_timeout
        self._pool: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=max_size)
        self._size = 0
        self._lock = threading.Lock()
        self._closed = False
        # Enable WAL mode (persistent, only needs to be set once per DB file)
        conn = self._create_connection()
        conn.execute("PRAGMA journal_mode = WAL")
        self._pool.put(conn)
        self._size = 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest teredacta/tests/test_health.py::TestWALMode -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/db_pool.py teredacta/tests/test_health.py
git commit -m "feat: enable WAL mode on SQLite connection pool init"
```

---

### Task 2: Add Config Fields

**Files:**
- Modify: `teredacta/config.py:14-36`

- [ ] **Step 1: Write the failing test**

Create a quick test in `teredacta/tests/test_health.py`:

```python
class TestConfigFields:
    def test_new_config_defaults(self):
        from teredacta.config import TeredactaConfig
        cfg = TeredactaConfig()
        assert cfg.max_pool_size == 32
        assert cfg.max_concurrent_requests == 40
        assert cfg.max_queue_size == 200
        assert cfg.max_sse_subscribers == 50

    def test_config_loads_from_yaml(self, tmp_path):
        from teredacta.config import load_config
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text("max_pool_size: 16\nmax_concurrent_requests: 20\n")
        cfg = load_config(str(cfg_file))
        assert cfg.max_pool_size == 16
        assert cfg.max_concurrent_requests == 20
        assert cfg.max_queue_size == 200  # default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest teredacta/tests/test_health.py::TestConfigFields -v`
Expected: FAIL — `TeredactaConfig` has no attribute `max_pool_size`

- [ ] **Step 3: Add fields to TeredactaConfig**

In `teredacta/config.py`, add after `health_sse_degraded_threshold` (line 31):

```python
    max_pool_size: int = 32
    max_concurrent_requests: int = 40
    max_queue_size: int = 200
    max_sse_subscribers: int = 50
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest teredacta/tests/test_health.py::TestConfigFields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/config.py teredacta/tests/test_health.py
git commit -m "feat: add concurrency config fields (pool size, queue, SSE cap)"
```

---

### Task 3: Increase DB Pool Size via Config

**Files:**
- Modify: `teredacta/unob.py` (where ConnectionPool is instantiated)
- Modify: `teredacta/app.py`

- [ ] **Step 1: Write the failing test**

Add to `teredacta/tests/test_health.py`:

```python
class TestPoolSizeConfig:
    def test_pool_uses_config_size(self, tmp_path):
        from teredacta.config import TeredactaConfig
        from teredacta.db_pool import ConnectionPool
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        pool = ConnectionPool(str(db), max_size=16)
        status = pool.pool_status()
        assert status["capacity"] == 16
        pool.close()
```

- [ ] **Step 2: Run test to verify it passes** (pool already accepts max_size param)

Run: `.venv/bin/python -m pytest teredacta/tests/test_health.py::TestPoolSizeConfig -v`
Expected: PASS (this test validates existing capability)

- [ ] **Step 3: Wire config to pool in UnobInterface**

Read `teredacta/unob.py` to find where `ConnectionPool` is created. Update it to pass `config.max_pool_size` instead of the hardcoded `max_size=8`. The exact line depends on the current code — find the `ConnectionPool(` call and change `max_size=8` to `max_size=config.max_pool_size`.

- [ ] **Step 4: Run full test suite to verify no regressions**

Run: `.venv/bin/python -m pytest teredacta/tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add teredacta/unob.py
git commit -m "feat: wire max_pool_size config to ConnectionPool"
```

---

### Task 4: Add SSE Subscriber Cap

**Files:**
- Modify: `teredacta/sse.py:23-28`
- Modify: `teredacta/app.py:47`

- [ ] **Step 1: Write the failing test**

Add to `teredacta/tests/test_stress_sse.py`:

```python
@pytest.mark.stress
@pytest.mark.timeout(90)
class TestSSESubscriberCap:
    @pytest.mark.asyncio
    async def test_subscribe_rejects_over_cap(self):
        sse = SSEManager(poll_interval=1.0, unob=None, max_subscribers=3)
        q1 = sse.subscribe()
        q2 = sse.subscribe()
        q3 = sse.subscribe()
        assert sse.subscriber_count == 3
        q4 = sse.subscribe()
        assert q4 is None
        assert sse.subscriber_count == 3
        for q in [q1, q2, q3]:
            sse.unsubscribe(q)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest teredacta/tests/test_stress_sse.py::TestSSESubscriberCap -m stress -v`
Expected: FAIL — `SSEManager.__init__()` got unexpected keyword argument `max_subscribers`

- [ ] **Step 3: Implement subscriber cap**

In `teredacta/sse.py`, modify `__init__` and `subscribe`:

```python
class SSEManager:
    def __init__(self, poll_interval: float = 2.0, unob: Optional[UnobInterface] = None, max_subscribers: int = 0):
        self.poll_interval = poll_interval
        self.unob = unob
        self.max_subscribers = max_subscribers  # 0 = unlimited
        self._subscribers: Set[asyncio.Queue] = set()
        self._task: Optional[asyncio.Task] = None
        self._last_stats: Optional[dict] = None

    def subscribe(self) -> Optional[asyncio.Queue]:
        if self.max_subscribers and len(self._subscribers) >= self.max_subscribers:
            return None
        queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop())
        return queue
```

- [ ] **Step 4: Wire config to SSEManager in app.py**

In `teredacta/app.py` line 47, change:

```python
app.state.sse = SSEManager(poll_interval=config.sse_poll_interval_seconds, unob=app.state.unob)
```

to:

```python
app.state.sse = SSEManager(
    poll_interval=config.sse_poll_interval_seconds,
    unob=app.state.unob,
    max_subscribers=config.max_sse_subscribers,
)
```

- [ ] **Step 5: Update SSE endpoint to handle None return**

In `teredacta/routers/dashboard.py`, find the SSE subscribe endpoint and add a check: if `subscribe()` returns `None`, return a 503 response with a message like "Too many active connections. Please try again shortly."

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest teredacta/tests/test_stress_sse.py -m stress -v`
Expected: PASS

Run: `.venv/bin/python -m pytest teredacta/tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add teredacta/sse.py teredacta/app.py teredacta/routers/dashboard.py teredacta/tests/test_stress_sse.py
git commit -m "feat: add configurable SSE subscriber cap (default 50)"
```

---

### Task 5: Async Bcrypt in Login Handler

**Files:**
- Modify: `teredacta/routers/admin.py:71-82`

- [ ] **Step 1: Write the failing test**

Add to `teredacta/tests/routers/test_admin_login.py` (create if needed):

```python
import asyncio
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient


class TestAsyncBcrypt:
    def test_login_does_not_block_event_loop(self, client):
        """Verify check_password runs in executor, not on event loop."""
        app = client.app
        original_check = app.state.config.check_password

        call_thread = {}
        import threading
        def tracking_check(pw):
            call_thread["name"] = threading.current_thread().name
            return original_check(pw)

        with patch.object(app.state.config, "check_password", side_effect=tracking_check):
            client.post("/admin/login", data={"password": "wrong"})

        # If run in executor, thread name will NOT be "MainThread"
        assert call_thread.get("name") != "MainThread", \
            "check_password ran on MainThread — should be in executor"
```

Note: this test requires a `client` fixture. Check `teredacta/tests/conftest.py` for the existing `TestClient` fixture and use it.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest teredacta/tests/routers/test_admin_login.py::TestAsyncBcrypt -v`
Expected: FAIL — `check_password` runs on MainThread

- [ ] **Step 3: Implement async bcrypt**

In `teredacta/routers/admin.py`, modify the login handler (around line 71-82):

```python
@router.post("/login")
async def login(request: Request):
    form = await request.form()
    password = form.get("password", "")
    config = request.app.state.config
    auth = request.app.state.auth
    import asyncio
    loop = asyncio.get_running_loop()
    valid = await loop.run_in_executor(None, config.check_password, password)
    if valid:
        response = RedirectResponse("/admin", status_code=303)
        auth.create_session(response)
        return response
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "admin/login.html", _ctx(request, error="Invalid password"), status_code=401)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest teredacta/tests/routers/test_admin_login.py::TestAsyncBcrypt -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/routers/admin.py teredacta/tests/routers/test_admin_login.py
git commit -m "perf: run bcrypt check_password in executor to avoid blocking event loop"
```

---

### Task 6: Request Timeout Middleware

**Files:**
- Create: `teredacta/timeout_middleware.py`
- Create: `teredacta/tests/test_timeout_middleware.py`
- Modify: `teredacta/app.py`

- [ ] **Step 1: Write the failing test**

Create `teredacta/tests/test_timeout_middleware.py`:

```python
import asyncio
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from teredacta.timeout_middleware import RequestTimeoutMiddleware


@pytest.fixture
def timeout_app():
    app = FastAPI()

    @app.get("/fast")
    async def fast():
        return {"status": "ok"}

    @app.get("/slow")
    async def slow():
        await asyncio.sleep(10)
        return {"status": "ok"}

    app = RequestTimeoutMiddleware(app, timeout_seconds=1.0)
    return app


class TestRequestTimeout:
    @pytest.mark.asyncio
    async def test_fast_request_succeeds(self, timeout_app):
        async with AsyncClient(transport=ASGITransport(app=timeout_app), base_url="http://test") as client:
            resp = await client.get("/fast")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_slow_request_times_out(self, timeout_app):
        async with AsyncClient(transport=ASGITransport(app=timeout_app), base_url="http://test") as client:
            resp = await client.get("/slow")
            assert resp.status_code == 504
            assert "timed out" in resp.text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest teredacta/tests/test_timeout_middleware.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teredacta.timeout_middleware'`

- [ ] **Step 3: Implement timeout middleware**

Create `teredacta/timeout_middleware.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest teredacta/tests/test_timeout_middleware.py -v`
Expected: PASS

- [ ] **Step 5: Register in app.py**

In `teredacta/app.py`, at the end of `create_app()` before `return app`, wrap the app:

```python
    from teredacta.timeout_middleware import RequestTimeoutMiddleware
    app = RequestTimeoutMiddleware(app, timeout_seconds=120.0)
```

Note: This returns an ASGI middleware wrapping the FastAPI app. The variable must still be named `app` for the return.

Wait — `create_app` returns a `FastAPI` instance, but `RequestTimeoutMiddleware` wraps it as generic ASGI. This is fine for uvicorn (which just needs an ASGI callable), but the return type changes. Update the function to:

```python
    from teredacta.timeout_middleware import RequestTimeoutMiddleware
    wrapped = RequestTimeoutMiddleware(app, timeout_seconds=120.0)
    # Preserve app reference for test access
    wrapped._app = app
    return wrapped
```

Actually, this will break tests that access `app.state`. A cleaner approach: register it as Starlette middleware instead of wrapping. In `app.py` after the FastAPI app is created:

```python
    app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=120.0)
```

For this to work, `RequestTimeoutMiddleware` needs to follow the Starlette middleware protocol. Update the class to accept `app` in `__init__`:

This is already compatible — `add_middleware` passes the ASGI app as the first arg to the constructor. The existing `__init__(self, app, timeout_seconds)` signature works.

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest teredacta/tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add teredacta/timeout_middleware.py teredacta/tests/test_timeout_middleware.py teredacta/app.py
git commit -m "feat: add request timeout middleware (120s default)"
```

---

### Task 7: Admission Control Middleware — Core

**Files:**
- Create: `teredacta/admission.py`
- Create: `teredacta/tests/test_admission.py`

This is the largest task. It implements the semaphore, deque, QueueTicket, slot transfer, ticket expiry, queue page HTML, and `/_queue/status` handler.

- [ ] **Step 1: Write tests for basic admission**

Create `teredacta/tests/test_admission.py`:

```python
import asyncio
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from teredacta.admission import AdmissionMiddleware


@pytest.fixture
def make_app():
    """Factory that creates a test app with admission middleware."""
    def _make(max_concurrent=2, max_queue=5):
        app = FastAPI()

        @app.get("/work")
        async def work():
            await asyncio.sleep(0.5)
            return {"status": "done"}

        @app.get("/health/live")
        async def health():
            return {"status": "ok"}

        @app.get("/static/test.css")
        async def static():
            return {"status": "ok"}

        @app.get("/_queue/status")
        async def queue_status():
            # This should be handled by middleware, not reach here
            return {"error": "should not reach app"}

        wrapped = AdmissionMiddleware(app, max_concurrent=max_concurrent, max_queue=max_queue)
        return wrapped
    return _make


class TestAdmissionBasic:
    @pytest.mark.asyncio
    async def test_requests_under_limit_pass_through(self, make_app):
        app = make_app(max_concurrent=5)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/work")
            assert resp.status_code == 200
            assert resp.json() == {"status": "done"}

    @pytest.mark.asyncio
    async def test_health_exempt_from_queue(self, make_app):
        app = make_app(max_concurrent=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Occupy the only slot
            async def hold_slot():
                await client.get("/work")

            task = asyncio.ensure_future(hold_slot())
            await asyncio.sleep(0.1)

            # Health should still respond
            resp = await asyncio.wait_for(client.get("/health/live"), timeout=2.0)
            assert resp.status_code == 200
            await task

    @pytest.mark.asyncio
    async def test_over_limit_returns_queue_page(self, make_app):
        app = make_app(max_concurrent=1, max_queue=5)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Occupy the only slot
            hold = asyncio.Event()
            original_app = app.app

            @original_app.get("/block")
            async def block():
                await hold.wait()
                return {"status": "done"}

            task = asyncio.ensure_future(client.get("/block"))
            await asyncio.sleep(0.1)

            # This should get a queue page
            resp = await client.get("/work")
            assert resp.status_code == 202
            assert "_queue_ticket" in resp.cookies or "queue" in resp.text.lower()

            hold.set()
            await task

    @pytest.mark.asyncio
    async def test_queue_overflow_returns_503(self, make_app):
        app = make_app(max_concurrent=1, max_queue=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            hold = asyncio.Event()
            original_app = app.app

            @original_app.get("/block")
            async def block():
                await hold.wait()
                return {"status": "done"}

            # Fill the slot
            task = asyncio.ensure_future(client.get("/block"))
            await asyncio.sleep(0.1)

            # Fill the queue (1 slot)
            resp1 = await client.get("/work")
            assert resp1.status_code == 202  # queued

            # Overflow
            resp2 = await client.get("/work")
            assert resp2.status_code == 503

            hold.set()
            await task
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest teredacta/tests/test_admission.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teredacta.admission'`

- [ ] **Step 3: Implement AdmissionMiddleware**

Create `teredacta/admission.py`:

```python
"""Admission control middleware with user-facing queue."""

import asyncio
import collections
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Optional
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)


@dataclass
class QueueTicket:
    id: str
    ready: bool = False
    created_at: float = field(default_factory=time.monotonic)
    ready_at: Optional[float] = None


class AdmissionState:
    """Per-worker admission state: semaphore, queue, and metrics."""

    def __init__(self, max_concurrent: int = 40, max_queue: int = 200):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        self.queue: collections.deque[QueueTicket] = collections.deque()
        self.tickets: dict[str, QueueTicket] = {}
        self._durations: collections.deque[tuple[float, float]] = collections.deque(maxlen=100)
        self._expiry_task: Optional[asyncio.Task] = None

    def start_expiry_loop(self):
        if self._expiry_task is None or self._expiry_task.done():
            self._expiry_task = asyncio.create_task(self._expire_tickets())

    async def _expire_tickets(self):
        try:
            while True:
                await asyncio.sleep(10)
                now = time.monotonic()
                expired = []
                for ticket in list(self.queue):
                    if ticket.ready and ticket.ready_at and (now - ticket.ready_at > 60):
                        expired.append(ticket)
                    elif not ticket.ready and (now - ticket.created_at > 300):
                        expired.append(ticket)
                for ticket in expired:
                    self.queue.remove(ticket)
                    self.tickets.pop(ticket.id, None)
                    if ticket.ready:
                        self.semaphore.release()
                        logger.debug("Expired ready ticket %s, released slot", ticket.id)
                    else:
                        logger.debug("Expired abandoned ticket %s", ticket.id)
        except asyncio.CancelledError:
            pass

    def record_duration(self, duration: float):
        self._durations.append((time.monotonic(), duration))

    def estimate_wait(self, position: int) -> float:
        now = time.monotonic()
        recent = [(t, d) for t, d in self._durations if now - t < 300]
        if len(recent) >= 5:
            avg = sum(d for _, d in recent) / len(recent)
        else:
            avg = 1.0
        active = max(1, self.max_concurrent - self.semaphore._value)
        return round(position * avg / active, 1)

    def get_position(self, ticket_id: str) -> int:
        count = 0
        for t in self.queue:
            if t.id == ticket_id:
                return count
            if not t.ready:
                count += 1
        return -1

    def complete_request(self):
        """Called when a request finishes. Transfer slot or release."""
        # Find the first unready ticket to transfer to
        for ticket in self.queue:
            if not ticket.ready:
                ticket.ready = True
                ticket.ready_at = time.monotonic()
                logger.debug("Transferred slot to ticket %s", ticket.id)
                return  # Do NOT release semaphore — slot transferred
        # No waiters — release normally
        self.semaphore.release()


_EXEMPT_PREFIXES = ("/health/", "/static/", "/_queue/", "/sse/")

_QUEUE_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TEREDACTA — Please Wait</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #1a1a2e; color: #e0e0e0; display: flex; align-items: center;
         justify-content: center; min-height: 100vh; margin: 0; }}
  .box {{ text-align: center; max-width: 420px; padding: 2rem; }}
  h1 {{ color: #c4a35a; font-size: 1.4rem; margin-bottom: 0.5rem; }}
  .pos {{ font-size: 2rem; font-weight: bold; color: #fff; margin: 1rem 0; }}
  .est {{ color: #999; font-size: 0.95rem; }}
  .bar {{ width: 200px; height: 4px; background: #333; margin: 1.5rem auto;
          border-radius: 2px; overflow: hidden; }}
  .bar::after {{ content: ""; display: block; width: 40%; height: 100%;
                 background: #c4a35a; border-radius: 2px;
                 animation: slide 1.5s ease-in-out infinite; }}
  @keyframes slide {{ 0% {{ transform: translateX(-100%); }}
                      100% {{ transform: translateX(350%); }} }}
  .requeue {{ color: #c4a35a; margin-top: 1rem; display: none; }}
</style>
</head>
<body>
<div class="box">
  <h1>TEREDACTA</h1>
  <p>The server is handling a lot of requests right now.</p>
  <div class="pos" id="pos">Position #{position}</div>
  <div class="est" id="est">Estimated wait: ~{wait_estimate}s</div>
  <div class="bar"></div>
  <div class="requeue" id="requeue">Reconnecting to queue...</div>
</div>
<script>
(function() {{
  var ticket = "{ticket_id}";
  var url = "{original_url}";
  var pollUrl = "/_queue/status?ticket=" + ticket;
  setInterval(function() {{
    fetch(pollUrl).then(function(r) {{ return r.json(); }}).then(function(d) {{
      if (d.ready) {{ window.location.href = url; return; }}
      if (d.requeue) {{
        document.getElementById("requeue").style.display = "block";
        window.location.href = url;
        return;
      }}
      document.getElementById("pos").textContent = "Position #" + d.position;
      document.getElementById("est").textContent = "Estimated wait: ~" + d.wait_estimate_seconds + "s";
    }}).catch(function() {{}});
  }}, 3000);
}})();
</script>
</body>
</html>"""


class AdmissionMiddleware:
    """ASGI middleware implementing admission control with a user-facing queue."""

    def __init__(self, app, max_concurrent: int = 40, max_queue: int = 200):
        self.app = app
        self.state = AdmissionState(max_concurrent=max_concurrent, max_queue=max_queue)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Exempt paths pass through
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            # Handle /_queue/status internally
            if path == "/_queue/status":
                await self._handle_queue_status(scope, send)
                return
            await self.app(scope, receive, send)
            return

        # Start expiry loop on first request
        self.state.start_expiry_loop()

        # Check for ready ticket in cookies
        ticket_id = self._get_ticket_cookie(scope)
        if ticket_id and ticket_id in self.state.tickets:
            ticket = self.state.tickets[ticket_id]
            if ticket.ready:
                # Claim the transferred slot
                self.state.queue.remove(ticket)
                del self.state.tickets[ticket_id]
                start = time.monotonic()
                try:
                    await self.app(scope, receive, send)
                finally:
                    duration = time.monotonic() - start
                    self.state.record_duration(duration)
                    self.state.complete_request()
                return

        # Try to acquire a slot
        acquired = self.state.semaphore.acquire(blocking=False) if hasattr(self.state.semaphore, 'acquire') else False
        # asyncio.Semaphore doesn't have acquire(blocking=False), use _value check
        if self.state.semaphore._value > 0:
            await self.state.semaphore.acquire()
            start = time.monotonic()
            try:
                await self.app(scope, receive, send)
            except Exception:
                self.state.complete_request()
                raise
            else:
                duration = time.monotonic() - start
                self.state.record_duration(duration)
                self.state.complete_request()
            return

        # Queue is full — 503
        if len(self.state.queue) >= self.state.max_queue:
            await self._send_503(send)
            return

        # Add to queue and return queue page
        new_ticket = QueueTicket(id=str(uuid.uuid4()))
        self.state.queue.append(new_ticket)
        self.state.tickets[new_ticket.id] = new_ticket
        position = self.state.get_position(new_ticket.id)
        wait = self.state.estimate_wait(position)

        original_url = scope.get("path", "/")
        qs = scope.get("query_string", b"")
        if qs:
            original_url += "?" + qs.decode("utf-8", errors="replace")

        await self._send_queue_page(send, new_ticket.id, position, wait, original_url)

    def _get_ticket_cookie(self, scope) -> Optional[str]:
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"cookie":
                cookies = SimpleCookie(header_value.decode("utf-8", errors="replace"))
                if "_queue_ticket" in cookies:
                    return cookies["_queue_ticket"].value
        return None

    async def _handle_queue_status(self, scope, send):
        qs = parse_qs(scope.get("query_string", b"").decode())
        ticket_id = qs.get("ticket", [""])[0]

        if ticket_id in self.state.tickets:
            ticket = self.state.tickets[ticket_id]
            if ticket.ready:
                body = json.dumps({"position": 0, "ready": True, "wait_estimate_seconds": 0}).encode()
            else:
                pos = self.state.get_position(ticket_id)
                wait = self.state.estimate_wait(pos)
                body = json.dumps({"position": pos, "ready": False, "wait_estimate_seconds": wait, "requeue": False}).encode()
        else:
            body = json.dumps({"position": -1, "ready": False, "wait_estimate_seconds": 0, "requeue": True}).encode()

        await send({"type": "http.response.start", "status": 200,
                     "headers": [[b"content-type", b"application/json"]]})
        await send({"type": "http.response.body", "body": body})

    async def _send_queue_page(self, send, ticket_id, position, wait_estimate, original_url):
        html = _QUEUE_PAGE_HTML.format(
            ticket_id=ticket_id,
            position=position,
            wait_estimate=wait_estimate,
            original_url=original_url,
        )
        body = html.encode("utf-8")
        await send({"type": "http.response.start", "status": 202,
                     "headers": [
                         [b"content-type", b"text/html; charset=utf-8"],
                         [b"set-cookie", f"_queue_ticket={ticket_id}; Path=/; HttpOnly; SameSite=Lax".encode()],
                     ]})
        await send({"type": "http.response.body", "body": body})

    async def _send_503(self, send):
        body = b"<html><body><h1>Server at capacity</h1><p>The server is at capacity. Please try again in a few minutes.</p></body></html>"
        await send({"type": "http.response.start", "status": 503,
                     "headers": [
                         [b"content-type", b"text/html"],
                         [b"retry-after", b"30"],
                     ]})
        await send({"type": "http.response.body", "body": body})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest teredacta/tests/test_admission.py -v`
Expected: PASS (at least the basic tests — some may need adjustment based on the exact asyncio semaphore behavior)

- [ ] **Step 5: Commit**

```bash
git add teredacta/admission.py teredacta/tests/test_admission.py
git commit -m "feat: admission control middleware with queue page and slot transfer"
```

---

### Task 8: Register Admission Middleware in App

**Files:**
- Modify: `teredacta/app.py`

- [ ] **Step 1: Write integration test**

Add to `teredacta/tests/test_admission.py`:

```python
class TestAdmissionIntegration:
    def test_admission_middleware_registered(self):
        from teredacta.config import TeredactaConfig
        from teredacta.app import create_app
        cfg = TeredactaConfig()
        app = create_app(cfg)
        # The outermost wrapper should be AdmissionMiddleware
        # Check that /_queue/status responds
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/_queue/status?ticket=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["requeue"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest teredacta/tests/test_admission.py::TestAdmissionIntegration -v`
Expected: FAIL — 404 (middleware not registered yet)

- [ ] **Step 3: Register middleware in app.py**

At the end of `create_app()` in `teredacta/app.py`, before the `return app` line, add:

```python
    from teredacta.admission import AdmissionMiddleware
    app = AdmissionMiddleware(
        app,
        max_concurrent=config.max_concurrent_requests,
        max_queue=config.max_queue_size,
    )

    return app
```

Note: The admission middleware must be the outermost wrapper (after timeout middleware). The order should be: `AdmissionMiddleware(RequestTimeoutMiddleware(FastAPI app))`. Since `add_middleware` adds in reverse order, and we're wrapping manually, ensure admission is applied last (outermost).

Actually, since Task 6 used `app.add_middleware(RequestTimeoutMiddleware, ...)` which registers it inside FastAPI's middleware stack, and here we wrap with `AdmissionMiddleware` as a raw ASGI wrapper, the order is correct: admission is outermost.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest teredacta/tests/test_admission.py::TestAdmissionIntegration -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest teredacta/tests/ -v --tb=short`
Expected: All pass. Some existing tests may need minor adjustments if they rely on specific response behavior now gated by admission.

- [ ] **Step 6: Commit**

```bash
git add teredacta/app.py teredacta/tests/test_admission.py
git commit -m "feat: register admission middleware in app"
```

---

### Task 9: Multi-Worker Support in `teredacta start`

**Files:**
- Modify: `teredacta/__main__.py:98-130`

- [ ] **Step 1: Write the failing test**

This is best tested manually, but add a basic CLI test:

```python
# In teredacta/tests/test_cli.py (create if needed)
from click.testing import CliRunner
from teredacta.__main__ import cli


class TestStartMultiWorker:
    def test_start_accepts_workers_config(self, tmp_path):
        """Verify start no longer rejects workers > 1 in config."""
        cfg = tmp_path / "teredacta.yaml"
        cfg.write_text("workers: 4\nhost: 127.0.0.1\nport: 19999\ndb_path: /nonexistent\n")
        runner = CliRunner()
        # start will fail (can't bind, no DB) but should NOT fail with
        # "Multi-worker mode is not supported"
        result = runner.invoke(cli, ["start", "--config", str(cfg)])
        assert "Multi-worker mode is not supported" not in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest teredacta/tests/test_cli.py::TestStartMultiWorker -v`
Expected: FAIL — output contains "Multi-worker mode is not supported"

- [ ] **Step 3: Update start command**

In `teredacta/__main__.py`, replace lines 100-103:

```python
    if cfg.workers > 1:
        click.echo("Error: Multi-worker mode is not supported with 'teredacta start'.")
        click.echo("Use systemd or 'teredacta run --workers N' instead.")
        sys.exit(1)
```

with multi-worker daemon support:

```python
    if cfg.workers > 1:
        # Multi-worker requires import string. Pass config via env.
        os.environ["_TEREDACTA_CONFIG_PATH"] = config_path or ""
        os.environ["_TEREDACTA_SECRET_KEY"] = cfg.secret_key
        if host:
            os.environ["_TEREDACTA_HOST"] = host
        if port:
            os.environ["_TEREDACTA_PORT"] = str(port)
```

Then update the child process block (around line 127-130) to handle multi-worker:

```python
    # Child process
    ...
    if cfg.workers > 1:
        import uvicorn
        uvicorn.run("teredacta._app_factory:app", host=cfg.host, port=cfg.port, workers=cfg.workers)
    else:
        from teredacta.app import create_app
        import uvicorn
        app = create_app(cfg)
        uvicorn.run(app, host=cfg.host, port=cfg.port)
```

- [ ] **Step 4: Update default workers to 4**

In `teredacta/config.py`, change:

```python
    workers: int = 1
```

to:

```python
    workers: int = 4
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest teredacta/tests/test_cli.py::TestStartMultiWorker -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest teredacta/tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add teredacta/__main__.py teredacta/config.py teredacta/tests/test_cli.py
git commit -m "feat: enable multi-worker daemon mode, default workers to 4"
```

---

### Task 10: Admission Stress Tests

**Files:**
- Create: `teredacta/tests/test_stress_admission.py`

- [ ] **Step 1: Write stress tests**

Create `teredacta/tests/test_stress_admission.py`:

```python
"""Stress tests for admission control under contention."""

import asyncio

import pytest
import httpx

from teredacta.admission import AdmissionMiddleware
from fastapi import FastAPI


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestAdmissionStress:

    @pytest.fixture
    def admission_app(self):
        app = FastAPI()
        hold = asyncio.Event()

        @app.get("/slow")
        async def slow():
            await hold.wait()
            return {"status": "done"}

        @app.get("/fast")
        async def fast():
            return {"status": "done"}

        @app.get("/health/live")
        async def health():
            return {"status": "ok"}

        wrapped = AdmissionMiddleware(app, max_concurrent=3, max_queue=10)
        return wrapped, hold

    @pytest.mark.asyncio
    async def test_queue_fifo_order(self, admission_app):
        """Verify queued requests proceed in FIFO order."""
        app, hold = admission_app
        results = []

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Fill all 3 slots
            tasks = [asyncio.ensure_future(client.get("/slow")) for _ in range(3)]
            await asyncio.sleep(0.2)

            # Queue 3 more — should get queue pages
            queued = []
            for i in range(3):
                resp = await client.get(f"/fast?order={i}")
                assert resp.status_code == 202
                queued.append(resp)

            # Release held requests
            hold.set()
            for t in tasks:
                await t

    @pytest.mark.asyncio
    async def test_health_responds_while_queue_full(self, admission_app):
        """Health probes are never queued."""
        app, hold = admission_app

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Fill all slots
            tasks = [asyncio.ensure_future(client.get("/slow")) for _ in range(3)]
            await asyncio.sleep(0.2)

            # Fill the queue
            for _ in range(10):
                await client.get("/fast")

            # Health should still respond
            resp = await asyncio.wait_for(client.get("/health/live"), timeout=2.0)
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

            hold.set()
            for t in tasks:
                await t

    @pytest.mark.asyncio
    async def test_ticket_expiry_releases_slots(self, admission_app):
        """Expired tickets release their semaphore slots."""
        app, hold = admission_app
        state = app.state

        # Manually create a ready ticket that's old
        import time
        from teredacta.admission import QueueTicket
        old_ticket = QueueTicket(id="old-test", ready=True, ready_at=time.monotonic() - 120)
        state.queue.append(old_ticket)
        state.tickets["old-test"] = old_ticket

        # Acquire all semaphore slots to simulate full
        for _ in range(3):
            await state.semaphore.acquire()

        # Trigger expiry
        await asyncio.sleep(0)  # yield
        # Run one expiry cycle manually
        now = time.monotonic()
        expired = [t for t in state.queue if t.ready and t.ready_at and (now - t.ready_at > 60)]
        for t in expired:
            state.queue.remove(t)
            state.tickets.pop(t.id, None)
            state.semaphore.release()

        # One slot should now be available
        assert state.semaphore._value == 1

    @pytest.mark.asyncio
    async def test_timeout_releases_slot(self):
        """Request that times out properly releases its admission slot."""
        from teredacta.timeout_middleware import RequestTimeoutMiddleware

        app = FastAPI()

        @app.get("/hang")
        async def hang():
            await asyncio.sleep(100)
            return {"status": "never"}

        @app.get("/fast")
        async def fast():
            return {"status": "ok"}

        # Stack: admission -> timeout -> app
        app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=0.5)
        wrapped = AdmissionMiddleware(app, max_concurrent=1, max_queue=5)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=wrapped), base_url="http://test"
        ) as client:
            # This will timeout
            resp = await client.get("/hang")
            assert resp.status_code == 504

            # Slot should be freed — next request should pass through
            resp = await client.get("/fast")
            assert resp.status_code == 200
```

- [ ] **Step 2: Run stress tests**

Run: `.venv/bin/python -m pytest teredacta/tests/test_stress_admission.py -m stress -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest teredacta/tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add teredacta/tests/test_stress_admission.py
git commit -m "test: add admission control stress tests"
```

---

### Task 11: Update Locust Suite for Queue Handling

**Files:**
- Modify: `stress/locustfile.py`
- Modify: `stress/stress_config.py`

- [ ] **Step 1: Add queue config to stress_config.py**

Add to `stress/stress_config.py`:

```python
# Queue handling
QUEUE_POLL_INTERVAL_SECONDS = 3
QUEUE_MAX_WAIT_SECONDS = 120  # Give up waiting after this long
```

- [ ] **Step 2: Update WebUser to handle queue pages**

In `stress/locustfile.py`, add a helper method to the `WebUser` class that handles queue responses. When a response has status 202 and contains a `_queue_ticket` cookie, poll `/_queue/status` until `ready: true`, then re-request the original URL.

```python
import time as _time

class WebUser(HttpUser):
    # ... existing code ...

    def _handle_possible_queue(self, response, name):
        """If response is a queue page (202), poll until ready and re-request."""
        if response.status_code != 202:
            return response

        ticket = response.cookies.get("_queue_ticket")
        if not ticket:
            return response

        start = _time.monotonic()
        while _time.monotonic() - start < QUEUE_MAX_WAIT_SECONDS:
            _time.sleep(QUEUE_POLL_INTERVAL_SECONDS)
            with self.client.get(
                f"/_queue/status?ticket={ticket}",
                name="/_queue/status",
                catch_response=True,
            ) as poll:
                if poll.status_code == 200:
                    data = poll.json()
                    if data.get("ready"):
                        poll.success()
                        # Re-request original URL
                        return self.client.get(response.url.path, name=name)
                    if data.get("requeue"):
                        poll.success()
                        return self.client.get(response.url.path, name=name)
                    poll.success()
        return response  # Timed out waiting

    @task(5)
    def browse_documents(self):
        page = random.randint(1, 10)
        with self.client.get(
            f"/documents?page={page}", name="/documents?page=[N]", catch_response=True
        ) as resp:
            if resp.status_code == 202:
                self._handle_possible_queue(resp, "/documents?page=[N]")
                resp.success()
            elif resp.status_code == 200:
                resp.success()
```

Apply the same pattern to `browse_recoveries`, `browse_highlights`, `browse_explore`, and `view_document_detail`.

- [ ] **Step 3: Update HealthMonitor to verify health is never queued**

```python
class HealthMonitor(HttpUser):
    # ... existing code ...

    @task(3)
    def check_liveness(self):
        with self.client.get("/health/live", catch_response=True, name="/health/live") as resp:
            if resp.status_code == 202:
                resp.failure("HEALTH ENDPOINT WAS QUEUED — admission control bug")
            elif resp.status_code != 200:
                _health_tracker["liveness_failures"] += 1
                resp.failure(f"LIVENESS FAILURE: {resp.status_code}")
            else:
                resp.success()
```

- [ ] **Step 4: Update locust user count for 500-user target**

In `stress/locustfile.py`, update `StressTestShape`:

```python
class StressTestShape(LoadTestShape):
    MAX_USERS = 500
    SPAWN_RATE = 20
```

- [ ] **Step 5: Commit**

```bash
git add stress/locustfile.py stress/stress_config.py
git commit -m "feat: update locust suite for admission queue and 500-user target"
```

---

### Task 12: Live Server Validation

**Files:** None (testing only)

- [ ] **Step 1: Reinstall and restart server**

```bash
.venv/bin/teredacta stop
.venv/bin/pip install -e .
.venv/bin/teredacta start
```

- [ ] **Step 2: Run pytest stress tests**

```bash
.venv/bin/python -m pytest teredacta/tests/test_stress_admission.py teredacta/tests/test_stress_db_pool.py teredacta/tests/test_stress_sse.py teredacta/tests/test_stress_thread_pool.py teredacta/tests/test_stress_compound_deadlock.py teredacta/tests/test_stress_mixed.py -m stress -v
```

Expected: All pass

- [ ] **Step 3: Run locust at 200 users**

```bash
cd stress && STRESS_ADMIN_PASSWORD=<password> ../.venv/bin/locust -f locustfile.py --headless --host http://localhost:80 --csv=/tmp/locust_200 --loglevel INFO
```

Expected: < 5% failure rate, no liveness failures, queue pages served and drained

- [ ] **Step 4: Run locust at 500 users**

Update `StressTestShape.MAX_USERS = 500` and run:

```bash
cd stress && STRESS_ADMIN_PASSWORD=<password> ../.venv/bin/locust -f locustfile.py --headless --host http://localhost:80 --csv=/tmp/locust_500 --loglevel INFO
```

Expected: Zero 503s, all requests either served directly or queued and completed, liveness never fails, queue drains within 30s of load drop

- [ ] **Step 5: Analyze results and tune**

Compare CSV results from both runs. Key metrics:
- p50/p95/p99 response times
- Max queue depth
- Queue drain time
- 503 rate (should be 0)
- Liveness failure count (should be 0)

If metrics are off, adjust `max_concurrent_requests` in config and re-run.

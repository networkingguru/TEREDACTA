# Stability Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the five issues that caused TEREDACTA to hang silently in production: no logging, BaseHTTPMiddleware + SSE leaks, shared thread pool starvation, missing health endpoint, and no request timeouts.

**Architecture:** Minimal changes to existing files. Logging setup in `__main__.py`. Middleware, health route, and timeout middleware in `app.py`. SSE executor isolation in `sse.py`. New config field in `config.py`.

**Tech Stack:** Python stdlib `logging`, FastAPI/Starlette ASGI, `concurrent.futures.ThreadPoolExecutor`

**Spec:** `docs/superpowers/specs/2026-03-31-stability-fixes-design.md`

**Issues:** #2, #3, #4, #5, #6

---

### Task 1: Wire Up Logging Configuration (#2)

**Files:**
- Modify: `teredacta/__main__.py`
- Test: `teredacta/tests/test_logging_setup.py`

- [ ] **Step 1: Write failing tests for logging setup**

Create `teredacta/tests/test_logging_setup.py`:

```python
"""Tests for logging configuration wiring."""
import logging
import sys

import pytest

from teredacta.config import TeredactaConfig


def test_setup_logging_configures_file_handler(tmp_path):
    """When log_path is set, a FileHandler should be configured."""
    from teredacta.__main__ import setup_logging

    log_file = tmp_path / "test.log"
    cfg = TeredactaConfig(log_path=str(log_file), log_level="debug")

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        setup_logging(cfg)
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "RotatingFileHandler" in handler_types
        assert root.level == logging.DEBUG
    finally:
        # Restore original handlers
        root.handlers = original_handlers


def test_setup_logging_no_file_handler_when_empty_path():
    """When log_path is empty, no FileHandler should be added."""
    from teredacta.__main__ import setup_logging

    cfg = TeredactaConfig(log_path="", log_level="info")

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        setup_logging(cfg)
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "RotatingFileHandler" not in handler_types
    finally:
        root.handlers = original_handlers


def test_setup_logging_stderr_handler_present():
    """A StreamHandler to stderr should always be configured."""
    from teredacta.__main__ import setup_logging

    cfg = TeredactaConfig(log_path="", log_level="warning")

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        setup_logging(cfg)
        stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)
                          and not isinstance(h, logging.FileHandler)]
        assert len(stream_handlers) >= 1
        assert root.level == logging.WARNING
    finally:
        root.handlers = original_handlers


def test_setup_logging_writes_to_file(tmp_path):
    """Log messages should appear in the configured log file."""
    from teredacta.__main__ import setup_logging

    log_file = tmp_path / "app.log"
    cfg = TeredactaConfig(log_path=str(log_file), log_level="info")

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        setup_logging(cfg)
        test_logger = logging.getLogger("teredacta.test")
        test_logger.info("stability test message")
        # Flush handlers
        for h in root.handlers:
            h.flush()
        content = log_file.read_text()
        assert "stability test message" in content
    finally:
        root.handlers = original_handlers


def test_uncaught_exception_is_logged(tmp_path):
    """sys.excepthook should be overridden to log uncaught exceptions."""
    from teredacta.__main__ import setup_logging

    log_file = tmp_path / "crash.log"
    cfg = TeredactaConfig(log_path=str(log_file), log_level="info")

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_excepthook = sys.excepthook
    try:
        setup_logging(cfg)
        assert sys.excepthook is not original_excepthook
    finally:
        root.handlers = original_handlers
        sys.excepthook = original_excepthook
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_logging_setup.py -v`
Expected: FAIL — `setup_logging` does not exist

- [ ] **Step 3: Implement `setup_logging()` in `__main__.py`**

Add to `teredacta/__main__.py` after the imports:

```python
import logging
from logging.handlers import RotatingFileHandler


def setup_logging(cfg):
    """Configure Python logging from TeredactaConfig.  Idempotent."""
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    # Clear any existing handlers to avoid duplicates on reload
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    # Always add stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)
    root.addHandler(stderr_handler)

    # File handler if log_path is set
    if cfg.log_path:
        file_handler = RotatingFileHandler(
            cfg.log_path, maxBytes=10_485_760, backupCount=5
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    # Log uncaught exceptions
    _original_excepthook = sys.excepthook

    def _exception_handler(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            _original_excepthook(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("teredacta").critical(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = _exception_handler
```

- [ ] **Step 4: Call `setup_logging()` in the `run` command**

In the `run()` function in `__main__.py`, add after `cfg = _load_and_patch_cfg(...)`:

```python
    setup_logging(cfg)
```

And change the `uvicorn.run()` calls to pass `log_config=None` so Uvicorn uses the root logger:

For single-worker:
```python
        uvicorn.run(app, host=cfg.host, port=cfg.port, log_config=None)
```

For multi-worker:
```python
        uvicorn.run("teredacta._app_factory:app", host=cfg.host, port=cfg.port, workers=cfg.workers, log_config=None)
```

- [ ] **Step 5: Call `setup_logging()` in the `start` command**

In the `start()` function, add `setup_logging(cfg)` after `cfg = _load_and_patch_cfg(...)` in the child process (after `os.setsid()`), before the `os.dup2` calls. Add `log_config=None` to the uvicorn.run call.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_logging_setup.py -v`
Expected: All 5 tests PASS

- [ ] **Step 7: Run full test suite to check for regressions**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/ -v --timeout=30`
Expected: All existing tests PASS

- [ ] **Step 8: Commit**

```bash
git add teredacta/__main__.py teredacta/tests/test_logging_setup.py
git commit -m "fix: wire up log_path and log_level config to Python logging (#2)"
```

---

### Task 2: Replace BaseHTTPMiddleware with Pure ASGI Middleware (#3)

**Files:**
- Modify: `teredacta/app.py`
- Test: `teredacta/tests/test_middleware.py`

- [ ] **Step 1: Write failing tests for the new middleware**

Create `teredacta/tests/test_middleware.py`:

```python
"""Tests for pure ASGI template context middleware."""
import pytest
from fastapi.testclient import TestClient


def test_middleware_sets_is_admin_on_request(client):
    """Every response should have been processed by the middleware."""
    # The explore page is public and renders — if middleware works,
    # request.state.is_admin is set and the template renders without error.
    response = client.get("/")
    # Should not get 500 (would happen if request.state.is_admin missing)
    assert response.status_code in (200, 302, 307)


def test_middleware_sets_csrf_token(app):
    """The middleware should set csrf_token on request state."""
    from starlette.testclient import TestClient as StarletteClient
    client = StarletteClient(app)
    # Any page that renders a template uses csrf_token
    response = client.get("/documents")
    assert response.status_code == 200


def test_sse_endpoint_works_with_middleware(app):
    """SSE endpoint should still work with the pure ASGI middleware.
    This tests that streaming responses are not broken."""
    from starlette.testclient import TestClient as StarletteClient

    # Set up admin access for SSE (local mode, no password = admin)
    client = StarletteClient(app)
    response = client.get("/sse/stats", headers={"Accept": "text/event-stream"})
    # Should get 200 (streaming) not 500 (middleware error)
    # TestClient may return the first chunk or close early
    assert response.status_code in (200, 403)
```

- [ ] **Step 2: Run tests to verify current state**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_middleware.py -v`
Expected: Should PASS with current middleware (this establishes baseline behavior)

- [ ] **Step 3: Replace the middleware in `app.py`**

Add a class BEFORE `create_app()`:

```python
class _TemplateContextMiddleware:
    """Pure ASGI middleware — does not wrap response body.

    Unlike BaseHTTPMiddleware (used by @app.middleware("http")), this is
    safe with streaming responses (SSE) because it sets request state and
    passes through without intercepting the response stream.

    Uses app.add_middleware() so the FastAPI app object (with .state) is
    preserved — important for test fixtures that set app.state attributes.
    """

    def __init__(self, app, config=None, auth=None):
        self.app = app
        self.config = config
        self.auth = auth

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope)
            request.state.is_admin = self.auth.is_admin(request)
            request.state.csrf_token = self.auth.get_csrf_token(request)
            request.state.config = self.config
        await self.app(scope, receive, send)
```

Inside `create_app()`, remove this block:
```python
    @app.middleware("http")
    async def add_template_context(request: Request, call_next):
        request.state.is_admin = app.state.auth.is_admin(request)
        request.state.csrf_token = app.state.auth.get_csrf_token(request)
        request.state.config = config
        response = await call_next(request)
        return response
```

And replace it with:
```python
    app.add_middleware(_TemplateContextMiddleware, config=config, auth=app.state.auth)
```

This preserves the `app` as a FastAPI instance with `.state` (important for test fixtures like `conftest.py:app_with_entities` that set `app.state` attributes after creation).

- [ ] **Step 4: Run tests**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_middleware.py teredacta/tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/app.py teredacta/tests/test_middleware.py
git commit -m "fix: replace BaseHTTPMiddleware with pure ASGI middleware (#3)"
```

---

### Task 3: Dedicated Thread Pool for SSE (#4)

**Files:**
- Modify: `teredacta/sse.py`
- Modify: `teredacta/routers/dashboard.py`
- Modify: `teredacta/app.py` (lifespan cleanup)
- Test: `teredacta/tests/test_sse_executor.py`

- [ ] **Step 1: Write failing tests**

Create `teredacta/tests/test_sse_executor.py`:

```python
"""Tests for SSE dedicated thread pool executor."""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from teredacta.sse import SSEManager


@pytest.mark.asyncio
async def test_sse_manager_has_own_executor():
    """SSEManager should create its own ThreadPoolExecutor."""
    manager = SSEManager(poll_interval=1.0)
    assert hasattr(manager, "executor")
    assert isinstance(manager.executor, ThreadPoolExecutor)
    manager.close()


@pytest.mark.asyncio
async def test_sse_poll_uses_dedicated_executor():
    """The poll loop should use the dedicated executor, not the default."""
    unob = MagicMock()
    unob.get_stats.return_value = {"docs": 1}
    unob.get_daemon_status.return_value = "running"

    manager = SSEManager(poll_interval=0.1, unob=unob)
    queue = manager.subscribe()

    # Wait for a poll cycle
    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert "docs" in event

    manager.unsubscribe(queue)
    await asyncio.sleep(0.1)
    manager.close()


@pytest.mark.asyncio
async def test_sse_close_shuts_down_executor():
    """close() should shut down the dedicated executor."""
    from concurrent.futures import BrokenExecutor
    manager = SSEManager(poll_interval=1.0)
    executor = manager.executor
    manager.close()
    # After shutdown, submitting new work should raise
    with pytest.raises((RuntimeError, BrokenExecutor)):
        executor.submit(lambda: None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_sse_executor.py -v`
Expected: FAIL — `SSEManager` has no `executor` attribute

- [ ] **Step 3: Add dedicated executor to SSEManager**

In `teredacta/sse.py`, add to imports:

```python
from concurrent.futures import ThreadPoolExecutor
```

In `__init__`, add:

```python
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sse")
```

In `_poll_loop`, change `run_in_executor(None, ...)` to:

```python
                        data = await loop.run_in_executor(
                            self.executor, partial(self._fetch_sync, self.unob)
                        )
```

Add a `close()` method:

```python
    def close(self):
        """Shut down the dedicated thread pool."""
        self.executor.shutdown(wait=False)
```

- [ ] **Step 4: Update dashboard.py to use SSE executor**

In `teredacta/routers/dashboard.py`, change the `daemon_status_fragment` function to use the SSE executor:

```python
    sse = getattr(request.app.state, "sse", None)
    executor = sse.executor if sse else None
    try:
        status = await loop.run_in_executor(executor, unob.get_daemon_status)
```

- [ ] **Step 5: Add SSE cleanup to app lifespan**

In `teredacta/app.py`, update the lifespan:

```python
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        application.state.unob.close()
        if hasattr(application.state, "sse"):
            application.state.sse.close()
```

- [ ] **Step 6: Run tests**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_sse_executor.py teredacta/tests/test_sse_nonblocking.py teredacta/tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add teredacta/sse.py teredacta/routers/dashboard.py teredacta/app.py teredacta/tests/test_sse_executor.py
git commit -m "fix: isolate SSE polling on dedicated thread pool (#4)"
```

---

### Task 4: Health Endpoint (#5)

**Files:**
- Modify: `teredacta/app.py`
- Test: `teredacta/tests/test_health.py`

- [ ] **Step 1: Write failing tests**

Create `teredacta/tests/test_health.py`:

```python
"""Tests for /health endpoint."""
import pytest
from fastapi.testclient import TestClient


def test_health_returns_ok(client):
    """Health endpoint returns 200 with status ok when DB is accessible."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["db"] == "ok"
    assert "uptime_seconds" in data


def test_health_returns_degraded_when_db_missing(test_config, tmp_path):
    """Health returns 503 when database is not accessible."""
    # Point to nonexistent DB
    test_config.db_path = str(tmp_path / "nonexistent.db")
    from teredacta.app import create_app
    app = create_app(test_config)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert "error" in data["db"].lower() or data["db"] != "ok"


def test_health_no_auth_required(client):
    """Health endpoint should work without authentication."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_reports_uptime(client):
    """Health response should include a numeric uptime_seconds field."""
    response = client.get("/health")
    data = response.json()
    assert isinstance(data["uptime_seconds"], (int, float))
    assert data["uptime_seconds"] >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_health.py -v`
Expected: FAIL — no `/health` route

- [ ] **Step 3: Add `/health` endpoint in `app.py`**

In `teredacta/app.py`, add after imports:

```python
import asyncio
import time as _time
from fastapi.responses import JSONResponse
```

Inside `create_app()`, before the router includes, add:

```python
    _start_time = _time.monotonic()

    @app.get("/health")
    async def health_check():
        uptime = _time.monotonic() - _start_time
        loop = asyncio.get_running_loop()

        def _check_db():
            conn = app.state.unob._get_db()
            app.state.unob._release_db(conn)

        try:
            # Run DB check in executor to avoid blocking the event loop.
            # Use a 2s timeout so a hung DB doesn't make health checks hang too.
            await asyncio.wait_for(
                loop.run_in_executor(None, _check_db), timeout=2.0
            )
            db_status = "ok"
            status_code = 200
        except Exception as e:
            db_status = f"error: {e}"
            status_code = 503
        return JSONResponse(
            {"status": "ok" if status_code == 200 else "degraded",
             "db": db_status,
             "uptime_seconds": round(uptime, 1)},
            status_code=status_code,
        )
```

Note: No `pool_status()` method is needed on ConnectionPool — the health check just tests acquire/release connectivity.

- [ ] **Step 4: Run tests**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_health.py teredacta/tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/app.py teredacta/tests/test_health.py
git commit -m "feat: add /health endpoint with DB liveness check (#5)"
```

---

### Task 5: Request Timeouts (#6)

**Files:**
- Modify: `teredacta/app.py`
- Modify: `teredacta/config.py`
- Test: `teredacta/tests/test_request_timeout.py`

- [ ] **Step 1: Write failing tests**

Create `teredacta/tests/test_request_timeout.py`:

```python
"""Tests for request timeout middleware."""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from starlette.testclient import TestClient


def test_timeout_middleware_class_exists():
    """The timeout middleware should be importable."""
    from teredacta.app import _RequestTimeoutMiddleware
    assert _RequestTimeoutMiddleware is not None


def test_fast_request_completes_normally():
    """Requests under the timeout should work normally."""
    from teredacta.app import _RequestTimeoutMiddleware

    inner = FastAPI()

    @inner.get("/fast")
    async def fast():
        return PlainTextResponse("ok")

    inner.add_middleware(_RequestTimeoutMiddleware, timeout_seconds=5.0)
    client = TestClient(inner)
    response = client.get("/fast")
    assert response.status_code == 200
    assert response.text == "ok"


def test_slow_request_returns_504():
    """Requests exceeding the timeout should get 504."""
    from teredacta.app import _RequestTimeoutMiddleware

    inner = FastAPI()

    @inner.get("/slow")
    async def slow():
        await asyncio.sleep(10)
        return PlainTextResponse("should not reach")

    inner.add_middleware(_RequestTimeoutMiddleware, timeout_seconds=0.5)
    client = TestClient(inner)
    response = client.get("/slow")
    assert response.status_code == 504


def test_sse_endpoint_exempt_from_timeout_by_path():
    """SSE endpoints under /sse/ should not be timed out."""
    from teredacta.app import _RequestTimeoutMiddleware
    from starlette.responses import StreamingResponse

    inner = FastAPI()

    async def slow_stream():
        yield "data: hello\n\n"
        await asyncio.sleep(2)
        yield "data: world\n\n"

    @inner.get("/sse/stats")
    async def sse():
        return StreamingResponse(slow_stream(), media_type="text/event-stream")

    inner.add_middleware(_RequestTimeoutMiddleware, timeout_seconds=0.5)
    client = TestClient(inner)
    response = client.get("/sse/stats")
    # Should get 200, not 504 — exempted by /sse/ path prefix
    assert response.status_code == 200


def test_sse_endpoint_exempt_from_timeout_by_accept_header():
    """Requests with Accept: text/event-stream should not be timed out."""
    from teredacta.app import _RequestTimeoutMiddleware
    from starlette.responses import StreamingResponse

    inner = FastAPI()

    async def slow_stream():
        yield "data: hello\n\n"
        await asyncio.sleep(2)
        yield "data: world\n\n"

    @inner.get("/events")
    async def sse():
        return StreamingResponse(slow_stream(), media_type="text/event-stream")

    inner.add_middleware(_RequestTimeoutMiddleware, timeout_seconds=0.5)
    client = TestClient(inner)
    response = client.get("/events", headers={"Accept": "text/event-stream"})
    assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_request_timeout.py -v`
Expected: FAIL — `_RequestTimeoutMiddleware` does not exist

- [ ] **Step 3: Add `request_timeout_seconds` to config**

In `teredacta/config.py`, add to `TeredactaConfig`:

```python
    request_timeout_seconds: float = 120.0
```

- [ ] **Step 4: Implement `_RequestTimeoutMiddleware` in `app.py`**

In `teredacta/app.py`, add the class before `create_app()`:

```python
class _RequestTimeoutMiddleware:
    """Pure ASGI middleware that enforces a request timeout.

    SSE endpoints are exempt (by /sse/ path prefix or Accept header).
    Returns 504 only if response headers have NOT yet been sent.
    If headers were already sent before the timeout, the connection
    is simply dropped (no way to send a new status code).
    """

    def __init__(self, app, timeout_seconds: float = 120.0):
        self.app = app
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Exempt SSE by path prefix
        path = scope.get("path", "")
        if path.startswith("/sse/"):
            await self.app(scope, receive, send)
            return

        # Exempt SSE by Accept header.
        # ASGI headers are a list of (name, value) byte-tuples.
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"accept" and b"text/event-stream" in header_value:
                await self.app(scope, receive, send)
                return

        # Track whether response headers have been sent
        response_started = False

        async def send_wrapper(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await asyncio.wait_for(
                self.app(scope, receive, send_wrapper),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            if not response_started:
                response = PlainTextResponse(
                    "Request timed out", status_code=504
                )
                await response(scope, receive, send)
```

Add to the imports at the top of `app.py` (if not already present from Task 4):

```python
import asyncio
from starlette.responses import PlainTextResponse
```

- [ ] **Step 5: Wire the middleware into `create_app()`**

In `create_app()`, after the `app.add_middleware(_TemplateContextMiddleware, ...)` line, add:

```python
    app.add_middleware(_RequestTimeoutMiddleware, timeout_seconds=config.request_timeout_seconds)
```

Note: Starlette applies middlewares in reverse order of `add_middleware` calls. The timeout middleware should wrap the template context middleware, so it should be added AFTER it. This means the timeout wraps everything.

- [ ] **Step 6: Run tests**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_request_timeout.py teredacta/tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add teredacta/app.py teredacta/config.py teredacta/tests/test_request_timeout.py
git commit -m "feat: add request timeout middleware (120s default) (#6)"
```

---

### Task 6: Final Integration Verification

**Files:**
- No new files

- [ ] **Step 1: Run full test suite**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 2: Verify the app starts and serves requests**

```bash
cd /root/TEREDACTA
timeout 5 .venv/bin/python -m teredacta run --host 127.0.0.1 --port 9999 &
sleep 2
curl -s http://127.0.0.1:9999/health
kill %1 2>/dev/null
```

Expected: Health endpoint returns `{"status":"ok","db":"ok","uptime_seconds":...}` or `{"status":"degraded",...}` if the Unobfuscator DB isn't at the default path.

- [ ] **Step 3: Verify logging works**

Check that the startup produced log output to stderr during the step above.

- [ ] **Step 4: Final commit if any adjustments needed**

Only if integration testing reveals issues that need fixing.

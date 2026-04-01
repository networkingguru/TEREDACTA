# Stress Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a comprehensive stress test suite to verify TEREDACTA's stability under load, including a health endpoint for monitoring.

**Architecture:** Health endpoint (`/health/live` and `/health/ready`) built into the app with public pool/SSE metrics. Pytest stress tests for CI-runnable regression checks targeting specific failure modes (DB pool contention, SSE saturation, thread pool exhaustion, compound deadlock). Locust load tests for realistic sustained load against a live server.

**Tech Stack:** FastAPI, pytest, pytest-timeout, httpx (async client), locust, sseclient-py

**Spec:** `docs/superpowers/specs/2026-04-01-stress-test-suite-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|---|---|
| `teredacta/routers/health.py` | `/health/live` and `/health/ready` endpoints |
| `teredacta/tests/test_health.py` | Health endpoint unit tests |
| `teredacta/tests/test_stress_db_pool.py` | DB pool contention stress tests |
| `teredacta/tests/test_stress_sse.py` | SSE saturation stress tests |
| `teredacta/tests/test_stress_thread_pool.py` | Thread pool exhaustion stress tests |
| `teredacta/tests/test_stress_compound_deadlock.py` | Production failure mode reproduction |
| `teredacta/tests/test_stress_mixed.py` | Combined workload stress tests |
| `stress/locustfile.py` | Locust user classes, LoadTestShape, and load test scenarios |
| `stress/stress_config.py` | Locust configuration (target URL, credentials, thresholds) |
| `stress/README.md` | How to run stress tests locally and against VPS |

### Modified Files
| File | Change |
|---|---|
| `teredacta/db_pool.py` | Add `pool_status()` method returning `{"idle": N, "in_use": N, "capacity": N}` |
| `teredacta/unob.py` | Add public `pool_status()` method delegating to `ConnectionPool` |
| `teredacta/sse.py` | Add `subscriber_count` property |
| `teredacta/app.py` | Mount health router, record startup time, add log filter |
| `teredacta/config.py` | Add `health_pool_degraded_threshold` and `health_sse_degraded_threshold` fields |
| `pyproject.toml` | Add `stress` optional deps, `pytest-timeout` to dev deps, pytest markers config |
| `deploy/README.md` | Add Caddy health check config |

---

### Task 1: Add pool_status() to ConnectionPool and UnobInterface

**Files:**
- Modify: `teredacta/db_pool.py:10-31`
- Modify: `teredacta/unob.py:89-139`
- Test: `teredacta/tests/test_health.py` (created in Task 2)

- [ ] **Step 1: Write the failing test**

Create `teredacta/tests/test_health.py`:

```python
"""Tests for health endpoint and pool_status."""

import sqlite3
import threading
import time

import pytest

from teredacta.db_pool import ConnectionPool


class TestPoolStatus:
    def test_pool_status_empty_pool(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        pool = ConnectionPool(str(db), max_size=4)
        status = pool.pool_status()
        assert status == {"idle": 0, "in_use": 0, "capacity": 4}
        pool.close()

    def test_pool_status_one_acquired(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        pool = ConnectionPool(str(db), max_size=4)
        conn = pool.acquire()
        status = pool.pool_status()
        assert status == {"idle": 0, "in_use": 1, "capacity": 4}
        pool.release(conn)
        pool.close()

    def test_pool_status_acquire_and_release(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        pool = ConnectionPool(str(db), max_size=4)
        conn = pool.acquire()
        pool.release(conn)
        status = pool.pool_status()
        assert status == {"idle": 1, "in_use": 0, "capacity": 4}
        pool.close()

    def test_pool_status_fully_acquired(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        pool = ConnectionPool(str(db), max_size=2)
        c1 = pool.acquire()
        c2 = pool.acquire()
        status = pool.pool_status()
        assert status == {"idle": 0, "in_use": 2, "capacity": 2}
        pool.release(c1)
        pool.release(c2)
        pool.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest teredacta/tests/test_health.py::TestPoolStatus -v`
Expected: FAIL with `AttributeError: 'ConnectionPool' object has no attribute 'pool_status'`

- [ ] **Step 3: Implement pool_status() on ConnectionPool**

Add to `teredacta/db_pool.py` after the `close()` method (after line 89):

```python
    def pool_status(self) -> dict:
        """Return pool metrics without acquiring a connection.

        Reads _size and _pool.qsize() which are approximate under
        contention (CPython GIL makes individual reads atomic, but the
        pair is not a snapshot). Acceptable for health monitoring.
        """
        idle = self._pool.qsize()
        size = self._size
        return {"idle": idle, "in_use": max(0, size - idle), "capacity": self._max_size}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest teredacta/tests/test_health.py::TestPoolStatus -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Add pool_status() to UnobInterface**

Add to `teredacta/unob.py` after `_release_db` method (find `def _release_db` and add after that method):

```python
    def pool_status(self) -> dict | None:
        """Return DB pool metrics, or None if pool not yet initialized."""
        if self._pool is None:
            return None
        return self._pool.pool_status()
```

- [ ] **Step 6: Commit**

```bash
git add teredacta/db_pool.py teredacta/unob.py teredacta/tests/test_health.py
git commit -m "feat: add pool_status() to ConnectionPool and UnobInterface"
```

---

### Task 2: Add subscriber_count to SSEManager

**Files:**
- Modify: `teredacta/sse.py:11-17`
- Test: `teredacta/tests/test_health.py`

- [ ] **Step 1: Write the failing test**

Append to `teredacta/tests/test_health.py`:

```python
import asyncio
from teredacta.sse import SSEManager


class TestSSESubscriberCount:
    """Tests must be async because SSEManager.subscribe() calls asyncio.create_task()."""

    @pytest.mark.asyncio
    async def test_subscriber_count_zero(self):
        sse = SSEManager(poll_interval=1.0, unob=None)
        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_subscriber_count_after_subscribe(self):
        sse = SSEManager(poll_interval=1.0, unob=None)
        q = sse.subscribe()
        assert sse.subscriber_count == 1
        sse.unsubscribe(q)
        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_subscriber_count_multiple(self):
        sse = SSEManager(poll_interval=1.0, unob=None)
        q1 = sse.subscribe()
        q2 = sse.subscribe()
        assert sse.subscriber_count == 2
        sse.unsubscribe(q1)
        assert sse.subscriber_count == 1
        sse.unsubscribe(q2)
        assert sse.subscriber_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest teredacta/tests/test_health.py::TestSSESubscriberCount -v`
Expected: FAIL with `AttributeError: 'SSEManager' object has no attribute 'subscriber_count'`

- [ ] **Step 3: Implement subscriber_count property on SSEManager**

Add to `teredacta/sse.py` after `__init__` (after line 17):

```python
    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest teredacta/tests/test_health.py::TestSSESubscriberCount -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/sse.py teredacta/tests/test_health.py
git commit -m "feat: add subscriber_count property to SSEManager"
```

---

### Task 3: Add health config fields

**Files:**
- Modify: `teredacta/config.py:14-33`
- Test: `teredacta/tests/test_health.py`

- [ ] **Step 1: Write the failing test**

Append to `teredacta/tests/test_health.py`:

```python
from teredacta.config import TeredactaConfig


class TestHealthConfig:
    def test_default_health_thresholds(self):
        cfg = TeredactaConfig()
        assert cfg.health_pool_degraded_threshold == 3
        assert cfg.health_sse_degraded_threshold == 20

    def test_custom_health_thresholds(self):
        cfg = TeredactaConfig(
            health_pool_degraded_threshold=5,
            health_sse_degraded_threshold=50,
        )
        assert cfg.health_pool_degraded_threshold == 5
        assert cfg.health_sse_degraded_threshold == 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest teredacta/tests/test_health.py::TestHealthConfig -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'health_pool_degraded_threshold'`

- [ ] **Step 3: Add config fields**

Add to `teredacta/config.py` in the `TeredactaConfig` dataclass, after `subprocess_timeout_seconds` (line 29):

```python
    health_pool_degraded_threshold: int = 3  # idle+uncreated <= this = degraded
    health_sse_degraded_threshold: int = 20  # subscribers >= this = degraded
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest teredacta/tests/test_health.py::TestHealthConfig -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/config.py teredacta/tests/test_health.py
git commit -m "feat: add health threshold config fields"
```

---

### Task 4: Implement health router

**Files:**
- Create: `teredacta/routers/health.py`
- Modify: `teredacta/app.py:48-66`
- Test: `teredacta/tests/test_health.py`

- [ ] **Step 1: Write the failing tests**

Append to `teredacta/tests/test_health.py`:

```python
from fastapi.testclient import TestClient


class TestHealthEndpoints:
    @pytest.fixture
    def health_client(self, tmp_path):
        """Create a test client with a real DB for health tests."""
        db_path = tmp_path / "test.db"
        sqlite3.connect(str(db_path)).close()

        cfg = TeredactaConfig(
            unobfuscator_path=str(tmp_path),
            unobfuscator_bin="echo",
            db_path=str(db_path),
            pdf_cache_dir=str(tmp_path / "pdf_cache"),
            output_dir=str(tmp_path / "output"),
            log_path=str(tmp_path / "unobfuscator.log"),
            host="127.0.0.1",
            port=8000,
        )
        (tmp_path / "pdf_cache").mkdir(exist_ok=True)
        (tmp_path / "output").mkdir(exist_ok=True)
        (tmp_path / "unobfuscator.log").touch()

        from teredacta.app import create_app
        app = create_app(cfg)
        return TestClient(app)

    def test_liveness_returns_ok(self, health_client):
        resp = health_client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_readiness_healthy_before_any_queries(self, health_client):
        resp = health_client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_readiness_includes_details_from_localhost(self, health_client):
        resp = health_client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        # localhost gets full details
        assert "checks" in data
        assert "db_pool" in data["checks"]
        assert "sse" in data["checks"]
        assert "uptime_seconds" in data["checks"]
        assert "worker_pid" in data

    def test_readiness_pool_none_is_healthy(self, health_client):
        # Before any DB query, pool is None — should be healthy
        resp = health_client.get("/health/ready")
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["checks"]["db_pool"]["status"] == "ok"

    def test_readiness_returns_503_when_unhealthy(self, health_client):
        # Force unhealthy by exhausting the pool
        app = health_client.app
        unob = app.state.unob
        # Trigger pool creation and exhaust all 8 connections
        conns = []
        for _ in range(8):
            conns.append(unob._get_db())
        resp = health_client.get("/health/ready")
        assert resp.status_code == 503  # 0 available = unhealthy
        data = resp.json()
        assert data["status"] == "unhealthy"
        assert data["checks"]["db_pool"]["idle"] == 0
        assert data["checks"]["db_pool"]["in_use"] == 8
        # Release
        for c in conns:
            unob._release_db(c)

    def test_liveness_works_when_readiness_unhealthy(self, health_client):
        """Liveness probe returns 200 even when readiness is unhealthy."""
        app = health_client.app
        unob = app.state.unob
        # Exhaust pool to make readiness unhealthy
        conns = [unob._get_db() for _ in range(8)]
        # Readiness should be 503
        assert health_client.get("/health/ready").status_code == 503
        # Liveness should still be 200
        resp = health_client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        for c in conns:
            unob._release_db(c)

    def test_readiness_timeout_returns_503(self, health_client):
        """If readiness checks hang beyond 1 second, return 503."""
        import asyncio
        from unittest.mock import patch

        async def slow_checks(*args, **kwargs):
            await asyncio.sleep(5)  # Will exceed 1s timeout

        with patch("teredacta.routers.health._readiness_checks", slow_checks):
            resp = health_client.get("/health/ready")
            assert resp.status_code == 503
            assert resp.json()["status"] == "unhealthy"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest teredacta/tests/test_health.py::TestHealthEndpoints -v`
Expected: FAIL (404 — `/health/live` route does not exist)

- [ ] **Step 3: Create the health router**

Create `teredacta/routers/health.py`:

```python
"""Health check endpoints for liveness and readiness probes."""

import asyncio
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/live")
async def liveness():
    return {"status": "ok"}


@router.get("/ready")
async def readiness(request: Request):
    try:
        result = await asyncio.wait_for(_readiness_checks(request), timeout=1.0)
        return result
    except asyncio.TimeoutError:
        return JSONResponse({"status": "unhealthy"}, status_code=503)


async def _readiness_checks(request: Request) -> JSONResponse:
    config = request.app.state.config
    unob = request.app.state.unob
    sse = getattr(request.app.state, "sse", None)
    # request.client can be None behind some reverse proxy configs
    client_host = getattr(request.client, "host", None) if request.client else None
    is_local = client_host in ("127.0.0.1", "localhost", "::1", "testclient")
    is_admin = getattr(request.state, "is_admin", False)
    show_details = is_local or is_admin

    # DB pool check
    pool_data = unob.pool_status()
    if pool_data is None:
        # Pool not yet initialized — no queries made yet, healthy
        pool_check = {"status": "ok", "idle": 0, "in_use": 0, "capacity": 0}
    else:
        # available = idle connections + uncreated slots
        available = pool_data["capacity"] - pool_data["in_use"]
        if available >= config.health_pool_degraded_threshold:
            pool_status = "ok"
        elif available >= 1:
            pool_status = "degraded"
        else:
            pool_status = "error"
        pool_check = {"status": pool_status, **pool_data}

    # SSE check
    sub_count = sse.subscriber_count if sse else 0
    sse_degraded = config.health_sse_degraded_threshold
    sse_unhealthy = sse_degraded * 5  # 100 by default
    if sub_count >= sse_unhealthy:
        sse_status = "error"
    elif sub_count >= sse_degraded:
        sse_status = "degraded"
    else:
        sse_status = "ok"
    sse_check = {"status": sse_status, "subscribers": sub_count}

    # Overall status
    statuses = [pool_check["status"], sse_check["status"]]
    if "error" in statuses:
        overall = "unhealthy"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    status_code = 503 if overall == "unhealthy" else 200

    if show_details:
        body = {
            "status": overall,
            "worker_pid": os.getpid(),
            "checks": {
                "db_pool": pool_check,
                "sse": sse_check,
                "uptime_seconds": round(time.monotonic() - request.app.state.startup_time, 1),
            },
        }
    else:
        body = {"status": overall}

    return JSONResponse(body, status_code=status_code)
```

- [ ] **Step 4: Mount health router in app.py**

Add to `teredacta/app.py` after the existing router imports (after line 48), add the health router import and mount. In the import line, add `health` to the imports:

Change the import line from:
```python
    from teredacta.routers import dashboard, documents, groups, recoveries, pdf, queue, summary, admin, explore, highlights, api
```
to:
```python
    from teredacta.routers import dashboard, documents, groups, recoveries, pdf, queue, summary, admin, explore, highlights, api, health
```

And add the mount and startup time after the SSE router mount (after line 51):
```python
    app.include_router(health.router, prefix="/health")
    app.state.startup_time = time.monotonic()
```

Also add `import time` to the top of `app.py` (after `import logging`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest teredacta/tests/test_health.py::TestHealthEndpoints -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add teredacta/routers/health.py teredacta/app.py teredacta/tests/test_health.py
git commit -m "feat: add /health/live and /health/ready endpoints"
```

---

### Task 5: Add Uvicorn access log filter for health endpoints

**Files:**
- Modify: `teredacta/app.py`
- Test: Manual verification (log filter is Uvicorn-level, not easily unit-testable)

- [ ] **Step 1: Add log filter to app.py**

Add at the top of `teredacta/app.py` after existing imports (after line 8):

```python
class _HealthLogFilter(logging.Filter):
    """Suppress access log entries for /health/* requests."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if " /health/" in msg:
            return False
        return True
```

Add inside `create_app()`, before the middleware definition (before line 40). Guard against accumulation from repeated `create_app()` calls in tests:

```python
    _access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _HealthLogFilter) for f in _access_logger.filters):
        _access_logger.addFilter(_HealthLogFilter())
```

- [ ] **Step 2: Run existing tests to verify nothing broke**

Run: `pytest teredacta/tests/test_health.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add teredacta/app.py
git commit -m "feat: suppress health endpoint access log noise"
```

---

### Task 6: Update pyproject.toml with dependencies and pytest config

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add stress optional deps and pytest-timeout**

In `pyproject.toml`, change the `[project.optional-dependencies]` section from:
```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "httpx>=0.25.0",
]
```
to:
```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pytest-timeout>=2.2.0",
    "httpx>=0.25.0",
]
stress = [
    "locust>=2.20.0",
    "sseclient-py>=1.8.0",
]
```

- [ ] **Step 2: Add pytest marker configuration**

Append to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
    "stress: stress tests (deselected by default, run with: pytest -m stress)",
]
addopts = "-m 'not stress'"
asyncio_mode = "strict"
```

- [ ] **Step 3: Install updated deps**

Run: `pip install -e ".[dev]"`

- [ ] **Step 4: Run existing tests to verify config doesn't break them**

Run: `pytest teredacta/tests/test_health.py -v`
Expected: All tests PASS (stress-marked tests would be skipped if any existed)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add stress test deps, pytest-timeout, and marker config"
```

---

### Task 7: Stress test — DB pool contention

**Files:**
- Create: `teredacta/tests/test_stress_db_pool.py`

- [ ] **Step 1: Write the stress tests**

Create `teredacta/tests/test_stress_db_pool.py`:

```python
"""Stress tests for DB connection pool under contention."""

import sqlite3
import threading
import time

import pytest

from teredacta.db_pool import ConnectionPool


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestDBPoolContention:
    @pytest.fixture
    def stress_db(self, tmp_path):
        """Create a DB with enough data for non-trivial queries."""
        db_path = tmp_path / "stress.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE documents ("
            "id TEXT PRIMARY KEY, source TEXT, extracted_text TEXT, "
            "text_processed BOOLEAN DEFAULT 0, pdf_processed BOOLEAN DEFAULT 0, "
            "original_filename TEXT, page_count INTEGER, size_bytes INTEGER)"
        )
        # Insert 100k rows for meaningful query pressure
        rows = [
            (f"doc-{i}", f"source-{i % 10}", f"text content for document {i} " * 50,
             i % 3 == 0, i % 5 == 0, f"file_{i}.pdf", (i % 20) + 1, (i % 1000) * 1024)
            for i in range(100_000)
        ]
        conn.executemany(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
        conn.commit()
        conn.close()
        return db_path

    @pytest.fixture
    def pool(self, stress_db):
        p = ConnectionPool(str(stress_db), max_size=8, read_only=True)
        yield p
        p.close()

    def test_50_threads_no_deadlock(self, pool, stress_db):
        """50 threads compete for 8 connections — all must complete."""
        results = []
        errors = []

        def worker(thread_id):
            try:
                conn = pool.acquire(timeout=10.0)
                try:
                    # Simulate a non-trivial query
                    row = conn.execute(
                        "SELECT COUNT(*) FROM documents WHERE extracted_text LIKE ?",
                        (f"%document {thread_id % 100}%",),
                    ).fetchone()
                    results.append((thread_id, row[0]))
                finally:
                    pool.release(conn)
            except TimeoutError:
                results.append((thread_id, "timeout"))
            except Exception as e:
                errors.append((thread_id, str(e)))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # All threads must have completed (not hung)
        assert len(results) + len(errors) == 50, (
            f"Only {len(results) + len(errors)}/50 threads completed"
        )
        assert not errors, f"Unexpected errors: {errors}"

    def test_pool_recovers_after_burst(self, pool, stress_db):
        """After a burst of contention, pool returns to normal."""
        # Phase 1: burst — hold all connections for 1 second
        held = []
        for _ in range(8):
            held.append(pool.acquire(timeout=5.0))

        status_during = pool.pool_status()
        assert status_during["idle"] == 0
        assert status_during["in_use"] == 8

        # Release all
        for conn in held:
            pool.release(conn)

        # Phase 2: verify recovery
        status_after = pool.pool_status()
        assert status_after["idle"] == 8
        assert status_after["in_use"] == 0

        # New acquire should succeed instantly
        conn = pool.acquire(timeout=1.0)
        pool.release(conn)

    def test_timeout_error_no_leak(self, pool, stress_db):
        """TimeoutError on acquire does not leak connections."""
        # Hold all 8
        held = []
        for _ in range(8):
            held.append(pool.acquire(timeout=5.0))

        # Short-timeout acquire should raise TimeoutError
        with pytest.raises(TimeoutError):
            pool.acquire(timeout=0.5)

        # Pool status should still show 8 in use (not 9)
        status = pool.pool_status()
        assert status["in_use"] == 8
        assert status["capacity"] == 8

        for conn in held:
            pool.release(conn)

        # After release, all 8 should be idle
        status = pool.pool_status()
        assert status["idle"] == 8
```

- [ ] **Step 2: Run to verify tests pass (they test real behavior)**

Run: `pytest -m stress teredacta/tests/test_stress_db_pool.py -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Commit**

```bash
git add teredacta/tests/test_stress_db_pool.py
git commit -m "test: add DB pool contention stress tests"
```

---

### Task 8: Stress test — SSE saturation

**Files:**
- Create: `teredacta/tests/test_stress_sse.py`

- [ ] **Step 1: Write the stress tests**

Create `teredacta/tests/test_stress_sse.py`:

```python
"""Stress tests for SSE connection saturation and cleanup."""

import asyncio

import pytest

from teredacta.sse import SSEManager


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestSSESaturation:
    """All tests are async because SSEManager.subscribe() calls asyncio.create_task()."""

    @pytest.mark.asyncio
    async def test_200_subscribers_no_leak(self):
        """Open 200 subscribers, unsubscribe all, verify cleanup."""
        sse = SSEManager(poll_interval=1.0, unob=None)
        queues = [sse.subscribe() for _ in range(200)]
        assert sse.subscriber_count == 200

        for q in queues:
            sse.unsubscribe(q)
        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_ungraceful_disconnect_cleanup_via_poll_loop(self):
        """Abandoned queues are cleaned up by the real _poll_loop broadcast."""
        from unittest.mock import MagicMock

        # Create a mock unob that returns changing stats each call
        mock_unob = MagicMock()
        call_count = 0
        def changing_stats():
            nonlocal call_count
            call_count += 1
            return {"total_documents": call_count}
        def changing_daemon():
            return "running"
        mock_unob.get_stats = changing_stats
        mock_unob.get_daemon_status = changing_daemon

        sse = SSEManager(poll_interval=0.01, unob=mock_unob)

        # Subscribe 10 queues — 5 active (we drain), 5 abandoned
        active_queues = []
        abandoned_queues = []
        for i in range(10):
            q = sse.subscribe()
            if i < 5:
                active_queues.append(q)
            else:
                abandoned_queues.append(q)

        assert sse.subscriber_count == 10

        # Let the real poll loop run and broadcast events.
        # Drain active queues so they don't fill up.
        # Abandoned queues will fill (maxsize=100) and get evicted.
        for _ in range(150):
            await asyncio.sleep(0.02)
            for q in active_queues:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass

        # Abandoned queues should have been evicted by _poll_loop
        assert sse.subscriber_count == 5

        for q in active_queues:
            sse.unsubscribe(q)
        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_rapid_connect_disconnect_cycle(self):
        """1000 rapid subscribe/unsubscribe cycles with no resource leak."""
        sse = SSEManager(poll_interval=1.0, unob=None)

        for _ in range(1000):
            q = sse.subscribe()
            sse.unsubscribe(q)

        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_subscribe_without_iterating_persists(self):
        """A queue subscribed but never iterated persists until QueueFull.

        This documents the known behavior: if subscribe() is called
        but the StreamingResponse generator never starts, the queue
        stays in _subscribers until broadcasts fill it to capacity (100).
        """
        sse = SSEManager(poll_interval=1.0, unob=None)
        orphan = sse.subscribe()

        # The orphan queue exists
        assert sse.subscriber_count == 1

        # Fill to capacity (maxsize=100). subscribe() doesn't put
        # anything in the queue, so we need 100 puts to fill it.
        for i in range(100):
            orphan.put_nowait(f"data: {i}\n\n")

        # Still there (full but not yet evicted — eviction happens on next broadcast)
        assert sse.subscriber_count == 1

        # One more triggers QueueFull — simulating what _poll_loop does
        dead = []
        try:
            orphan.put_nowait("data: overflow\n\n")
        except asyncio.QueueFull:
            dead.append(orphan)
        for q in dead:
            sse._subscribers.discard(q)

        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_subscribe_unsubscribe(self):
        """Concurrent async subscribe/unsubscribe is safe."""
        sse = SSEManager(poll_interval=1.0, unob=None)

        async def churn(n):
            for _ in range(n):
                q = sse.subscribe()
                await asyncio.sleep(0)  # yield to other tasks
                sse.unsubscribe(q)

        await asyncio.gather(*[churn(100) for _ in range(10)])
        assert sse.subscriber_count == 0
```

- [ ] **Step 2: Run to verify tests pass**

Run: `pytest -m stress teredacta/tests/test_stress_sse.py -v`
Expected: All 5 tests PASS

- [ ] **Step 3: Commit**

```bash
git add teredacta/tests/test_stress_sse.py
git commit -m "test: add SSE saturation stress tests"
```

---

### Task 9: Add shared stress test fixtures to conftest.py

**Files:**
- Modify: `teredacta/tests/conftest.py`

This avoids duplicating the full DB schema across every stress test file.

- [ ] **Step 1: Add stress_db and stress_app fixtures to conftest.py**

Append to `teredacta/tests/conftest.py`:

```python
@pytest.fixture
def stress_db(tmp_path, mock_db):
    """Reuse mock_db schema with optional seed data for stress tests."""
    return mock_db


@pytest.fixture
def stress_app(tmp_path, stress_db):
    """App for stress tests using the shared mock_db schema."""
    cfg = TeredactaConfig(
        unobfuscator_path=str(tmp_path),
        unobfuscator_bin="echo",
        db_path=str(stress_db),
        pdf_cache_dir=str(tmp_path / "pdf_cache"),
        output_dir=str(tmp_path / "output"),
        log_path=str(tmp_path / "unobfuscator.log"),
        host="127.0.0.1",
        port=8000,
    )
    from teredacta.app import create_app
    return create_app(cfg)
```

- [ ] **Step 2: Run existing tests to verify nothing broke**

Run: `pytest teredacta/tests/test_health.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add teredacta/tests/conftest.py
git commit -m "test: add shared stress_db and stress_app fixtures"
```

---

### Task 10: Stress test — Thread pool exhaustion

**Files:**
- Create: `teredacta/tests/test_stress_thread_pool.py`

- [ ] **Step 1: Write the stress tests**

Create `teredacta/tests/test_stress_thread_pool.py`:

```python
"""Stress tests for thread pool exhaustion scenarios."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import httpx


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestThreadPoolExhaustion:

    @pytest.fixture(autouse=True)
    def pin_executor(self):
        """Pin executor to small size and restore original after test."""
        loop = asyncio.get_event_loop()
        original_executor = loop._default_executor
        small_executor = ThreadPoolExecutor(max_workers=4)
        loop.set_default_executor(small_executor)
        yield small_executor
        # Restore original executor
        loop.set_default_executor(original_executor)
        small_executor.shutdown(wait=False, cancel_futures=True)

    @pytest.mark.asyncio
    async def test_liveness_responds_when_executor_saturated(self, stress_app, pin_executor):
        """Liveness probe works even when executor threads are all blocked."""
        loop = asyncio.get_running_loop()

        # Saturate the executor with short blocking tasks (2s, not 10s)
        barrier = threading.Event()
        futures = []
        for _ in range(4):
            fut = loop.run_in_executor(None, lambda: barrier.wait(timeout=2.0))
            futures.append(fut)

        try:
            await asyncio.sleep(0.3)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=stress_app),
                base_url="http://testserver",
            ) as client:
                resp = await asyncio.wait_for(
                    client.get("/health/live"),
                    timeout=3.0,
                )
                assert resp.status_code == 200
                assert resp.json()["status"] == "ok"
        finally:
            barrier.set()  # Unblock all threads
            await asyncio.gather(*futures, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_readiness_responds_when_executor_saturated(self, stress_app, pin_executor):
        """Readiness probe works even when executor threads are all blocked."""
        loop = asyncio.get_running_loop()
        barrier = threading.Event()

        futures = []
        for _ in range(4):
            fut = loop.run_in_executor(None, lambda: barrier.wait(timeout=2.0))
            futures.append(fut)

        try:
            await asyncio.sleep(0.3)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=stress_app),
                base_url="http://testserver",
            ) as client:
                resp = await asyncio.wait_for(
                    client.get("/health/ready"),
                    timeout=3.0,
                )
                assert resp.status_code == 200
                assert resp.json()["status"] == "healthy"
        finally:
            barrier.set()
            await asyncio.gather(*futures, return_exceptions=True)
```

- [ ] **Step 2: Run to verify tests pass**

Run: `pytest -m stress teredacta/tests/test_stress_thread_pool.py -v`
Expected: All 2 tests PASS

- [ ] **Step 3: Commit**

```bash
git add teredacta/tests/test_stress_thread_pool.py
git commit -m "test: add thread pool exhaustion stress tests"
```

---

### Task 11: Stress test — Compound deadlock (production failure mode)

**Files:**
- Create: `teredacta/tests/test_stress_compound_deadlock.py`

- [ ] **Step 1: Write the stress tests**

Create `teredacta/tests/test_stress_compound_deadlock.py`:

```python
"""Stress test reproducing the production compound deadlock.

The production hang was: all default executor threads blocked on
pool.acquire() (30s timeout) while SSE poll and admin requests
also need executor threads. This test verifies:
1. The event loop stays responsive during compound contention
2. The system recovers after holds are released
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import httpx

from teredacta.db_pool import ConnectionPool


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestCompoundDeadlock:

    @pytest.fixture(autouse=True)
    def pin_executor(self):
        """Pin executor to 8 threads (same as pool size) and restore after."""
        loop = asyncio.get_event_loop()
        original_executor = loop._default_executor
        small_executor = ThreadPoolExecutor(max_workers=8)
        loop.set_default_executor(small_executor)
        yield small_executor
        loop.set_default_executor(original_executor)
        small_executor.shutdown(wait=False, cancel_futures=True)

    @pytest.mark.asyncio
    async def test_event_loop_survives_compound_deadlock(self, stress_app, stress_db):
        """Event loop stays responsive even when executor + pool are both saturated."""
        loop = asyncio.get_running_loop()

        # Create a pool we can control
        pool = ConnectionPool(str(stress_db), max_size=8, read_only=True)

        # Phase 1: Hold all 8 pool connections
        held_conns = [pool.acquire(timeout=5.0) for _ in range(8)]
        assert pool.pool_status()["in_use"] == 8

        # Phase 2: Saturate executor with tasks trying to acquire pool connections
        # These will all block for up to 2 seconds waiting for a connection
        blocked_futures = []
        for _ in range(8):
            fut = loop.run_in_executor(
                None,
                lambda: pool.acquire(timeout=2.0),
            )
            blocked_futures.append(fut)

        # Give executor threads time to start blocking
        await asyncio.sleep(0.5)

        # Phase 3: Verify event loop is still alive
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=stress_app),
            base_url="http://testserver",
        ) as client:
            resp = await asyncio.wait_for(
                client.get("/health/live"),
                timeout=2.0,
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

        # Phase 4: Release all held connections
        for conn in held_conns:
            pool.release(conn)

        # Phase 5: Wait for blocked futures to resolve
        results = await asyncio.gather(*blocked_futures, return_exceptions=True)

        # Some may have acquired (after release), some may have timed out
        acquired = [r for r in results if not isinstance(r, Exception)]

        # Release any that acquired
        for conn in acquired:
            pool.release(conn)

        # Phase 6: Verify recovery
        status = pool.pool_status()
        assert status["in_use"] == 0

        # New acquire should work instantly
        conn = pool.acquire(timeout=1.0)
        pool.release(conn)

        pool.close()

    @pytest.mark.asyncio
    async def test_health_reports_degraded_during_contention(self, stress_app):
        """Health endpoint reports correct status during compound contention."""
        unob = stress_app.state.unob

        # Force pool creation by making a query
        conn = unob._get_db()
        unob._release_db(conn)

        # Hold all but 1 connection
        held = []
        for _ in range(7):
            held.append(unob._get_db())

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=stress_app),
            base_url="http://testserver",
        ) as client:
            resp = await client.get("/health/ready")
            data = resp.json()
            # Only 1 idle — should be degraded (threshold is 3)
            assert data["status"] == "degraded"
            assert data["checks"]["db_pool"]["idle"] == 1

        for c in held:
            unob._release_db(c)

        # After release — should be healthy again
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=stress_app),
            base_url="http://testserver",
        ) as client:
            resp = await client.get("/health/ready")
            data = resp.json()
            assert data["status"] == "healthy"
```

- [ ] **Step 2: Run to verify tests pass**

Run: `pytest -m stress teredacta/tests/test_stress_compound_deadlock.py -v`
Expected: All 2 tests PASS

- [ ] **Step 3: Commit**

```bash
git add teredacta/tests/test_stress_compound_deadlock.py
git commit -m "test: add compound deadlock stress test (production failure mode)"
```

---

### Task 12: Stress test — Mixed workload

**Files:**
- Create: `teredacta/tests/test_stress_mixed.py`

- [ ] **Step 1: Write the stress tests**

Create `teredacta/tests/test_stress_mixed.py`:

```python
"""Stress tests for mixed concurrent workloads."""

import asyncio
import sqlite3

import pytest
import httpx


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestMixedWorkload:

    @pytest.fixture
    def seeded_app(self, stress_app, stress_db):
        """Seed the stress_db with document data for mixed workload."""
        conn = sqlite3.connect(str(stress_db))
        rows = [
            (f"doc-{i}", f"source-{i % 5}", f"text content {i} " * 20,
             1, 0, f"file_{i}.pdf", (i % 10) + 1, i * 100)
            for i in range(1000)
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO documents "
            "(id, source, extracted_text, text_processed, pdf_processed, "
            "original_filename, page_count, size_bytes) VALUES (?,?,?,?,?,?,?,?)", rows
        )
        conn.commit()
        conn.close()
        return stress_app

    @pytest.mark.asyncio
    async def test_concurrent_requests_and_sse(self, seeded_app):
        """Simultaneous HTTP requests + SSE subscribers don't deadlock."""
        errors = []

        async def make_requests(client, n):
            for i in range(n):
                try:
                    resp = await client.get("/documents")
                    if resp.status_code not in (200, 503):
                        errors.append(f"GET /documents returned {resp.status_code}")
                except Exception as e:
                    errors.append(f"request error: {e}")

        async def subscribe_sse(client):
            """Subscribe to SSE briefly."""
            try:
                # Just hit the SSE endpoint — it'll 403 since no admin session,
                # but the point is to exercise the request path
                resp = await client.get("/sse/stats")
                # 403 is expected (not admin)
            except Exception:
                pass

        async def check_health(client, results):
            for _ in range(5):
                resp = await client.get("/health/ready")
                results.append(resp.json())
                await asyncio.sleep(0.2)

        health_results = []

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=seeded_app),
            base_url="http://testserver",
        ) as client:
            # Launch mixed workload
            await asyncio.gather(
                make_requests(client, 20),
                make_requests(client, 20),
                make_requests(client, 20),
                subscribe_sse(client),
                subscribe_sse(client),
                check_health(client, health_results),
            )

        assert not errors, f"Errors during mixed workload: {errors}"
        # Health should have been healthy throughout (light load)
        for result in health_results:
            assert result["status"] in ("healthy", "degraded")

    @pytest.mark.asyncio
    async def test_recovery_after_load(self, seeded_app):
        """Health returns to healthy after load subsides."""

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=seeded_app),
            base_url="http://testserver",
        ) as client:
            # Phase 1: Apply load
            tasks = []
            for _ in range(30):
                tasks.append(client.get("/documents"))
            await asyncio.gather(*tasks)

            # Phase 2: Wait briefly for things to settle
            await asyncio.sleep(0.5)

            # Phase 3: Check health
            resp = await client.get("/health/ready")
            data = resp.json()
            assert data["status"] == "healthy"
```

- [ ] **Step 2: Run to verify tests pass**

Run: `pytest -m stress teredacta/tests/test_stress_mixed.py -v`
Expected: All 2 tests PASS

- [ ] **Step 3: Commit**

```bash
git add teredacta/tests/test_stress_mixed.py
git commit -m "test: add mixed workload stress tests"
```

---

### Task 13: Locust load test suite

**Files:**
- Create: `stress/stress_config.py`
- Create: `stress/locustfile.py`
- Create: `stress/README.md`

- [ ] **Step 1: Create stress/stress_config.py**

```bash
mkdir -p stress
```

Create `stress/stress_config.py` (named `stress_config` to avoid shadowing `teredacta.config`):

```python
"""Configuration for locust stress tests."""

import os

# Target server
TARGET_HOST = os.environ.get("STRESS_TARGET_HOST", "http://localhost:8000")

# Admin credentials for SSE and admin endpoints
ADMIN_PASSWORD = os.environ.get("STRESS_ADMIN_PASSWORD", "test-password")

# User class weights (must sum to 100)
WEB_USER_WEIGHT = 60
SSE_USER_WEIGHT = 15
ADMIN_USER_WEIGHT = 20
HEALTH_MONITOR_WEIGHT = 5

# Health monitoring thresholds
LIVENESS_FAILURE_SECONDS = 0  # Any liveness failure is critical
READINESS_UNHEALTHY_SECONDS = 60  # Sustained unhealthy = test failure

# SSE connection parameters
SSE_MIN_HOLD_SECONDS = 10
SSE_MAX_HOLD_SECONDS = 60

# Load test phases (seconds)
RAMP_UP_SECONDS = 30
SUSTAINED_SECONDS = 240
RAMP_DOWN_SECONDS = 30
RECOVERY_SECONDS = 15
```

- [ ] **Step 2: Create stress/locustfile.py**

Create `stress/locustfile.py`:

```python
"""Locust stress test suite for TEREDACTA.

Run headless:
    locust -f stress/locustfile.py --headless -u 200 -r 10 -t 5m --host http://localhost:8000

Run with Web UI:
    locust -f stress/locustfile.py --host http://localhost:8000
"""

import logging
import math
import random
import time

import gevent
from locust import HttpUser, LoadTestShape, between, events, task

from stress_config import (
    ADMIN_PASSWORD,
    ADMIN_USER_WEIGHT,
    HEALTH_MONITOR_WEIGHT,
    RAMP_DOWN_SECONDS,
    RAMP_UP_SECONDS,
    READINESS_UNHEALTHY_SECONDS,
    RECOVERY_SECONDS,
    SSE_MAX_HOLD_SECONDS,
    SSE_MIN_HOLD_SECONDS,
    SSE_USER_WEIGHT,
    SUSTAINED_SECONDS,
    WEB_USER_WEIGHT,
)

logger = logging.getLogger(__name__)

# Track health status transitions globally.
# Safe under gevent: cooperative scheduling, no I/O between read-modify-write.
_health_tracker = {
    "last_healthy": time.monotonic(),
    "unhealthy_since": None,
    "liveness_failures": 0,
}


class StressTestShape(LoadTestShape):
    """Custom load shape with warm-up, sustained, cool-down, and recovery phases.

    Phase 1 (0-30s):      Ramp up from 0 to 200 users
    Phase 2 (30s-4m30s):  Sustained at 200 users
    Phase 3 (4m30s-5m):   Ramp down from 200 to 0
    Phase 4 (5m-5m15s):   Recovery — only HealthMonitor users remain
    """
    MAX_USERS = 200
    SPAWN_RATE = 10

    def tick(self):
        run_time = self.get_run_time()

        if run_time < RAMP_UP_SECONDS:
            # Phase 1: Ramp up
            users = min(self.MAX_USERS, math.ceil(run_time * self.SPAWN_RATE))
            return (users, self.SPAWN_RATE)

        elif run_time < RAMP_UP_SECONDS + SUSTAINED_SECONDS:
            # Phase 2: Sustained load
            return (self.MAX_USERS, self.SPAWN_RATE)

        elif run_time < RAMP_UP_SECONDS + SUSTAINED_SECONDS + RAMP_DOWN_SECONDS:
            # Phase 3: Ramp down
            elapsed_in_phase = run_time - RAMP_UP_SECONDS - SUSTAINED_SECONDS
            fraction_remaining = 1 - (elapsed_in_phase / RAMP_DOWN_SECONDS)
            users = max(1, math.ceil(self.MAX_USERS * fraction_remaining))
            return (users, self.SPAWN_RATE)

        elif run_time < RAMP_UP_SECONDS + SUSTAINED_SECONDS + RAMP_DOWN_SECONDS + RECOVERY_SECONDS:
            # Phase 4: Recovery — keep minimal users for health monitoring
            return (1, 1)

        else:
            # Done
            return None


class WebUser(HttpUser):
    """Simulates a visitor browsing public pages."""

    weight = WEB_USER_WEIGHT
    wait_time = between(1, 5)

    @task(5)
    def browse_documents(self):
        page = random.randint(1, 10)
        self.client.get(f"/documents?page={page}", name="/documents?page=[N]")

    @task(3)
    def browse_recoveries(self):
        self.client.get("/recoveries")

    @task(3)
    def browse_highlights(self):
        self.client.get("/highlights")

    @task(2)
    def browse_explore(self):
        self.client.get("/")

    @task(1)
    def view_document_detail(self):
        doc_id = f"doc-{random.randint(1, 100)}"
        self.client.get(f"/documents/{doc_id}", name="/documents/[id]")


class SSEUser(HttpUser):
    """Simulates an admin subscribing to SSE stats."""

    weight = SSE_USER_WEIGHT
    # Short wait between reconnections — hold time is inside the task
    wait_time = between(1, 3)

    def on_start(self):
        """Authenticate to get admin session cookie."""
        self.client.post(
            "/admin/login",
            data={"password": ADMIN_PASSWORD},
            name="/admin/login",
            allow_redirects=False,
        )

    @task
    def subscribe_sse(self):
        """Open SSE connection, hold it, then disconnect."""
        hold_time = random.uniform(SSE_MIN_HOLD_SECONDS, SSE_MAX_HOLD_SECONDS)
        start = time.monotonic()

        try:
            with self.client.get(
                "/sse/stats",
                stream=True,
                timeout=hold_time + 5,  # Hard timeout to prevent blocking beyond hold_time
                name="/sse/stats",
                catch_response=True,
            ) as resp:
                if resp.status_code == 403:
                    resp.failure("Not authenticated — SSE returned 403")
                    return
                resp.success()

                # Hold connection for the specified duration
                for line in resp.iter_lines():
                    if time.monotonic() - start > hold_time:
                        break
        except Exception as e:
            logger.debug("SSE connection ended: %s", e)


class AdminUser(HttpUser):
    """Simulates admin dashboard usage."""

    weight = ADMIN_USER_WEIGHT
    wait_time = between(2, 8)

    def on_start(self):
        self.client.post(
            "/admin/login",
            data={"password": ADMIN_PASSWORD},
            name="/admin/login",
            allow_redirects=False,
        )

    @task(3)
    def view_admin_dashboard(self):
        self.client.get("/admin/")

    @task(2)
    def check_daemon_status(self):
        self.client.get("/admin/daemon/status")

    @task(2)
    def view_entity_index_status(self):
        self.client.get("/admin/entity-index/status")

    @task(1)
    def view_config(self):
        self.client.get("/admin/config")

    @task(1)
    def view_logs(self):
        self.client.get("/admin/logs")


class HealthMonitor(HttpUser):
    """Continuously monitors health endpoints."""

    weight = HEALTH_MONITOR_WEIGHT
    wait_time = between(2, 5)

    @task(3)
    def check_liveness(self):
        with self.client.get("/health/live", catch_response=True, name="/health/live") as resp:
            if resp.status_code != 200:
                _health_tracker["liveness_failures"] += 1
                resp.failure(f"LIVENESS FAILURE: {resp.status_code}")
                logger.error("LIVENESS PROBE FAILED: status=%s", resp.status_code)
            else:
                resp.success()

    @task(1)
    def check_readiness(self):
        with self.client.get("/health/ready", catch_response=True, name="/health/ready") as resp:
            now = time.monotonic()

            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "unknown")

                if status == "healthy":
                    _health_tracker["last_healthy"] = now
                    _health_tracker["unhealthy_since"] = None
                    resp.success()
                elif status == "degraded":
                    # Expected under load — log but don't fail
                    resp.success()
                    logger.info("Health: degraded")
                else:
                    resp.failure(f"Unexpected status: {status}")
            elif resp.status_code == 503:
                if _health_tracker["unhealthy_since"] is None:
                    _health_tracker["unhealthy_since"] = now
                    logger.warning("Health: unhealthy (started)")

                duration = now - _health_tracker["unhealthy_since"]
                if duration > READINESS_UNHEALTHY_SECONDS:
                    resp.failure(
                        f"UNHEALTHY for {duration:.0f}s (threshold: {READINESS_UNHEALTHY_SECONDS}s)"
                    )
                else:
                    resp.success()
            else:
                resp.failure(f"Unexpected status code: {resp.status_code}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Report health summary at end of test. process_exit_code only works in headless mode."""
    tracker = _health_tracker
    logger.info("=== Health Summary ===")
    logger.info("Liveness failures: %d", tracker["liveness_failures"])
    if tracker["unhealthy_since"]:
        logger.warning("Server was unhealthy at test end")
    else:
        logger.info("Server was healthy at test end")

    if tracker["liveness_failures"] > 0:
        logger.error("TEST FAILED: Liveness probe failures detected")
        environment.process_exit_code = 1
```

- [ ] **Step 3: Create stress/README.md**

Create `stress/README.md`:

```markdown
# TEREDACTA Stress Tests

Load testing suite using [Locust](https://locust.io/).

## Setup

```bash
pip install -e ".[stress]"
```

## Running

### Against local server

Start TEREDACTA locally first:
```bash
teredacta run
```

Then run the stress tests:
```bash
# Headless (CI mode) — uses StressTestShape for phases
locust -f stress/locustfile.py --headless --host http://localhost:8000

# With web UI (interactive)
locust -f stress/locustfile.py --host http://localhost:8000
# Then open http://localhost:8089
```

### Against VPS

```bash
export STRESS_ADMIN_PASSWORD=your-admin-password
locust -f stress/locustfile.py --headless --host https://your-vps.example.com
```

### With web UI

```bash
locust -f stress/locustfile.py --host https://your-vps.example.com
```
Open http://localhost:8089 to configure users, spawn rate, and watch results.

## Load Phases (StressTestShape)

| Phase | Duration | Users | Description |
|---|---|---|---|
| Warm-up | 0-30s | 0→200 | Ramp up at 10 users/sec |
| Sustained | 30s-4m30s | 200 | Full load |
| Cool-down | 4m30s-5m | 200→0 | Ramp down |
| Recovery | 5m-5m15s | 1 | Verify health returns to healthy |

## Configuration

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `STRESS_TARGET_HOST` | `http://localhost:8000` | Target server URL |
| `STRESS_ADMIN_PASSWORD` | `test-password` | Admin password for SSE/admin tests |

## User Profiles

| Profile | Weight | Description |
|---|---|---|
| WebUser | 60% | Browses public pages (documents, recoveries, highlights) |
| SSEUser | 15% | Opens SSE connections, holds 10-60s, mix of graceful/ungraceful disconnects |
| AdminUser | 20% | Admin dashboard, daemon status, entity index status, config, logs |
| HealthMonitor | 5% | Polls /health/live and /health/ready, tracks status transitions |

## Success Criteria

- Liveness probe (`/health/live`) never fails
- Readiness probe (`/health/ready`) does not report "unhealthy" for more than 60 seconds continuously
- No HTTP 500 errors
- Server recovers to "healthy" after load subsides
```

- [ ] **Step 4: Commit**

```bash
git add stress/
git commit -m "feat: add locust load test suite with LoadTestShape phases"
```

---

### Task 14: Update deploy docs with Caddy health check

**Files:**
- Modify: `deploy/README.md:56-68`

- [ ] **Step 1: Add Caddy health check config**

In `deploy/README.md`, change the recommended production config section. After the existing content at the end of the file, add:

```markdown

## Health Checks

TEREDACTA exposes health endpoints for monitoring:

- `GET /health/live` — Liveness probe (event loop alive?)
- `GET /health/ready` — Readiness probe (DB pool, SSE status)

### Caddy Health Check

Add to your Caddyfile reverse_proxy block:

```
reverse_proxy localhost:8000 {
    health_uri /health/live
    health_interval 5s
}
```

This lets Caddy detect and route around unresponsive workers.

### External Monitoring

Point your monitoring tool (UptimeRobot, Healthchecks.io, etc.) at:
- Liveness: `https://your-domain.com/health/live`
- Readiness: `https://your-domain.com/health/ready`
```

- [ ] **Step 2: Commit**

```bash
git add deploy/README.md
git commit -m "docs: add health check config for Caddy and monitoring"
```

---

### Task 15: Run all tests and verify

**Files:** None (verification only)

- [ ] **Step 1: Run existing unit tests (non-stress)**

Run: `pytest teredacta/tests/ -v`
Expected: All existing tests PASS, stress tests are DESELECTED

- [ ] **Step 2: Run health endpoint tests**

Run: `pytest teredacta/tests/test_health.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run stress tests**

Run: `pytest -m stress -v`
Expected: All stress tests PASS

- [ ] **Step 4: Verify stress tests are excluded from default run**

Run: `pytest teredacta/tests/ --co -q | grep stress`
Expected: No stress test files listed (deselected by marker)

- [ ] **Step 5: Final commit if any fixes needed**

Only if previous steps required fixes.

---

## Task Dependency Graph

```
Task 1 (pool_status) ──┐
Task 2 (subscriber_count) ──┤
Task 3 (config fields) ──┤
                          ├── Task 4 (health router) ── Task 5 (log filter)
Task 6 (pyproject.toml) ──┘
                               │
                          Task 9 (shared fixtures)
                               │
                    ┌──────────┼──────────┐──────────┐
                    ▼          ▼          ▼          ▼
              Task 7      Task 8     Task 10     Task 11
            (db pool)     (sse)    (threadpool)  (deadlock)
                    │          │          │          │
                    └──────────┼──────────┘──────────┘
                               ▼
                          Task 12 (mixed)
                               │
                               ▼
                          Task 13 (locust)
                               │
                               ▼
                          Task 14 (deploy docs)
                               │
                               ▼
                          Task 15 (verify all)
```

Tasks 1, 2, 3, 6 can run in parallel. Task 9 (shared fixtures) after Task 4. Tasks 7, 8, 10, 11 can run in parallel after Task 9. Task 13 is independent of 7–12.

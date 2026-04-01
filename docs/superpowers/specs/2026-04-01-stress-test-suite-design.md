# Stress Test Suite Design

**Issue:** #7 — Enhancement: Build a stress test suite for TEREDACTA  
**Date:** 2026-04-01  
**Status:** Approved

## Overview

Comprehensive stress test suite to verify TEREDACTA's stability under load, targeting the failure modes that caused the production hang (all threads deadlocked, no logs, unresponsive server). Two complementary tools: pytest stress tests for CI-runnable regression checks, and locust for realistic sustained load testing against a live server.

## Architecture: Approach C (Locust + Pytest Stress Tests)

- **Pytest stress tests** — fast, deterministic, CI-runnable. Target specific failure modes: DB pool contention, SSE saturation, thread pool exhaustion, compound deadlock, mixed workloads.
- **Locust load tests** — realistic sustained load with composable user profiles. Run manually against localhost (fixture mode) or live VPS.

## 1. Health Endpoint

Two new async endpoints. Mounted via `app.include_router(health_router, prefix="/health")`.

### `GET /health/live` — Liveness Probe

Returns `{"status": "ok"}` with HTTP 200. No dependency checks. Proves the event loop is not deadlocked. Pure async — no executor, no DB, no locks.

### `GET /health/ready` — Readiness Probe

Returns JSON with component checks. Detailed metrics are only included when the request comes from localhost or an authenticated admin session; public responses return only the top-level status string.

**Authenticated/localhost response:**

```json
{
  "status": "healthy | degraded | unhealthy",
  "worker_pid": 12345,
  "checks": {
    "db_pool": {"status": "ok", "idle": 3, "in_use": 2, "capacity": 8},
    "sse": {"status": "ok", "subscribers": 3},
    "uptime_seconds": 1234
  }
}
```

**Public response:**

```json
{
  "status": "healthy | degraded | unhealthy"
}
```

**Pool metrics — correct formula:**

The pool uses lazy initialization (`_size` grows from 0 to `max_size`). The metrics are:
- `idle` = `self._pool.qsize()` — connections sitting in the queue ready for use
- `in_use` = `self._size - self._pool.qsize()` — connections checked out
- `capacity` = `self._max_size` — maximum possible connections

Note: `queue.Queue.qsize()` is approximate under contention (CPython). This is acceptable for health monitoring — the thresholds have enough margin that off-by-one races don't affect classification.

**Thresholds (8-connection pool):**

| Metric | Healthy | Degraded | Unhealthy |
|---|---|---|---|
| DB pool idle + uncreated | ≥3 | 1–2 | 0 or pool is None and app has served requests |
| SSE subscribers | <20 | 20–100 | >100 |

SSE thresholds are deliberately low because `/sse/stats` is admin-only — even 20 concurrent admin SSE connections is suspicious for typical deployments (0–5 admin users). Thresholds are configurable via `TeredactaConfig` fields `health_pool_degraded_threshold` and `health_sse_degraded_threshold`.

**Design constraints:**
- Never acquires a DB pool connection — reads pool metadata only
- Never acquires `ConnectionPool._lock` — reads `_size` and `_pool.qsize()` which are safe under the GIL for approximate values
- Async — does not occupy a thread pool slot
- 1-second hard timeout via `asyncio.wait_for()` — returns 503 if checks hang (if reading two integers takes >1s, the process is effectively dead)
- Returns HTTP 200 for healthy/degraded, HTTP 503 for unhealthy

**Required changes:**
1. Add public `pool_status() -> dict | None` method on `UnobInterface` that returns `{"idle": N, "in_use": N, "capacity": N}` or `None` if pool not yet initialized. The health endpoint treats `None` as "ok" (no queries have been made yet, pool not needed).
2. Add `subscriber_count` property on `SSEManager` returning `len(self._subscribers)`.

**Multi-worker note:** With `workers > 1`, each worker has its own pool and SSE manager. The `/health/ready` response reflects the state of the worker that handles the request. The `worker_pid` field (in authenticated responses) allows correlation. Caddy's round-robin means a single probe may not detect a hung worker — this is a known limitation. If one worker deadlocks, Caddy will still route some requests to it (resulting in timeouts), and probes will intermittently report healthy vs unhealthy depending on which worker responds.

**Log suppression:** Add Uvicorn access log filter to suppress `/health/*` requests, preventing log noise from frequent polling (43k+ lines/day at 2-second intervals).

### Implementation

New file: `teredacta/routers/health.py`, mounted in `app.py` with `prefix="/health"`.

### Caddy Integration

Update `deploy/README.md` with health check config:

```
reverse_proxy localhost:8000 {
    health_uri /health/live
    health_interval 5s
}
```

## 2. Pytest Stress Tests

CI-runnable regression tests targeting specific failure modes. Located in `teredacta/tests/`.

All stress tests use `httpx.AsyncClient` with ASGI transport (not `TestClient`) to exercise the full async stack, including the real event loop, executor, and SSE generator lifecycle.

### `test_stress_db_pool.py` — DB Pool Contention

- Spawn 50+ threads all calling `pool.acquire()` simultaneously on an 8-connection pool
- Verify no deadlocks — all threads complete (with either a connection or a timeout error)
- Verify pool recovers after burst subsides (connections returned, new acquires succeed)
- Verify graceful timeout behavior (proper exception, not a hang)
- Include variant with short acquire timeout (1–2s) to exercise the `TimeoutError` path and verify no connection leaks on timeout

### `test_stress_sse.py` — SSE Connection Saturation

- Open 200+ SSE subscriber queues rapidly
- Disconnect half ungracefully (abandon without unsubscribe)
- Verify that abandoned queues persist until `QueueFull` eviction (this is the current behavior — the test documents it, not assumes cleanup)
- Force `QueueFull` by broadcasting enough events, then verify eviction occurs
- Verify remaining active subscribers still receive events
- Rapid connect/disconnect cycling (1000 cycles) — verify no resource leak
- Test the subscribe-before-StreamingResponse race: subscribe a queue, then never start iterating the generator — verify the queue is eventually cleaned up or document it as a known leak vector

### `test_stress_thread_pool.py` — Thread Pool Exhaustion

- Pin executor size to a known value (e.g., 8 threads) for deterministic testing via `loop.set_default_executor(ThreadPoolExecutor(max_workers=8))`
- Submit blocking tasks that saturate the pinned executor
- Verify the liveness endpoint (`/health/live`) still responds (pure async, no executor dependency)
- Verify SSE polling continues (also async)
- Verify server returns errors (not hangs) when executor is full
- Include a variant that goes through `run_in_executor` → `pool.acquire()` to exercise the real code path, not just direct `pool.acquire()`

### `test_stress_compound_deadlock.py` — Production Failure Mode (NEW)

This is the specific scenario that caused the production hang:
1. Fill all 8 DB pool connections with long-running holds (simulated via sleep or deliberate slow queries)
2. Submit enough `run_in_executor(None, pool.acquire)` calls to saturate the default executor — all executor threads now blocked waiting for pool connections
3. Verify the event loop itself remains responsive (liveness probe returns 200)
4. Verify that additional `run_in_executor` calls (e.g., from SSE poll, admin requests) fail or queue rather than deadlocking
5. Release the long holds — verify the system recovers (pool connections returned, executor unblocks, health returns to healthy)
6. Pin executor to a small size (e.g., 8 threads = same as pool size) to make the compound deadlock deterministic

### `test_stress_mixed.py` — Combined Workload

- Simultaneously: HTTP requests to multiple endpoints + SSE subscribers + DB-heavy queries via `run_in_executor`
- Explicitly exercise cross-resource contention: N SSE subscribers holding executor slots while M requests also need executor slots for DB access
- Verify health endpoint reports degraded (not unhealthy) under moderate load
- Verify clean recovery after load stops — health returns to healthy

### `test_health.py` — Health Endpoint Unit Tests

- Verify response format and status codes (authenticated vs public responses)
- Verify threshold transitions (healthy → degraded → unhealthy)
- Verify 1-second timeout behavior
- Verify liveness probe works when readiness is unhealthy
- Verify `pool_status()` returns `None` before first query and valid dict after
- Verify `worker_pid` is included in authenticated responses

### Test Infrastructure

**Synthetic database:** SQLite DB with ~100k documents for meaningful query pressure. SQLite scans 10k rows in single-digit milliseconds — 100k with populated `extracted_text` fields (random 500–2000 character strings) creates actual I/O pressure. Include proportional related rows:
- 100k `documents` with populated `extracted_text`, `original_filename`, varying `page_count`/`size_bytes`
- 5k `match_groups` with 15k `match_group_members`
- 3k `merge_results` with populated `merged_text` (1000+ chars)
- 500 `jobs` across all statuses

Use deliberately expensive queries where needed: `LIKE '%pattern%'` on `extracted_text` (forces full scan), self-joins, unindexed filters.

**Pytest configuration in `pyproject.toml`:**
```toml
[tool.pytest.ini_options]
markers = [
    "stress: stress tests (excluded from default runs)",
]
addopts = "-m 'not stress'"
```

Running stress tests explicitly: `pytest -m stress -v`

**Timeouts:**
- Per-operation timeout: 5 seconds (e.g., a single `pool.acquire()`)
- Per-test timeout: 90 seconds (allows ramp-up, sustained load, recovery verification)
- Enforced via `pytest-timeout>=2.2.0` (added to dev dependencies)

**Executor pinning:** Stress tests that depend on executor saturation must pin the executor size to a known value (e.g., 8) at test setup. This ensures deterministic behavior across machines with different CPU counts (GitHub Actions: 2 vCPUs = 6 default threads; dev machine: 16 cores = 20 default threads).

**CI notes:** Stress tests run on-demand (`pytest -m stress`), not in the default `pytest` invocation. CI can include them as a separate job if desired.

Real SQLite and real connection pool — no mocks for stressed resources.

## 3. Locust Load Tests

Located in `stress/` at project root (separate from unit tests — requires a running server).

### User Classes

**`WebUser`** (weight: 60) — Standard page browsing
- Hits `/`, `/documents`, `/recoveries`, `/highlights`, random document/recovery detail pages
- Realistic think time (1–5s between requests)
- Validates responses are 200, not 503 or timeouts

**`SSEUser`** (weight: 15) — SSE subscriber (custom User subclass)
- Auth flow: POST to `/admin/login` with configured credentials, capture session cookie, pass cookie in SSE connection headers
- Opens SSE connection to `/sse/stats` using `sseclient-py` with the authenticated session
- Holds connection for random duration (10–60s)
- Mix of graceful disconnects (close connection) and ungraceful (kill greenlet mid-stream)
- Tracks events received, connection duration, errors
- Note: SSE connections block the gevent greenlet for their duration — the weight of 15% ensures ~30 of 200 users are SSE at peak, leaving 170 greenlets for HTTP load

**`AdminUser`** (weight: 20) — Admin operations
- Authenticates via `/admin/login`, manages session cookie
- Hits admin endpoints: daemon status, config page, queue, logs
- Occasional write operations: save config, trigger search

**`HealthMonitor`** (weight: 5) — Continuous health polling
- Hits `/health/live` every 2 seconds and `/health/ready` every 5 seconds
- Distinguishes between failure modes:
  - Liveness failure (any duration) = critical failure, flag immediately
  - Readiness unhealthy (sustained >60 seconds) = test failure
  - Readiness degraded = expected under load, log but don't fail
- Records all status transitions with timestamps

### Configuration

- `stress/config.py` — target URL, credentials, user counts, spawn rates, run duration
- Default: fixture mode (localhost:8000 with synthetic data)
- `--host` flag for live VPS testing
- `STRESS_ADMIN_PASSWORD` env var for credentials
- Defaults: **200 users**, spawn rate 10/s, 5-minute run

**Load profile justification:** With 200 users and 1–5s think time (avg 3s), expected concurrent in-flight requests ≈ 200/3 × avg_response_time. Even at 100ms avg response time, that's ~7 concurrent requests. At 500ms (under load), ~33 concurrent. This is sufficient to saturate the 8-connection pool and stress the default executor (6–20 threads depending on machine). The VPS profile can be tuned higher.

### Phases

1. **Warm-up** (30s): Ramp from 0 to 200 users at 10/s
2. **Sustained load** (4 minutes): Full user count, all profiles active
3. **Cool-down** (30s): Ramp down to 0 users via custom `LoadTestShape`
4. **Recovery verification**: HealthMonitor continues for 15s after cool-down, verifies health returns to "healthy"

### Running

```bash
# Headless against VPS
locust -f stress/locustfile.py --headless -u 200 -r 10 -t 5m --host https://your-vps.example.com

# Web UI for interactive testing
locust -f stress/locustfile.py --host https://your-vps.example.com

# Local fixture mode
locust -f stress/locustfile.py --headless -u 200 -r 10 -t 5m --host http://localhost:8000
```

## 4. Dependencies & Project Structure

### New Dependencies

In `pyproject.toml`:

```toml
[project.optional-dependencies]
stress = [
    "locust>=2.20.0",
    "sseclient-py>=1.8.0",
]

# Add to existing dev deps:
# pytest-timeout>=2.2.0
```

Pytest stress tests use stdlib + existing test deps + `pytest-timeout`. Locust tests additionally need the `stress` extra.

### Pytest Configuration

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "stress: stress tests (deselected by default, run with: pytest -m stress)",
]
addopts = "-m 'not stress'"
```

### Project Structure Additions

```
teredacta/
├── routers/
│   └── health.py                    # /health/live and /health/ready
├── tests/
│   ├── test_stress_db_pool.py
│   ├── test_stress_sse.py
│   ├── test_stress_thread_pool.py
│   ├── test_stress_compound_deadlock.py  # Production failure mode
│   ├── test_stress_mixed.py
│   └── test_health.py
stress/
├── locustfile.py
├── config.py
└── README.md
```

### Running

```bash
# Install stress dependencies
pip install -e ".[stress]"

# Unit + health tests (always in CI)
pytest teredacta/tests/test_health.py -v

# Stress tests (on-demand)
pytest -m stress -v

# Locust (manual, needs running server)
locust -f stress/locustfile.py --headless -u 200 -r 10 -t 5m --host http://localhost:8000
```

## 5. Success Criteria

From issue #7:

- Server remains responsive (liveness endpoint returns 200) under sustained load
- No thread pool deadlocks — compound deadlock test passes
- Proper error responses (503/504) when overloaded, not silent hangs
- Clean recovery after load subsides — health returns to "healthy" within 15 seconds of load stopping
- SSE subscribers cleaned up after disconnect (via QueueFull eviction)
- Health endpoint correctly reports degraded/unhealthy status under load

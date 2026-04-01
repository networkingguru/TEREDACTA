# Stress Test Suite Design

**Issue:** #7 — Enhancement: Build a stress test suite for TEREDACTA  
**Date:** 2026-04-01  
**Status:** Approved

## Overview

Comprehensive stress test suite to verify TEREDACTA's stability under load, targeting the failure modes that caused the production hang (all threads deadlocked, no logs, unresponsive server). Two complementary tools: pytest stress tests for CI-runnable regression checks, and locust for realistic sustained load testing against a live server.

## Architecture: Approach C (Locust + Pytest Stress Tests)

- **Pytest stress tests** — fast, deterministic, CI-runnable. Target specific failure modes: DB pool contention, SSE saturation, thread pool exhaustion, mixed workloads.
- **Locust load tests** — realistic sustained load with composable user profiles. Run manually against localhost (fixture mode) or live VPS.

## 1. Health Endpoint

Two new public async endpoints, no authentication required.

### `GET /health/live` — Liveness Probe

Returns `{"status": "ok"}` with HTTP 200. No dependency checks. Proves the event loop is not deadlocked.

### `GET /health/ready` — Readiness Probe

Returns JSON with component checks:

```json
{
  "status": "healthy | degraded | unhealthy",
  "checks": {
    "db_pool": {"status": "ok | degraded | error", "available": 6, "max": 8},
    "sse": {"status": "ok | degraded", "subscribers": 3},
    "uptime_seconds": 1234
  }
}
```

**Thresholds (8-connection pool):**

| Metric | Healthy | Degraded | Unhealthy |
|---|---|---|---|
| DB pool available | ≥3 | 1–2 | 0 or acquire timeout |
| SSE subscribers | <100 | 100–500 | >500 |

**Design constraints:**
- Never acquires a DB pool connection — inspects pool queue metadata only
- Async — does not occupy a thread pool slot
- 3-second hard timeout via `asyncio.wait_for()` — returns 503 if checks hang
- Returns HTTP 200 for healthy/degraded, HTTP 503 for unhealthy

**Required change:** Expose `available_count` property on `ConnectionPool` so the health endpoint can inspect pool state without acquiring a connection.

### Implementation

New file: `teredacta/routers/health.py`, mounted in `app.py`.

## 2. Pytest Stress Tests

CI-runnable regression tests targeting specific failure modes. Located in `teredacta/tests/`.

### `test_stress_db_pool.py` — DB Pool Contention

- Spawn 50+ threads all calling `pool.acquire()` simultaneously on an 8-connection pool
- Verify no deadlocks — all threads complete (with either a connection or a timeout error)
- Verify pool recovers after burst subsides (connections returned, new acquires succeed)
- Verify graceful timeout behavior (proper exception, not a hang)

### `test_stress_sse.py` — SSE Connection Saturation

- Open 200+ SSE subscriber queues rapidly
- Disconnect half ungracefully (abandon without unsubscribe)
- Verify cleanup — dead queues are detected and removed
- Verify remaining subscribers still receive events
- Rapid connect/disconnect cycling (1000 cycles) — verify no resource leak

### `test_stress_thread_pool.py` — Thread Pool Exhaustion

- Submit blocking tasks that saturate the default executor
- Verify the health endpoint still responds (async, not blocked by executor)
- Verify SSE polling continues (also async)
- Verify server returns errors (not hangs) when executor is full

### `test_stress_mixed.py` — Combined Workload

- Simultaneously: HTTP requests to multiple endpoints + SSE subscribers + DB-heavy queries
- Verify health endpoint reports degraded (not unhealthy) under moderate load
- Verify clean recovery after load stops — health returns to healthy

### `test_health.py` — Health Endpoint Unit Tests

- Verify response format and status codes
- Verify threshold transitions (healthy → degraded → unhealthy)
- Verify 3-second timeout behavior
- Verify liveness probe works when readiness is unhealthy

### Test Infrastructure

- Synthetic SQLite DB with ~10k documents for non-trivial queries
- Configurable concurrency levels via pytest parametrize or env vars
- 30-second timeout on all stress tests (hangs fail as test failures, not infinite waits)
- `@pytest.mark.stress` marker, excluded from default test runs via `pytest.ini`
- Real SQLite and real connection pool — no mocks for stressed resources

## 3. Locust Load Tests

Located in `stress/` at project root (separate from unit tests — requires a running server).

### User Classes

**`WebUser`** — Standard page browsing
- Hits `/`, `/documents`, `/recoveries`, `/highlights`, random document/recovery detail pages
- Realistic think time (1–5s between requests)
- Validates responses are 200, not 503 or timeouts

**`SSEUser`** — SSE subscriber (custom User subclass)
- Authenticates, opens SSE connection to `/sse/stats`
- Holds connection for random duration (10–60s)
- Mix of graceful and ungraceful disconnects
- Tracks events received, connection duration, errors

**`AdminUser`** — Admin operations
- Authenticates, hits admin endpoints: daemon status, config page, queue, logs
- Lower weight (fewer admin users than public users)

**`HealthMonitor`** — Continuous health polling
- Hits `/health/ready` every 2 seconds throughout the run
- Records status transitions (healthy → degraded → unhealthy)
- Fails the run if unhealthy is sustained for >30 seconds

### Configuration

- `stress/config.py` — target URL, user counts, spawn rates, run duration
- Default: fixture mode (localhost:8000 with synthetic data)
- `--host` flag for live VPS testing
- Defaults: 50 users, spawn rate 5/s, 5-minute run

### Running

```bash
# Headless CI mode
locust -f stress/locustfile.py --headless -u 50 -r 5 -t 5m --host http://localhost:8000

# Web UI for VPS testing
locust -f stress/locustfile.py --host https://your-vps.example.com
```

## 4. Dependencies & Project Structure

### New Dependencies

In `pyproject.toml` under `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
stress = [
    "locust>=2.20.0",
    "sseclient-py>=1.8.0",
]
```

No new core dependencies. Pytest stress tests use only stdlib + existing test deps.

### Project Structure Additions

```
teredacta/
├── routers/
│   └── health.py              # /health/live and /health/ready
├── tests/
│   ├── test_stress_db_pool.py
│   ├── test_stress_sse.py
│   ├── test_stress_thread_pool.py
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

# Stress tests (CI or manual)
pytest teredacta/tests/test_stress_*.py -v

# Locust (manual, needs running server)
locust -f stress/locustfile.py --headless -u 50 -r 5 -t 5m --host http://localhost:8000
```

## 5. Success Criteria

From issue #7:

- Server remains responsive (health endpoint returns 200) under sustained load
- No thread pool deadlocks
- Proper error responses (503/504) when overloaded, not silent hangs
- Clean recovery after load subsides

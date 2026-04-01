# Concurrency & Admission Queue Design Spec

**Goal:** Support 500+ concurrent users by raising server capacity through tuning and adding an admission control queue that holds excess users with position feedback rather than rejecting them.

**Approach:** Incremental improvements to the existing architecture (no rewrite). Two workstreams: (1) concurrency tuning to raise the ceiling, (2) admission control middleware with a user-facing queue page.

---

## 0. Prerequisites

### Enable WAL Mode on SQLite

Set `PRAGMA journal_mode = WAL` once during `ConnectionPool.__init__()` (on the first connection, before adding it to the pool). WAL mode is a persistent database-level setting that survives across connections and restarts, so it only needs to be set once per database file, not per connection. Without WAL, readers block on writers and vice versa, making pool size increases ineffective. This is the single highest-impact change and must land before other tuning.

### Verify Request Timeout Middleware

The admission queue relies on the request timeout middleware (120s) to kill long-running requests and free semaphore slots. `RequestTimeoutMiddleware` is NOT currently registered in `teredacta/app.py` (confirmed by grep). The commit `8218ab7` added it but it appears to have been lost. Re-implement and register it as an explicit implementation step before admission control. This is a hard dependency — without it, a hung request holds a semaphore slot forever.

---

## 1. Concurrency Tuning

### DB Pool: 8 -> 32 connections

The connection pool (`teredacta/db_pool.py`) is the primary bottleneck. With WAL mode enabled, SQLite handles concurrent readers well. Increase `max_size` default from 8 to 32 and make it configurable via `teredacta.yaml` as `max_pool_size`.

With 4 workers x 32 connections = 128 total pool connections across workers.

### Uvicorn Workers: 1 -> 4

The VPS has 8 AMD EPYC cores and 23GB RAM. Set default workers to 4 (configurable). Each worker gets its own event loop, executor, DB pool, and admission queue. This multiplies capacity across the board:

- 4 event loops
- 4 x 32 = 128 DB pool connections
- 4 x 40 = 160 anyio thread limiter tokens

Higher than 4 risks SQLite write contention with diminishing returns.

**Daemon mode:** The `teredacta start` command currently rejects `workers > 1` (`__main__.py` lines 100-103). Update `start` to allow `workers > 1`. The `start` command uses `os.fork()` to daemonize, and uvicorn's multi-worker mode also forks internally. This works: the PID file records the uvicorn master process PID, and `teredacta stop` sends SIGTERM to the master, which propagates to workers.

**Sticky sessions:** With multi-worker, each worker has its own admission queue state. The OS distributes connections across workers with no sticky routing. A user queued on worker 1 may poll worker 2 and get "ticket not found." To handle this: when a poll returns "ticket not found," the queue page JS re-enters the queue on the new worker (gets a new ticket). This is slightly worse UX (position resets) but avoids requiring sticky session infrastructure. Document in the operator guide that sticky sessions (e.g., Caddy `ip_hash`) are recommended for best queue UX.

### Bcrypt Login -> run_in_executor

`config.check_password()` runs synchronous bcrypt on the event loop, blocking all other coroutines for ~200-500ms. The login handler in `teredacta/routers/admin.py` (line 77) is an `async def` function, so bcrypt blocks the event loop directly. If it were a plain `def`, Starlette would auto-offload it. Since it is `async def`, the fix must explicitly wrap: `await loop.run_in_executor(None, config.check_password, password)`.

### SSE Hard Cap: 50 subscribers

`SSEManager.subscribe()` gets a `max_subscribers` parameter (configurable via `max_sse_subscribers` in config, default 50). Beyond that, return 503 with a friendly message. Prevents unbounded memory growth.

---

## 2. Admission Control Middleware

Pure ASGI middleware (wrapping the entire app, not FastAPI HTTP middleware) using `asyncio.Semaphore` for admission gating and `collections.deque` for FIFO queue tracking. Registered as the outermost middleware so it intercepts requests before routing.

### Request Flow

1. Request arrives at middleware (ASGI level, before routing)
2. Check if path is exempt (health, static, SSE, queue status) -- if so, pass through
3. Check if request carries a `_queue_ticket` cookie with a ready ticket -- if so, remove ticket from deque, proceed (semaphore slot already held on its behalf)
4. Try to acquire `asyncio.Semaphore(max_concurrent_requests)` without blocking
5. If acquired: request proceeds normally. On response complete, check if deque has waiting tickets. If yes, do NOT release semaphore -- instead transfer the slot by marking the front ticket as ready. If no waiters, release semaphore normally
6. If not acquired and queue has room: assign a ticket (UUID cookie), append ticket to FIFO deque, return queue page HTML immediately and close the connection. The user's browser polls `/_queue/status` until their ticket is marked ready, then re-submits the original request
7. If not acquired and queue is full: return 503 with friendly overflow page and `Retry-After` header

### Configuration

```yaml
max_concurrent_requests: 40    # per worker admission limit
max_queue_size: 200            # per worker; beyond this, 503
max_pool_size: 32              # DB connection pool size
max_sse_subscribers: 50        # SSE connection cap
workers: 4                     # uvicorn worker count
```

All four fields (`max_concurrent_requests`, `max_queue_size`, `max_pool_size`, `max_sse_subscribers`) must be added to `TeredactaConfig` in `teredacta/config.py` with defaults. The existing `**{k: v ...}` pattern in `load_config` (line 91) will pick them up from `teredacta.yaml` automatically.

Note: `max_concurrent_requests` (40) exceeds `max_pool_size` (32) by design. Not all requests require a DB connection (static-adjacent pages, admin dashboard, health). The 8-request gap is acceptable. If tuning shows excessive DB pool waits, lower `max_concurrent_requests` to match `max_pool_size`.

### Exempt Paths

These are never queued:

- `/health/*` -- monitoring probes must always respond
- `/_queue/status` -- the poll endpoint for queued users
- `/static/*` -- CSS/JS/images served from disk
- `/sse/*` -- SSE connections are long-lived and managed separately (see Section 5)

The path prefix `/_queue` is used instead of `/queue` to avoid collision with the existing `/queue/{path}` redirect to `/admin/queue/` in `app.py`. The `/_queue/status` endpoint is handled directly by the ASGI middleware before FastAPI routing — no FastAPI route definition is needed.

### Semaphore + FIFO Deque

The semaphore controls admission. The deque provides ordering and position tracking.

Data structure: `collections.deque` of `QueueTicket` dataclass instances:

```python
@dataclass
class QueueTicket:
    id: str                     # UUID
    ready: bool = False         # True when a slot has been transferred
    created_at: float = 0.0     # time.monotonic() at queue entry
    ready_at: float | None = None  # time.monotonic() when marked ready
```

A `dict[str, QueueTicket]` provides O(1) lookup by ticket ID alongside the deque for ordering.

**Slot transfer (critical):** When a request completes and the deque has waiting tickets, the completing request does NOT call `semaphore.release()`. Instead, it marks the front unready ticket as `ready=True` and sets `ready_at`. The semaphore count stays the same -- the slot is transferred, not released and re-acquired. When the user's browser re-submits the request with the ready ticket cookie, the middleware finds it in the dict, removes it from both dict and deque, and proceeds without acquiring the semaphore. If no tickets are waiting, the completing request calls `semaphore.release()` normally.

**Ready-ticket request completion:** When a request that entered via a ready ticket completes, it follows the exact same completion logic as any other request: check the deque for waiting tickets, transfer or release. There is no distinction between a "normal" request and a "ready-ticket" request once admitted — both hold a semaphore slot and both release/transfer on completion.

**Position calculation:** Iterate the deque from front to back, counting entries where `t.ready == False`, stopping when `t.id == ticket_id`. The count at that point is the position (0 = next to be admitted).

### Ticket Expiry

A periodic cleanup coroutine runs every 10 seconds:

1. Scan from the front of the deque
2. Remove any ticket where `ready=True` and `monotonic() - ready_at > 60` (ready but unclaimed for 60s)
3. For each expired ready ticket, call `semaphore.release()` to return the transferred slot
4. Remove any ticket where `ready=False` and `monotonic() - created_at > 300` (abandoned -- queued for 5+ minutes without polling)

This prevents stale tickets from blocking the queue or leaking semaphore slots.

### Ticket Tracking

- Middleware sets a `_queue_ticket` cookie with a UUID when a request enters the queue
- `GET /_queue/status?ticket=<id>` returns `{"position": N, "ready": false, "wait_estimate_seconds": M}` via O(1) dict lookup for ticket existence/readiness + O(n) deque scan for position (n <= 200 max, negligible)
- When `ready: true`, the queue page JS auto-redirects to the original URL (the re-submitted request carries the ticket cookie)
- Browser refresh preserves the cookie, so the user keeps their position
- If ticket is not found (worker restart or routed to different worker), response is `{"position": -1, "ready": false, "requeue": true}` and the JS re-enters the queue

### Wait Time Estimation

Sliding window of the last 100 completed request durations, stored as `collections.deque(maxlen=100)` of `(timestamp, duration)` tuples.

**Computation:**

1. Filter to entries within the last 5 minutes
2. If >= 5 recent entries: average their durations
3. If < 5 recent entries: use 1.0s default
4. `active_slots = max(1, max_concurrent_requests - semaphore._value)` (clamped to avoid division by zero)
5. `wait_seconds = position * avg_duration / active_slots`

The `/ active_slots` factor accounts for parallel processing: if 40 requests are active concurrently, ~40 will complete in each `avg_duration` window.

**Why sliding window, not EMA:** An EMA decays toward zero during idle periods. When a burst arrives after hours of quiet, the EMA barely moves and gives wildly inaccurate estimates. A sliding window naturally reflects current conditions by only averaging recent completions.

### Queue Overflow

Handled in the request flow (step 7). If the deque length >= `max_queue_size` (default 200) when a new request can't acquire the semaphore, return 503 with a friendly page: "The server is at capacity. Please try again in a few minutes." A `Retry-After` header is included for automated clients.

---

## 3. Queue Page UX

The queue page is served when the server is at capacity. It must be self-contained with zero external dependencies (no DB, no templates, no static file requests).

### Content

- TEREDACTA branding (inline CSS, no image requests)
- "The server is handling a lot of requests right now."
- "You're approximately **#N** in line. Estimated wait: **~Xs**."
- CSS-only animated progress indicator
- Position and estimate auto-update every 2-3 seconds via `fetch('/_queue/status?ticket=...')`
- When `ready: true`, auto-redirect to the original URL
- When `requeue: true` (ticket not found), automatically re-enter the queue by reloading the original URL

### Implementation

Single Python string in the middleware module. An f-string with the ticket ID and original URL baked in. ~60 lines of HTML/CSS/JS total. The polling JS handles three states: waiting (update position), ready (redirect), and requeue (reload).

### Edge Cases

- **Browser closed while queued:** Ticket sits in deque. If marked ready, the 60-second expiry starts. If never marked ready, the 5-minute abandoned ticket expiry removes it. Neither leaks a semaphore slot.
- **User refreshes queue page:** Same ticket cookie, same position. No place lost.
- **Multiple tabs:** Each tab gets its own ticket and queue slot (correct -- each is a separate concurrent request). Known trade-off: a user with N queued tabs holds N semaphore slots when ready. This is acceptable at stated queue sizes and not worth deduplication complexity.
- **Cookie-less clients (curl, scripts):** Get queue HTML with `Retry-After` header. Ticket ID also included in the response body as a data attribute for clients that can parse it. No cookie persistence means they go to the back on retry.

---

## 4. Error Handling

- **Middleware exception before semaphore acquired:** Pass request through unqueued (fail-open). Nothing to release.
- **Middleware exception after semaphore acquired:** Release/transfer the slot (same completion logic as normal), then return an error response. The request already ran or partially ran — the slot must not leak.
- **Middleware exception during response streaming:** Release/transfer the slot. The response is already partial — the client will see a broken response regardless.
- **Worker restart:** Queue state is in-memory and lost. Next poll from a queued user gets `requeue: true` and the JS re-enters the queue on whatever worker handles the next request.
- **Long-running requests:** Hold their semaphore slot. The request timeout middleware (120s) is the backstop -- it kills the request and frees the slot. The admission middleware must handle the timeout response and properly release/transfer the slot.
- **Queue status endpoint abuse:** Exempt from queuing. Returns ~100 bytes of JSON. Dict lookup is O(1), position scan is O(n) with n <= 200. Negligible cost even at hundreds of polls/sec.

---

## 5. SSE Handling

SSE connections are excluded from the admission queue. They are long-lived but cheap -- each holds an `asyncio.Queue` in memory and shares a single poll task for DB queries. SSE paths (`/sse/*`) are in the exempt paths list.

- Separate hard cap via `max_sse_subscribers` (default 50)
- Beyond cap: 503 with friendly message
- SSE poll task continues using `run_in_executor` for DB/subprocess calls -- unaffected by admission control

---

## 6. Testing Strategy

### Unit Tests (pytest, in-process)

- Semaphore admission: requests proceed when under limit, queue when at limit
- Slot transfer: completing request transfers slot to front ticket without releasing semaphore
- Queue position tracking: FIFO ordering, O(1) position lookup by ticket
- Ticket cookie: persistence on refresh, new ticket per tab
- Ticket expiry: ready tickets expire after 60s, abandoned tickets after 300s, slots properly released
- Exempt paths: health, static, SSE, queue/status always bypass
- Queue overflow: 503 when deque exceeds max_queue_size
- Wait estimate: sliding window computation, stale entry filtering, default fallback, division-by-zero guard
- Semaphore release on error: fail-open behavior
- Requeue flow: ticket-not-found returns requeue flag
- Timeout + admission interaction: request times out via RequestTimeoutMiddleware, verify slot is released/transferred and next queued ticket proceeds

### Stress Tests (pytest, in-process)

- Compound test: saturate semaphore, verify queued requests proceed in FIFO order as slots free via transfer
- Verify health probes respond while queue is full
- Verify ticket expiry under load doesn't leak slots

### Locust Tests (live server)

- Update existing locust suite to expect and handle queue pages under peak load
- `HealthMonitor` validates health endpoints are never queued
- New `QueuedUser` class: receive queue page -> poll status -> auto-redirect -> complete original request. Handle requeue gracefully.
- Success criteria: zero 503s at 500 users, liveness never fails, queue drains within 30s of load drop

### Tuning Validation

- Stress test at 200, 300, 500 users with 4 workers, max_concurrent_requests: 40
- Measure: p50/p95/p99 response times, max queue depth, queue drain time, 503 rate

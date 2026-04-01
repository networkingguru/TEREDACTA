# TEREDACTA Stability Fixes — Design Spec

**Date:** 2026-03-31
**Issues:** #2, #3, #4, #5, #6

## Context

Production incident: TEREDACTA hung with all threads deadlocked on `futex_wait_queue`. The process left no logs. Root cause investigation identified five contributing factors.

## Fix 1: Wire Up Logging Configuration (#2)

**Problem:** `log_path` and `log_level` config fields exist but are unused.

**Design:**
- Add a `setup_logging(cfg)` function in `__main__.py` called before app startup in both `run` and `start` commands
- Configure Python's root logger with:
  - A `RotatingFileHandler` writing to `cfg.log_path` (if non-empty)
  - A `StreamHandler` on stderr (for `run` mode visibility)
  - Log level from `cfg.log_level`
  - Format: `%(asctime)s %(levelname)s %(name)s %(message)s`
- Add `sys.excepthook` override to log uncaught exceptions before process death
- Set Uvicorn's `log_config=None` so it uses the configured root logger instead of its own
- In `start` (daemon) mode, keep the existing `os.dup2` redirect but also configure the file handler

**Config defaults (unchanged):**
- `log_path`: `""` (empty = no file handler, stderr only — already the default in config.py)
- `log_level`: `"info"` (already the default)

## Fix 2: Replace BaseHTTPMiddleware with Pure ASGI Middleware (#3)

**Problem:** `@app.middleware("http")` uses `BaseHTTPMiddleware` which wraps streaming response bodies, causing resource leaks with long-lived SSE connections.

**Design:**
- Replace the decorator-based middleware with a class implementing the ASGI interface directly
- The middleware sets `request.state.is_admin`, `request.state.csrf_token`, and `request.state.config` on the request scope, then passes through to the next app without wrapping the response
- This is a drop-in replacement — no router changes needed

```python
class TemplateContextMiddleware:
    def __init__(self, app, config, auth):
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

## Fix 3: Dedicated Thread Pool for SSE (#4)

**Problem:** SSE polling and request handlers compete for the same default `ThreadPoolExecutor`.

**Design:**
- Create a dedicated `ThreadPoolExecutor(max_workers=2, thread_name_prefix="sse")` owned by `SSEManager`
- Pass this executor to `run_in_executor()` in `_poll_loop()` instead of `None`
- Shut down the executor in `SSEManager.close()` (called from app lifespan)
- The `dashboard.py` `daemon_status_fragment` endpoint also uses `run_in_executor(None, ...)` — change it to use the SSE manager's executor via `request.app.state.sse.executor`

## Fix 4: Health Endpoint (#5)

**Problem:** No way to detect if the server is responsive.

**Design:**
- Add `GET /health` as an async handler (runs in event loop, not thread pool)
- Returns JSON: `{"status": "ok", "db": "ok"|"error", "uptime_seconds": N}`
- DB check: acquire and immediately release a connection from the pool with a short timeout (2s); run in executor to avoid blocking the event loop
- On DB failure: return `{"status": "degraded", "db": "error: <message>"}` with HTTP 503
- No authentication required

## Fix 5: Request Timeouts (#6)

**Problem:** No request-level timeout — slow requests hold thread pool slots indefinitely.

**Design:**
- Add Uvicorn's `--timeout-keep-alive` (default 5, already reasonable)
- Add a pure ASGI timeout middleware that tracks whether response headers have been sent; if not yet sent when the timeout fires, return HTTP 504
- SSE endpoints are exempt (identified by `/sse/` path prefix or `Accept: text/event-stream` header)
- Use a `response_started` flag to avoid sending 504 after headers are already on the wire
- The timeout middleware wraps the app OUTSIDE the template context middleware

## Files Modified

| File | Changes |
|------|---------|
| `teredacta/__main__.py` | Add `setup_logging()`, pass `log_config=None` to uvicorn |
| `teredacta/app.py` | Replace middleware decorator with ASGI class, add health route, add timeout middleware |
| `teredacta/sse.py` | Add dedicated executor, add `close()` method |
| `teredacta/routers/dashboard.py` | Use SSE executor instead of default |
| `teredacta/config.py` | Add `request_timeout_seconds` field (log_path/log_level already exist) |
| `teredacta/db_pool.py` | No changes needed (health check uses existing acquire/release) |

## Testing Strategy

- Unit tests for logging setup (verify handlers configured)
- Unit test for health endpoint (mock DB pool)
- Unit test for timeout middleware (mock slow handler)
- Integration test: SSE connections don't leak with pure ASGI middleware
- Verify existing tests still pass

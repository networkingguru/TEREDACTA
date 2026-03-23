# Public Deployment Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden TEREDACTA for public-facing deployment by fixing the five highest-impact scalability bottlenecks, adding a sample reverse proxy config, updating docs with real dataset sizes, and switching the license to MIT.

**Architecture:** Single Uvicorn process becomes multi-worker. SSE daemon-status polling removed from public pages (admin-only). SQLite connections pooled via a thread-safe queue. Sample Caddy config provided for reverse proxying and automatic HTTPS. README and config docs updated for production deployment.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, SQLite, Caddy (sample config only)

---

### Task 1: Raise file descriptor limit in systemd template and document for manual setups

**Files:**
- Modify: `teredacta/installer/templates/systemd.service.j2`
- Modify: `README.md` (deployment section)

- [ ] **Step 1: Add LimitNOFILE to systemd template**

In `teredacta/installer/templates/systemd.service.j2`, add `LimitNOFILE=4096` under `[Service]`:

```ini
[Service]
Type=simple
User={{ user }}
LimitNOFILE=4096
ExecStart=teredacta run --config {{ db_path | replace('/unobfuscator.db', '') }}/../.teredacta/config.yaml
Restart=on-failure
RestartSec=5
```

- [ ] **Step 2: Run existing tests to verify no breakage**

Run: `cd /Users/brianhill/Scripts/TEREDACTA && python -m pytest teredacta/tests/ -x -q`
Expected: All pass (this is a config-only change)

- [ ] **Step 3: Commit**

```bash
git add teredacta/installer/templates/systemd.service.j2
git commit -m "feat: raise file descriptor limit to 4096 in systemd template"
```

---

### Task 2: Add Uvicorn worker count to config and CLI

**Files:**
- Modify: `teredacta/config.py` — add `workers` field
- Modify: `teredacta/__main__.py` — pass `workers` to `uvicorn.run()`

- [ ] **Step 1: Write test for workers config field**

Create `teredacta/tests/test_workers_config.py`:

```python
from teredacta.config import TeredactaConfig

def test_default_workers_is_1():
    cfg = TeredactaConfig()
    assert cfg.workers == 1

def test_workers_from_init():
    cfg = TeredactaConfig(workers=4)
    assert cfg.workers == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/brianhill/Scripts/TEREDACTA && python -m pytest teredacta/tests/test_workers_config.py -x -v`
Expected: FAIL — `TeredactaConfig` has no `workers` field

- [ ] **Step 3: Add workers field to TeredactaConfig**

In `teredacta/config.py`, add to the `TeredactaConfig` dataclass fields:

```python
    workers: int = 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/brianhill/Scripts/TEREDACTA && python -m pytest teredacta/tests/test_workers_config.py -x -v`
Expected: PASS

- [ ] **Step 5: Update `run` command in `__main__.py` to use workers**

When `workers > 1`, Uvicorn requires an import string (not an app instance) so it can fork worker processes. Replace the entire `run` command:

```python
@cli.command()
@click.option("--host", default=None, help="Bind host (overrides config)")
@click.option("--port", default=None, type=int, help="Bind port (overrides config)")
@click.option("--config", "config_path", default=None, help="Path to config file")
@click.option("--workers", "workers_override", default=None, type=int, help="Number of worker processes")
def run(host, port, config_path, workers_override):
    """Start the TEREDACTA web server (foreground)."""
    import uvicorn

    cfg = _load_and_patch_cfg(config_path, host, port)
    if workers_override:
        cfg.workers = workers_override
    _print_banner(cfg)

    if cfg.workers > 1:
        # Multi-worker requires import string, not app instance.
        # Store config in env so _app_factory.py can reconstruct it.
        # Empty string → None round-trip is handled by the factory.
        import os
        os.environ["_TEREDACTA_CONFIG_PATH"] = config_path or ""
        if host:
            os.environ["_TEREDACTA_HOST"] = host
        if port:
            os.environ["_TEREDACTA_PORT"] = str(port)
        uvicorn.run("teredacta._app_factory:app", host=cfg.host, port=cfg.port, workers=cfg.workers)
    else:
        from teredacta.app import create_app
        app = create_app(cfg)
        uvicorn.run(app, host=cfg.host, port=cfg.port)
```

Create `teredacta/_app_factory.py`:

```python
"""Factory module for multi-worker Uvicorn.

When Uvicorn runs with workers > 1 it needs an import string pointing to an
app object. This module creates the app using config from environment
variables set by __main__.py.

The empty-string-to-None conversion on _TEREDACTA_CONFIG_PATH is intentional:
__main__.py stores `config_path or ""` (since env vars can't be None), and
we convert "" back to None here so load_config() uses its search-path logic.
"""
import os
from teredacta.config import load_config
from teredacta.app import create_app

_config_path = os.environ.get("_TEREDACTA_CONFIG_PATH") or None
_cfg = load_config(_config_path)

_host = os.environ.get("_TEREDACTA_HOST")
_port = os.environ.get("_TEREDACTA_PORT")
if _host:
    _cfg.host = _host
if _port:
    _cfg.port = int(_port)

app = create_app(_cfg)
```

- [ ] **Step 6: Update `start` command to reject multi-worker**

The `start` command uses `os.fork()` for daemonization. Combining this with Uvicorn's own `workers > 1` forking creates a double-fork problem where `teredacta stop` would orphan worker processes. Instead, refuse multi-worker in daemon mode and direct users to systemd.

In the `start` command, after `cfg = _load_and_patch_cfg(...)`, add:

```python
    if cfg.workers > 1:
        click.echo("Error: Multi-worker mode is not supported with 'teredacta start'.")
        click.echo("Use systemd or 'teredacta run --workers N' instead.")
        sys.exit(1)
```

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/brianhill/Scripts/TEREDACTA && python -m pytest teredacta/tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add teredacta/config.py teredacta/__main__.py teredacta/_app_factory.py teredacta/tests/test_workers_config.py
git commit -m "feat: add configurable Uvicorn worker count (default 1)"
```

---

### Task 3: Make SSE conditional — admin pages only

**Files:**
- Modify: `teredacta/templates/base.html` — conditionally include daemon-status SSE
- Modify: `teredacta/routers/dashboard.py` — add admin guard to SSE endpoint

The daemon status indicator (`/sse/daemon-status` polled every 5s and `/sse/stats` persistent SSE) is only useful for admins. Public users don't need to see pipeline status. Currently every page load triggers an HTMX poll that becomes a persistent connection.

- [ ] **Step 1: Write test that public users don't get SSE markup**

Create `teredacta/tests/test_sse_conditional.py`:

```python
def test_public_page_no_sse_polling(client):
    """Public pages should not poll /sse/daemon-status."""
    resp = client.get("/recoveries")
    assert resp.status_code == 200
    assert "/sse/daemon-status" not in resp.text

def test_admin_page_has_sse_polling(client):
    """Admin pages should still have daemon status polling."""
    # In local mode, admin is auto-enabled
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "daemon-status" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/brianhill/Scripts/TEREDACTA && python -m pytest teredacta/tests/test_sse_conditional.py -x -v`
Expected: `test_public_page_no_sse_polling` FAILS (SSE markup is on every page)

- [ ] **Step 3: Modify base.html to conditionally show daemon status**

Use `is defined` guard so the template never errors if a route handler forgets to pass `is_admin`:

In `teredacta/templates/base.html`, change the `nav-right` div:

From:
```html
        <div class="nav-right">
            <span id="daemon-status" hx-get="/sse/daemon-status" hx-trigger="load, every 5s" hx-swap="innerHTML">
                <span class="status-dot stopped"></span> CHECKING...
            </span>
        </div>
```

To:
```html
        <div class="nav-right">
            {% if is_admin is defined and is_admin %}
            <span id="daemon-status" hx-get="/sse/daemon-status" hx-trigger="load, every 5s" hx-swap="innerHTML">
                <span class="status-dot stopped"></span> CHECKING...
            </span>
            {% endif %}
        </div>
```

- [ ] **Step 4: Guard SSE endpoints against non-admin access**

In `teredacta/routers/dashboard.py`, add admin checks to both SSE endpoints:

```python
@sse_router.get("/sse/stats")
async def sse_stats(request: Request):
    if not getattr(request.state, "is_admin", False):
        return HTMLResponse("Forbidden", status_code=403)
    sse = getattr(request.app.state, "sse", None)
    if sse is None:
        return HTMLResponse("SSE not configured", status_code=503)
    queue = sse.subscribe()
    return StreamingResponse(
        sse.event_generator(queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@sse_router.get("/sse/daemon-status", response_class=HTMLResponse)
async def daemon_status_fragment(request: Request):
    if not getattr(request.state, "is_admin", False):
        return HTMLResponse("", status_code=403)
    unob = request.app.state.unob
    loop = asyncio.get_running_loop()
    try:
        status = await loop.run_in_executor(None, unob.get_daemon_status)
    except Exception:
        status = "unknown"
    dot_class = "running" if status == "running" else "stopped"
    return HTMLResponse(
        f'<span class="status-dot {dot_class}"></span> {status.upper()}'
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/brianhill/Scripts/TEREDACTA && python -m pytest teredacta/tests/test_sse_conditional.py -x -v`
Expected: Both PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /Users/brianhill/Scripts/TEREDACTA && python -m pytest teredacta/tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add teredacta/templates/base.html teredacta/routers/dashboard.py teredacta/tests/test_sse_conditional.py
git commit -m "feat: restrict daemon-status SSE polling to admin pages only"
```

---

### Task 4: Add SQLite connection pooling

**Files:**
- Create: `teredacta/db_pool.py` — thread-safe connection pool
- Modify: `teredacta/unob.py` — replace `_get_db()` with pooled connections
- Modify: `teredacta/app.py` — initialize pool at startup, close at shutdown

Currently `_get_db()` in `unob.py:120-134` opens a fresh `sqlite3.connect()` on every request and closes it in a `finally` block. Under load this creates a connection storm. A simple thread-safe pool reuses connections.

- [ ] **Step 1: Write tests for the connection pool**

Create `teredacta/tests/test_db_pool.py`:

```python
import sqlite3
import threading
from teredacta.db_pool import ConnectionPool

def test_pool_returns_connection(tmp_path):
    db_path = tmp_path / "test.db"
    sqlite3.connect(str(db_path)).close()
    pool = ConnectionPool(str(db_path), max_size=2, read_only=True)
    conn = pool.acquire()
    assert conn is not None
    pool.release(conn)
    pool.close()

def test_pool_reuses_connections(tmp_path):
    db_path = tmp_path / "test.db"
    sqlite3.connect(str(db_path)).close()
    pool = ConnectionPool(str(db_path), max_size=2, read_only=True)
    conn1 = pool.acquire()
    pool.release(conn1)
    conn2 = pool.acquire()
    assert conn1 is conn2
    pool.release(conn2)
    pool.close()

def test_pool_context_manager(tmp_path):
    db_path = tmp_path / "test.db"
    sqlite3.connect(str(db_path)).close()
    pool = ConnectionPool(str(db_path), max_size=2, read_only=True)
    with pool.connection() as conn:
        assert conn is not None
    pool.close()

def test_pool_max_size(tmp_path):
    db_path = tmp_path / "test.db"
    sqlite3.connect(str(db_path)).close()
    pool = ConnectionPool(str(db_path), max_size=2, read_only=True)
    c1 = pool.acquire()
    c2 = pool.acquire()
    # Third acquire should block; use timeout to avoid hanging
    import queue
    try:
        c3 = pool.acquire(timeout=0.1)
        # Should not reach here
        pool.release(c3)
        assert False, "Should have raised"
    except Exception:
        pass  # Expected — pool exhausted
    pool.release(c1)
    pool.release(c2)
    pool.close()

def test_pool_threaded(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.commit()
    conn.close()
    pool = ConnectionPool(str(db_path), max_size=4, read_only=True)
    results = []
    def worker():
        with pool.connection() as c:
            row = c.execute("SELECT 1").fetchone()
            results.append(row[0])
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8
    assert all(r == 1 for r in results)
    pool.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/brianhill/Scripts/TEREDACTA && python -m pytest teredacta/tests/test_db_pool.py -x -v`
Expected: FAIL — `teredacta.db_pool` does not exist

- [ ] **Step 3: Implement ConnectionPool**

Create `teredacta/db_pool.py`:

```python
"""Thread-safe SQLite connection pool."""

import queue
import sqlite3
import threading
from contextlib import contextmanager
from typing import Optional


class ConnectionPool:
    """Reusable pool of SQLite connections.

    Connections are created lazily up to *max_size*. When all connections
    are in use, acquire() blocks until one is returned.
    """

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

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=self._busy_timeout / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {self._busy_timeout}")
        if self._read_only:
            conn.execute("PRAGMA query_only = ON")
        return conn

    def acquire(self, timeout: Optional[float] = 30.0) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("Pool is closed")
        # Try to get an idle connection first
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            pass
        # Try to create a new one if under max
        with self._lock:
            if self._size < self._max_size:
                self._size += 1
                return self._create_connection()
        # Wait for a connection to be returned
        try:
            return self._pool.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"Could not acquire connection within {timeout}s")

    def release(self, conn: sqlite3.Connection):
        if self._closed:
            conn.close()
            return
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            conn.close()
            with self._lock:
                self._size -= 1

    @contextmanager
    def connection(self):
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)

    def close(self):
        self._closed = True
        while True:
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break
```

- [ ] **Step 4: Run pool tests**

Run: `cd /Users/brianhill/Scripts/TEREDACTA && python -m pytest teredacta/tests/test_db_pool.py -x -v`
Expected: All PASS

- [ ] **Step 5: Integrate pool into UnobInterface**

In `teredacta/unob.py`, modify `__init__` and `_get_db`:

Replace the existing `_get_db` method (and add pool init) so that:

```python
# In __init__, after existing fields:
self._pool: Optional[ConnectionPool] = None

# Replace _get_db:
def _get_db(self) -> sqlite3.Connection:
    if self._pool is None:
        from teredacta.db_pool import ConnectionPool
        db_path = Path(self.config.db_path)
        if not db_path.exists():
            raise FileNotFoundError(
                f"Database not found at {db_path}. "
                "Check your TEREDACTA configuration."
            )
        self._pool = ConnectionPool(
            str(db_path), max_size=8, read_only=True, busy_timeout=5000
        )
    return self._pool.acquire()
```

Then change every `conn.close()` in `finally` blocks to `self._release_db(conn)` instead. There are many methods that follow the pattern (approximately 12 occurrences).

**Important:** Leave `ensure_indexes()` (line ~136) unchanged — it opens its own write connection directly via `sqlite3.connect()` and must NOT use the read-only pool.

The methods follow this pattern:

```python
conn = self._get_db()
try:
    # ... queries ...
finally:
    conn.close()
```

Change each to:

```python
conn = self._get_db()
try:
    # ... queries ...
finally:
    self._release_db(conn)
```

Add the helper:

```python
def _release_db(self, conn: sqlite3.Connection):
    if self._pool:
        self._pool.release(conn)
    else:
        conn.close()
```

Also add a `close` method to `UnobInterface`:

```python
def close(self):
    if self._pool:
        self._pool.close()
```

- [ ] **Step 6: Add shutdown hook in app.py using lifespan**

In `teredacta/app.py`, use FastAPI's lifespan context manager (not the deprecated `@app.on_event`):

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(application: FastAPI):
    yield
    application.state.unob.close()
```

Then pass it to `FastAPI(title="TEREDACTA", docs_url=None, redoc_url=None, lifespan=lifespan)`.

Move the lifespan definition before `create_app` or inline it inside `create_app` before the `FastAPI()` call.

- [ ] **Step 7: Run full test suite**

Run: `cd /Users/brianhill/Scripts/TEREDACTA && python -m pytest teredacta/tests/ -x -q`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add teredacta/db_pool.py teredacta/unob.py teredacta/app.py teredacta/tests/test_db_pool.py
git commit -m "feat: add SQLite connection pooling to reduce per-request overhead"
```

---

### Task 5: Add sample Caddy reverse proxy config

**Files:**
- Create: `deploy/Caddyfile` — sample Caddy config
- Create: `deploy/README.md` — deployment guide

- [ ] **Step 1: Create deploy directory**

```bash
mkdir -p /Users/brianhill/Scripts/TEREDACTA/deploy
```

- [ ] **Step 2: Write Caddyfile**

Create `deploy/Caddyfile`:

```
# Sample Caddyfile for TEREDACTA
# Replace example.com with your domain.
# Caddy handles HTTPS certificates automatically via Let's Encrypt.
#
# Install: https://caddyserver.com/docs/install
# Run:     caddy run --config /path/to/Caddyfile

example.com {
    # Serve static files directly (bypasses Uvicorn)
    handle_path /static/* {
        root * /path/to/TEREDACTA/teredacta/static
        file_server
    }

    # Proxy everything else to Uvicorn with SSE-friendly settings
    reverse_proxy localhost:8000 {
        flush_interval -1
        transport http {
            read_timeout 120s
        }
    }
}
```

- [ ] **Step 3: Write deployment README**

Create `deploy/README.md`:

```markdown
# Deploying TEREDACTA

## Reverse Proxy with Caddy

Caddy provides automatic HTTPS via Let's Encrypt, static file serving, and connection buffering.

### Install Caddy

```bash
# Ubuntu/Debian
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy

# macOS
brew install caddy
```

### Configure

1. Copy `Caddyfile` to `/etc/caddy/Caddyfile`
2. Replace `example.com` with your domain
3. Replace `/path/to/TEREDACTA` with the actual install path
4. Ensure DNS points to your server

### Start

```bash
sudo systemctl enable --now caddy
```

Caddy will automatically obtain and renew TLS certificates.

## File Descriptor Limits

For production, raise the file descriptor limit:

```bash
# Check current limit
ulimit -n

# Temporary (current session)
ulimit -n 4096

# Permanent (add to /etc/security/limits.conf)
* soft nofile 4096
* hard nofile 8192
```

The systemd service template already includes `LimitNOFILE=4096`.

## Recommended Production Config

```yaml
# teredacta.yaml
host: 127.0.0.1          # Bind to localhost (Caddy handles external traffic)
port: 8000
workers: 4                # Uvicorn worker processes
secret_key: <generate>    # python3 -c "import os; print(os.urandom(32).hex())"
```

Set admin password via environment variable:
```bash
export TEREDACTA_ADMIN_PASSWORD=your-secure-password
```
```

- [ ] **Step 4: Commit**

```bash
git add deploy/
git commit -m "docs: add sample Caddy config and deployment guide"
```

---

### Task 6: Update README for production deployment

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update disk space to full dataset size**

The README currently says "~50 GB disk space" for datasets and "~40 GB total" for downloads. The actual full dataset (all DOJ volumes plus House Oversight releases with complete PDF cache) is approximately 200 GB. Update both references.

In the Prerequisites section, change:
```
- **~50 GB disk space** for datasets (PDF cache + database)
```
to:
```
- **~200 GB disk space** for the full dataset (PDF cache + database)
```

In Step 4, change:
```
This downloads the DOJ Epstein disclosure datasets from archive.org mirrors (~40 GB total).
```
to:
```
This downloads the DOJ Epstein disclosure datasets from archive.org mirrors (~200 GB total).
```

- [ ] **Step 2: Update Architecture section**

Replace the Architecture section with:

```markdown
## Architecture

```
Browser ─── Caddy (HTTPS) ─── Uvicorn (N workers) ─┬─ SQLite (read-only, pooled) ── Unobfuscator DB
                                                     ├─ SQLite (read/write, WAL) ──── Entity Index DB
                                                     ├─ SSE (admin only)
                                                     └─ subprocess (admin) ─────────── Unobfuscator CLI
```

FastAPI application with configurable Uvicorn worker processes. Public routes are read-only with pooled SQLite connections. SSE live updates are restricted to admin pages. The entity index is a separate TEREDACTA-owned SQLite database — Unobfuscator's database is never modified.

For production deployment behind a reverse proxy, see [deploy/README.md](deploy/README.md).
```

- [ ] **Step 3: Update Configuration section**

Add `workers` to the sample config:

```yaml
host: 127.0.0.1       # 0.0.0.0 for network access, 127.0.0.1 behind reverse proxy
port: 8000
workers: 1             # Uvicorn worker processes (4 recommended for production)
secret_key: <generated-by-installer>
```

- [ ] **Step 4: Update License section**

Change:
```
## License

Private.
```

to:

```
## License

MIT. See [LICENSE](LICENSE).
```

- [ ] **Step 5: Run full tests**

Run: `cd /Users/brianhill/Scripts/TEREDACTA && python -m pytest teredacta/tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: update README for production deployment, real dataset sizes, MIT license"
```

---

### Task 7: Change license to MIT

**Files:**
- Create: `LICENSE`
- Modify: `pyproject.toml` — add license field

- [ ] **Step 1: Create LICENSE file**

Create `LICENSE` with the standard MIT license text, copyright holder Brian Hill, year 2026.

- [ ] **Step 2: Add license to pyproject.toml**

Add under `[project]`:
```toml
license = {text = "MIT"}
```

- [ ] **Step 3: Commit**

```bash
git add LICENSE pyproject.toml
git commit -m "chore: switch license from private to MIT"
```

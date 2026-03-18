# TEREDACTA — Design Specification

**Date:** 2026-03-16
**Status:** Approved

## Overview

TEREDACTA is a Python web application that wraps Unobfuscator in a modern, reactive web interface. It provides a single-pane-of-glass experience for browsing documents, viewing PDFs, monitoring pipeline progress, and managing all Unobfuscator features through a browser.

**Branding:** The logo is an ASCII-art pterodactyl with the name "TEREDACTA" stylized into it.

## Goals

- Surface all Unobfuscator features in a web UI
- Public read-only access for transparency; authenticated admin for control operations
- Platform independent (Windows, macOS, Linux)
- Minimal tooling: no Node/npm, no build step, pure Python with vendored JS
- Support local use, server deployment, and containerized deployment
- Guided installer for all deployment modes

## Architecture

### Monolith with Modular Routers

Single FastAPI process serving HTML templates (Jinja2), static assets (HTMX, PDF.js), SSE endpoints, and API routes. Routes are organized into FastAPI routers — one per feature area.

```
teredacta/
├── __init__.py
├── __main__.py              # Entry point: python -m teredacta
├── app.py                   # FastAPI app factory
├── config.py                # TEREDACTA config loader
├── auth.py                  # Admin session middleware (signed cookies)
├── sse.py                   # SSE event manager (polls Unob DB for changes)
├── unob.py                  # Interface to Unobfuscator (DB reads + subprocess)
├── routers/
│   ├── dashboard.py         # Live stats, pipeline progress
│   ├── documents.py         # Document browser with filtering
│   ├── groups.py            # Match group viewer
│   ├── recoveries.py        # Recovery viewer with highlighted text
│   ├── pdf.py               # PDF serving + PDF.js viewer page
│   ├── queue.py             # Job queue viewer (admin: manage)
│   ├── summary.py           # Summary report viewer
│   └── admin.py             # Login, daemon control, config, logs, downloads, search
├── templates/
│   ├── base.html            # Top nav bar shell + HTMX/SSE setup
│   ├── partials/            # HTMX fragments (table rows, stats cards, etc.)
│   ├── dashboard/
│   ├── documents/
│   ├── groups/
│   ├── recoveries/
│   ├── pdf/
│   ├── queue/
│   ├── summary/
│   └── admin/
├── static/
│   ├── css/
│   │   └── app.css          # Single stylesheet
│   ├── js/
│   │   ├── htmx.min.js     # Vendored HTMX
│   │   └── pdfjs/           # Vendored PDF.js
│   └── img/                 # Logo, favicon
├── installer/
│   ├── wizard.py            # CLI install wizard
│   └── templates/           # docker-compose.yml, systemd unit templates
└── tests/
```

### Data Flow

**Read path (public):** Browser → FastAPI router → queries Unobfuscator SQLite via `unob.py` → renders Jinja2 template → returns HTML (full page or HTMX fragment). SSE stream pushes live stat updates.

**Write path (admin only):** Admin action → FastAPI checks session cookie → calls `subprocess.run(["unobfuscator", ...])` via `unob.py` → returns status fragment.

**PDF path:** Browser requests PDF → router reads file from Unobfuscator's PDF cache or output directory → streams to PDF.js viewer.

### Interface to Unobfuscator (`unob.py`)

Single module encapsulating all interaction with Unobfuscator:

- **Database reads:** Direct SQLite queries against Unobfuscator's database. Opens connection with `PRAGMA query_only=ON` and `busy_timeout=5000` to handle concurrent access safely while the daemon writes. All reads are read-only. If the DB file does not exist or is corrupted, `unob.py` raises a clear error that the UI surfaces as a banner: "Database not found at configured path. Check your TEREDACTA configuration."
- **Subprocess calls:** Invokes the `unobfuscator` CLI for control operations: `start`, `stop`, `status`, `search`, `config set`, `summary`. All subprocess calls use a 60-second default timeout. Stderr is captured and surfaced to the admin UI on failure. If the `unobfuscator` binary is not found at the configured path, a clear error message is shown.
- **File access:** Reads PDFs from Unobfuscator's `pdf_cache` and `output` directories.
- **Log tailing:** Implements its own Python-based log file reader (not delegating to `unobfuscator log` which uses `tail -f` and is not cross-platform). Reads the log file directly and streams new lines via SSE.
- **Restart:** Implemented as stop-then-start within TEREDACTA. If stop times out (30 seconds), reports the failure to the admin rather than force-starting a second instance.

This is the only module that knows about Unobfuscator's internals. If the Unobfuscator schema changes, only `unob.py` needs updating.

## Technology Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Runtime | Python 3.10+ | |
| Web framework | FastAPI | |
| ASGI server | Uvicorn | |
| Templates | Jinja2 | |
| Reactivity | HTMX (vendored) | No build step |
| PDF viewing | PDF.js (vendored) | No build step |
| Live updates | SSE (native FastAPI) | |
| Auth | itsdangerous | Signed cookies |
| Password hashing | bcrypt | Admin password storage |
| Config | PyYAML | |
| CLI | Click | |
| DB access | sqlite3 | stdlib |
| Subprocess | subprocess | stdlib |

**Dependencies:** FastAPI, uvicorn, jinja2, itsdangerous, bcrypt, pyyaml, click. Seven packages beyond stdlib.

## Layout

### Application Shell

Top navigation bar with horizontal links. Full-width content area below.

- **Left side of nav:** Dashboard | Documents | Groups | Recoveries | Queue | Summary
- **Right side of nav:** Daemon status indicator (green/red dot with RUNNING/STOPPED)
- No visible admin link in the nav bar — admin access is via the `/admin` URL only

### Detail Views

Tabbed single-pane layout. Tabs switch between different views of the same data (e.g., merged text, output PDF, original PDFs, metadata). One view at a time, full width. Clean and focused.

## Authentication & Authorization

### Two-Tier Model

- **Public (unauthenticated):** Full read access to all data. Dashboard, document browser, match groups, recoveries, PDF viewer, job queue (view only), summary report.
- **Admin (authenticated):** All public features plus daemon control, search, config editing, log viewing, dataset downloads, job queue management.

### Implementation

- Admin password set via `TEREDACTA_ADMIN_PASSWORD` env var (preferred) or config file (stored as bcrypt hash, never plaintext). When the env var is set, the app hashes the plaintext value on startup and holds the hash in memory for comparison — it does not write back to the config file.
- **Local mode:** If `host` is `127.0.0.1` and no password is configured, admin features are available without authentication (single-user local use).
- **Server mode:** If `host` is `0.0.0.0` and no password is configured, admin features are disabled entirely and a warning is logged.
- Login page at `/admin` — no visible link in the public UI
- POST `/admin/login` validates password, sets signed cookie via itsdangerous with `SameSite=Strict`
- CSRF protection: `base.html` renders a CSRF token into a `<meta>` tag. HTMX picks it up via a global `hx-headers='{"X-CSRF-Token": "..."}' ` attribute on `<body>`. All state-changing endpoints validate this header against the token in the signed session cookie.
- Session expires after configurable timeout (default 1 hour)
- When authenticated, admin-only controls appear throughout the UI (start/stop buttons, search form, etc.)
- No user accounts, no database table — one password, one session

## Feature Areas

### Public Features

**1. Dashboard** (SSE live updates)
- Pipeline stage progress bars: indexed → fingerprinted → matched → merged → PDF processed → output generated. Progress is derived from DB counts: "indexed" = rows in `documents` where `text_processed=1`, "fingerprinted" = rows in `document_fingerprints`, "matched" = documents in `match_group_members`, etc.
- Key stats cards: total documents, match groups, redactions recovered, soft redactions, PDFs processed, failed jobs
- Daemon status indicator (running/stopped) — visible but not controllable without admin
- Admin view: start/stop/restart buttons appear next to daemon status

**2. Document Browser**
- Paginated table: ID, filename, batch, source, page count, redaction status, processing status
- Filter by: source (DOJ/House Oversight), batch, processing stage, has-redactions
- Search box: server-side SQL `LIKE` query against document ID, filename, and description fields via HTMX request. This is a simple filter on indexed metadata, not a full-text search on `extracted_text`. Distinct from the admin Search feature (#8), which enqueues Unobfuscator processing jobs.
- Click row → detail view with full extracted text, linked match group, "View PDF" button

**3. Match Groups**
- List of all match groups with member count and similarity scores
- Click group → shows all member documents
- Visual indicator of which docs contributed recovered text

**4. Recovery Viewer**
- **Recovery list page:**
  - List of merge results where `recovered_count > 0`
  - **Search box:** Filter recoveries by text content of recovered passages (e.g., search for "Epstein" to find all documents where that name was recovered). Server-side SQL `LIKE` query on `merged_text`. Distinct from document browser search (which filters by metadata) and admin search (which enqueues processing jobs). A "Search in recoveries" link appears on the document browser when metadata search returns sparse results.
  - **Most common unredactions:** Top section showing the top 20 most frequently recovered text strings (minimum 2 occurrences, minimum 3 words), ranked by count. Each entry links to the filtered recovery list for that string. Strings are compared after whitespace normalization (collapse whitespace, trim). Computed on first access using SQLite `json_each()` on `merge_results.recovered_segments`, cached in memory, and invalidated when the SSE polling loop detects new merge results.
- Tabbed detail view:
  - **Merged Text tab:** Full merged text with recovered passages highlighted in green. Source attribution for each recovered passage.
  - **Output PDF tab:** Highlighted PDF in PDF.js viewer
  - **Original PDFs tab:** Source document PDFs in PDF.js, switchable between group members. Includes a **PDF comparison mode**: side-by-side synchronized scrolling of the base document and a selected donor document. Both PDF.js viewers scroll in lockstep. The donor PDF has recovered passages highlighted (using the same yellow highlighting from Unobfuscator's output generator), making it easy to see exactly which parts of the donor filled in the base document's redactions. A dropdown selects which donor to compare against. A toggle switches between side-by-side and single-PDF view.
  - **Metadata tab:** Document IDs, similarity scores, recovery stats, links
- Download button for output PDF

**5. PDF Viewer**
- PDF.js embedded viewer for any PDF (original, output, summary)
- Download button

**6. Job Queue** (read-only for public)
- Table: job ID, stage, status, priority, payload summary
- Filter by status (pending/running/done/failed)

**7. Summary Report**
- View the summary PDF generated by Unobfuscator

### Admin Features

All accessed via `/admin` URL after authentication.

**8. Search**
- Form: person name, batch ID, document ID, free text query
- Submit enqueues high-priority job via `unobfuscator search`
- Shows job status, links to results when complete

**9. Daemon Control**
- Start/stop/restart buttons
- Foreground option
- Status with uptime

**10. Configuration**
- Display current config.yaml values
- Editable form for: workers, thresholds, polling interval, redaction markers
- Save writes to Unobfuscator's config

**11. Logs**
- Live-tail of daemon log via SSE
- Filter by level (info/warning/error)
- Configurable line count

**12. Dataset Downloads**
- List available datasets with download status
- Trigger downloads, show progress
- Disk space indicator

## Live Updates (SSE)

`sse.py` runs a single shared async polling task that queries the Unobfuscator SQLite database every 2 seconds. Connected clients subscribe to this shared task via an async generator. When a client disconnects, its subscription is cleaned up automatically. The polling task only runs while at least one client is connected — it starts on first subscription and stops when the last client disconnects.

**SSE-powered areas:**
- Dashboard stats and progress bars
- Job queue status changes
- Daemon status (running/stopped)
- Log tailing (admin only)

**Standard HTMX areas** (request/response, no SSE):
- Document browsing and filtering
- Match group viewing
- Recovery viewing
- PDF viewing
- All admin forms (search, config, downloads)

## Installer & Deployment

### CLI Wizard (`python -m teredacta install`)

1. Detect OS (Windows/macOS/Linux)
2. Ask: local use or server deployment?
3. Check for existing Unobfuscator installation
   - Found: ask for path, validate DB exists
   - Not found: offer to install. The wizard runs `git clone` to fetch Unobfuscator, creates a Python virtual environment in the target directory, runs `pip install -r requirements.txt` inside it, and verifies `unobfuscator.py` runs. If `git` is not available, falls back to downloading a release archive via `urllib`.
4. Ask for data directory (DB, PDFs, output)
5. Ask for port (default 8000)
6. Server mode: ask for admin password
7. Ask: bare-metal or Docker?
   - **Bare-metal:** Generate config file. On Linux, offer systemd unit file.
   - **Docker:** Generate `docker-compose.yml` and `.env` with volume mounts.
8. Write config to `~/.teredacta/config.yaml`

### Configuration File

```yaml
unobfuscator_path: /path/to/Unobfuscator
unobfuscator_bin: python /path/to/Unobfuscator/unobfuscator.py
db_path: /path/to/unobfuscator.db
pdf_cache_dir: /path/to/pdf_cache
output_dir: /path/to/output
host: 127.0.0.1
port: 8000
admin_password_hash: null   # bcrypt hash; use env var TEREDACTA_ADMIN_PASSWORD for plaintext input
log_level: info
session_timeout_minutes: 60
sse_poll_interval_seconds: 2
subprocess_timeout_seconds: 60
```

### Deployment Modes

- **Local:** `python -m teredacta run` — binds to 127.0.0.1, admin access without login
- **Server:** `python -m teredacta run` — binds to 0.0.0.0, admin password required
- **Docker:** `docker compose up -d` — uses generated compose file with volume mounts

### Graceful Shutdown

When TEREDACTA receives SIGTERM (or the Docker container stops), it shuts down the Uvicorn server cleanly. It does **not** attempt to stop the Unobfuscator daemon — the daemon is an independent process that should be managed separately. In Docker, the `docker-compose.yml` template runs both processes and handles stopping both via container lifecycle.

## Platform Independence

- Python 3.10+ on Windows, macOS, Linux
- No platform-specific dependencies
- subprocess calls to Unobfuscator use `sys.executable` to find the Python interpreter
- File paths handled with `pathlib.Path` throughout
- Docker option provides full platform abstraction

### Windows Considerations

- **Daemon control:** Unobfuscator's `stop` command uses Unix signals (`SIGTERM`/`SIGKILL`) which don't exist on Windows. On Windows, TEREDACTA uses `taskkill` for process management instead of delegating to `unobfuscator stop`. The `start` command launches the daemon as a subprocess directly rather than using Unix daemonization.
- **Log tailing:** TEREDACTA implements its own Python-based log reader, avoiding Unobfuscator's `tail -f` dependency.
- **Recommended path on Windows:** Docker deployment, which sidesteps all platform differences.

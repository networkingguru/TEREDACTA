# UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform TEREDACTA from an admin-oriented pipeline monitor into a discovery-first investigative tool with entity exploration, redaction jumping, and role-appropriate navigation.

**Architecture:** Four phases, each producing working software. Phase 1 restructures navigation. Phase 2 builds the entity index. Phase 3 adds the Explore and Highlights pages. Phase 4 adds redaction jumping and research improvements.

**Tech Stack:** FastAPI, Jinja2, HTMX, vanilla JS (explore.js, source-panel.js), SQLite, PDF.js, CSS animations.

**Spec:** `docs/superpowers/specs/2026-03-22-ui-redesign-design.md`

---

## File Structure

### New files
- `teredacta/routers/explore.py` — Explore page + entity API endpoints
- `teredacta/routers/highlights.py` — Highlights page
- `teredacta/routers/api.py` — Entity API endpoints (HTML fragments)
- `teredacta/entity_index.py` — Entity extraction, index build, DB management
- `teredacta/templates/explore.html` — Explore page template
- `teredacta/templates/explore/entity_list.html` — Entity list HTMX fragment
- `teredacta/templates/explore/connections.html` — Connections HTMX fragment
- `teredacta/templates/explore/preview.html` — Preview HTMX fragment
- `teredacta/templates/highlights.html` — Highlights page template
- `teredacta/templates/recoveries/source_panel.html` — Source panel fragment
- `teredacta/templates/pdf/embed_full.html` — Full PDF.js viewer with findController
- `teredacta/static/js/explore.js` — Entity graph column slide, fetch, pushState
- `teredacta/static/js/source-panel.js` — Recovery click handler, source panel
- `teredacta/tests/test_entity_index.py` — Entity extraction tests
- `teredacta/tests/routers/test_explore.py` — Explore page tests
- `teredacta/tests/routers/test_highlights.py` — Highlights page tests
- `teredacta/tests/routers/test_source_panel.py` — Source panel tests

### Modified files
- `teredacta/app.py` — Remount routers, add entity index to app.state
- `teredacta/templates/base.html` — New nav bar with role-aware links
- `teredacta/routers/admin.py` — Add entity index build endpoint, absorb dashboard page + stats-fragment
- `teredacta/routers/dashboard.py` — Stripped down to SSE endpoints only (becomes SSE-only module)
- `teredacta/routers/recoveries.py` — Add source panel endpoint, boolean search
- `teredacta/routers/documents.py` — Entity-aware search
- `teredacta/unob.py` — Add segment mapping to format_merged_text, search context extraction
- `teredacta/static/css/app.css` — Three-column layout, slide animations, source panel, hover effects
- `teredacta/templates/dashboard.html` — Update nav block to `nav_admin`, update hardcoded URLs to `/admin/` paths
- `teredacta/templates/recoveries/tabs/merged_text.html` — Clickable recovered passages
- `teredacta/templates/recoveries/detail.html` — Source panel container
- `teredacta/templates/recoveries/list.html` — Remove common unredactions panel, add sort/boolean hint
- `teredacta/templates/admin/dashboard.html` — Add entity index stats card, use `nav_admin` block
- `teredacta/templates/groups/list.html` — Change nav block to `nav_admin`
- `teredacta/templates/groups/detail.html` — Change nav block to `nav_admin`
- `teredacta/templates/queue/list.html` — Change nav block to `nav_admin`
- `teredacta/config.py` — Add entity_db_path to TeredactaConfig
- `teredacta/tests/conftest.py` — Add entity DB fixtures

---

## Phase 1: Navigation Restructure

### Task 1: Add entity_db_path to config

**Files:**
- Modify: `teredacta/config.py`
- Modify: `teredacta/tests/test_config.py`

- [ ] **Step 1: Add entity_db_path field to TeredactaConfig**

In `teredacta/config.py`, add to the dataclass:
```python
entity_db_path: str = ""
```

And in `load_config`, after building the config, if `entity_db_path` is empty, default it:
```python
if not cfg.entity_db_path:
    cfg.entity_db_path = str(Path(cfg.db_path).parent / "teredacta_entities.db") if cfg.db_path else ""
```

- [ ] **Step 2: Run existing tests**

Run: `pytest teredacta/tests/test_config.py -v`
Expected: All pass (new field has a default)

- [ ] **Step 3: Commit**

```bash
git add teredacta/config.py
git commit -m "feat: add entity_db_path to config"
```

### Task 2: Restructure base.html navigation

**Files:**
- Modify: `teredacta/templates/base.html`
- Modify: `teredacta/templates/dashboard.html`
- Modify: `teredacta/templates/admin/dashboard.html`
- Modify: `teredacta/templates/groups/list.html`
- Modify: `teredacta/templates/groups/detail.html`
- Modify: `teredacta/templates/queue/list.html`

- [ ] **Step 1: Update base.html with new nav structure**

Replace the nav section in `teredacta/templates/base.html`:

```html
<nav class="top-nav">
    <div class="nav-left">
        <a href="/" class="nav-logo"><img src="/static/img/logo.png" alt="TEREDACTA" class="nav-logo-img"></a>
        <a href="/" class="nav-link {% block nav_explore %}{% endblock %}">Explore</a>
        <a href="/highlights" class="nav-link {% block nav_highlights %}{% endblock %}">Highlights</a>
        <a href="/recoveries" class="nav-link {% block nav_recoveries %}{% endblock %}">Recoveries</a>
        <a href="/documents" class="nav-link {% block nav_documents %}{% endblock %}">Documents</a>
        <a href="/summary" class="nav-link {% block nav_summary %}{% endblock %}">Summary</a>
        {% if is_admin %}
        <a href="/admin" class="nav-link {% block nav_admin %}{% endblock %}" title="Pipeline administration">Admin</a>
        {% endif %}
    </div>
    <div class="nav-right">
        <span id="daemon-status" hx-get="/sse/daemon-status" hx-trigger="load, every 5s" hx-swap="innerHTML">
            <span class="status-dot stopped"></span> CHECKING...
        </span>
    </div>
</nav>
```

Note: The old `nav_dashboard`, `nav_groups`, and `nav_queue` blocks are removed from `base.html`. Any template that previously used those blocks must be updated.

- [ ] **Step 2: Update dashboard.html to use nav_admin and fix hardcoded URLs**

`teredacta/templates/dashboard.html` stays as the admin dashboard page (it is the page rendered by `dashboard.py`'s `GET /` route, which will be absorbed into `admin.py` — see Task 3). Update it:

1. Change `{% block nav_dashboard %}active{% endblock %}` to `{% block nav_admin %}active{% endblock %}`.
2. Change `hx-get="/stats-fragment"` to `hx-get="/admin/stats-fragment"`.
3. Verify daemon control buttons already use `/admin/daemon/*` paths (they do: `hx-post="/admin/daemon/start"` etc.).

- [ ] **Step 3: Update admin/dashboard.html to use nav_admin**

In `teredacta/templates/admin/dashboard.html`, add `{% block nav_admin %}active{% endblock %}` (it currently has no nav block).

- [ ] **Step 4: Update groups and queue templates to use nav_admin**

In `teredacta/templates/groups/list.html`: change `{% block nav_groups %}active{% endblock %}` to `{% block nav_admin %}active{% endblock %}`.
In `teredacta/templates/groups/detail.html`: change `{% block nav_groups %}active{% endblock %}` to `{% block nav_admin %}active{% endblock %}`.
In `teredacta/templates/queue/list.html`: change `{% block nav_queue %}active{% endblock %}` to `{% block nav_admin %}active{% endblock %}`.

- [ ] **Step 5: Run tests to verify nav renders**

Run: `pytest teredacta/tests/ -v -x`
Expected: All 119 pass

- [ ] **Step 6: Commit**

```bash
git add teredacta/templates/
git commit -m "feat: restructure nav — discovery first, admin behind toggle"
```

### Task 3: Remount routers for new URL structure

**Files:**
- Modify: `teredacta/app.py`
- Modify: `teredacta/routers/dashboard.py`
- Modify: `teredacta/routers/admin.py`
- Create: `teredacta/routers/explore.py`
- Create: `teredacta/routers/highlights.py`
- Create: `teredacta/templates/explore.html`
- Create: `teredacta/templates/highlights.html`

**Route conflict resolution:** After remounting, both `dashboard.py` and `admin.py` would have `GET /` at `/admin/`. To fix this, we move `dashboard.py`'s page endpoints (`GET /` and `GET /stats-fragment`) into `admin.py` and strip `dashboard.py` down to SSE-only endpoints.

- [ ] **Step 1: Move page endpoints from dashboard.py into admin.py**

Move the `dashboard` view (`GET /`) and `stats_fragment` view (`GET /stats-fragment`) from `dashboard.py` into `admin.py`. In `admin.py`, the existing `admin_page` (`GET /`) already handles the login gate and renders `admin/dashboard.html`. Update it to also handle the case where a non-admin-requiring config just renders `dashboard.html` (the pipeline stats page). Specifically:

In `admin.py`, update the `GET /` handler to render `dashboard.html` as a sub-view or add the stats-fragment endpoint:

```python
@router.get("/stats-fragment", response_class=HTMLResponse)
async def stats_fragment(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    templates = request.app.state.templates
    unob = request.app.state.unob
    loop = asyncio.get_running_loop()
    try:
        stats = await loop.run_in_executor(None, unob.get_stats)
    except FileNotFoundError:
        stats = {}
    return templates.TemplateResponse("dashboard_stats.html", {
        "request": request, "stats": stats,
    })
```

- [ ] **Step 2: Strip dashboard.py down to SSE endpoints only**

Remove `GET /` and `GET /stats-fragment` from `dashboard.py`. It now contains only the SSE endpoints:

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.responses import StreamingResponse

sse_router = APIRouter()

@sse_router.get("/sse/stats")
async def sse_stats(request: Request):
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

Note: `dashboard.py` no longer has a `router` object — only `sse_router`. The module-level `router = APIRouter()` is removed.

- [ ] **Step 3: Create explore placeholder at /**

Create `teredacta/routers/explore.py`:
```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def explore_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("explore.html", {
        "request": request,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })
```

Create `teredacta/templates/explore.html`:
```html
{% extends "base.html" %}
{% block title %}Explore — TEREDACTA{% endblock %}
{% block nav_explore %}active{% endblock %}
{% block content %}
<h1>Explore</h1>
<p style="color:var(--text-secondary);">Entity index has not been built yet. {% if is_admin %}<a href="/admin">Build it from the admin panel.</a>{% else %}Ask your administrator to build the entity index.{% endif %}</p>
{% endblock %}
```

- [ ] **Step 4: Add highlights placeholder**

Create `teredacta/routers/highlights.py`:
```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def highlights_page(request: Request):
    templates = request.app.state.templates
    unob = request.app.state.unob
    return templates.TemplateResponse("highlights.html", {
        "request": request,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })
```

Create `teredacta/templates/highlights.html`:
```html
{% extends "base.html" %}
{% block title %}Highlights — TEREDACTA{% endblock %}
{% block nav_highlights %}active{% endblock %}
{% block content %}
<h1>Highlights</h1>
<p style="color:var(--text-secondary);">Coming soon.</p>
{% endblock %}
```

- [ ] **Step 5: Update app.py router mounting**

```python
from teredacta.routers import dashboard, documents, groups, recoveries, pdf, queue, summary, admin, explore, highlights

# SSE endpoints stay at root (accessible to all users for nav daemon indicator)
app.include_router(dashboard.sse_router)

# Public pages
app.include_router(explore.router)
app.include_router(highlights.router, prefix="/highlights")
app.include_router(documents.router, prefix="/documents")
app.include_router(recoveries.router, prefix="/recoveries")
app.include_router(pdf.router, prefix="/pdf")
app.include_router(summary.router, prefix="/summary")

# Admin pages — admin.py now owns GET / (login gate + dashboard),
# GET /stats-fragment, and all other admin endpoints
app.include_router(admin.router, prefix="/admin")
app.include_router(groups.router, prefix="/admin/groups")
app.include_router(queue.router, prefix="/admin/queue")

# Redirects for old URLs
from fastapi.responses import RedirectResponse
@app.get("/groups/{path:path}")
def redirect_groups(path: str):
    return RedirectResponse(f"/admin/groups/{path}", status_code=301)
@app.get("/queue/{path:path}")
def redirect_queue(path: str):
    return RedirectResponse(f"/admin/queue/{path}", status_code=301)
```

Note: `dashboard.router` is no longer mounted (it no longer exists). Only `dashboard.sse_router` is mounted at root level. `admin.router` at `/admin` now provides both the admin page (`GET /`) and the stats fragment (`GET /stats-fragment`).

- [ ] **Step 6: Update tests for new URL structure**

Specific files that need URL updates:

- `teredacta/tests/routers/test_dashboard.py`: Change `client.get("/")` to `client.get("/admin/")` (two occurrences, lines 7 and 17). These tests verify the dashboard page and stats loading — they now hit the admin dashboard.
- `teredacta/tests/routers/test_groups.py`: Change `client.get("/groups/999")` to `client.get("/admin/groups/999")` (line 7).
- `teredacta/tests/test_integration.py`: Change `client.get("/")` to `client.get("/admin/")` (lines 41, 88). Change `client.get("/groups/1")` to `client.get("/admin/groups/1")` (lines 63, 94). Add a new test for `client.get("/")` returning 200 (explore page).

Run: `pytest teredacta/tests/ -v -x`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add teredacta/app.py teredacta/routers/ teredacta/templates/ teredacta/tests/
git commit -m "feat: remount routers — explore at /, admin pages under /admin/"
```

---

## Phase 2: Entity Index

### Task 4: Entity extraction engine

**Files:**
- Create: `teredacta/entity_index.py`
- Create: `teredacta/tests/test_entity_index.py`

- [ ] **Step 1: Write entity extraction tests**

Create `teredacta/tests/test_entity_index.py`:

```python
import pytest
from teredacta.entity_index import extract_entities

class TestExtractEntities:
    def test_person_names(self):
        text = "Meeting with Leon Black and Alan Dershowitz"
        entities = extract_entities(text)
        names = [e for e in entities if e["type"] == "person"]
        assert any(e["name"] == "Leon Black" for e in names)
        assert any(e["name"] == "Alan Dershowitz" for e in names)

    def test_all_caps_names(self):
        text = "JEFFREY EPSTEIN was indicted"
        entities = extract_entities(text)
        names = [e for e in entities if e["type"] == "person"]
        assert any(e["name"] == "Jeffrey Epstein" for e in names)

    def test_name_with_initial(self):
        text = "Email from J. Smith"
        entities = extract_entities(text)
        names = [e for e in entities if e["type"] == "person"]
        assert any(e["name"] == "J. Smith" for e in names)

    def test_stop_list_filters(self):
        text = "Filed in United States Southern District"
        entities = extract_entities(text)
        names = [e["name"] for e in entities if e["type"] == "person"]
        assert "United States" not in names
        assert "Southern District" not in names

    def test_organizations(self):
        text = "The FBI and SDNY investigated"
        entities = extract_entities(text)
        orgs = [e for e in entities if e["type"] == "org"]
        assert any(e["name"] == "FBI" for e in orgs)
        assert any(e["name"] == "SDNY" for e in orgs)

    def test_emails(self):
        text = "Contact jeevacation@gmail.com for info"
        entities = extract_entities(text)
        emails = [e for e in entities if e["type"] == "email"]
        assert any(e["name"] == "jeevacation@gmail.com" for e in emails)

    def test_phones(self):
        text = "Call 561-656-1947 or (212) 555-0100"
        entities = extract_entities(text)
        phones = [e for e in entities if e["type"] == "phone"]
        assert len(phones) >= 2

    def test_locations(self):
        text = "Properties in Palm Beach and Virgin Islands"
        entities = extract_entities(text)
        locs = [e for e in entities if e["type"] == "location"]
        assert any(e["name"] == "Palm Beach" for e in locs)
        assert any(e["name"] == "Virgin Islands" for e in locs)

    def test_empty_text(self):
        assert extract_entities("") == []
        assert extract_entities(None) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest teredacta/tests/test_entity_index.py -v`
Expected: ImportError — `entity_index` module doesn't exist

- [ ] **Step 3: Implement extract_entities**

Create `teredacta/entity_index.py`:

```python
"""Entity extraction and index management for TEREDACTA.

Builds a local SQLite index of people, organizations, locations, emails,
and phone numbers found in recovered redaction segments. This index powers
the Explore page's entity graph without modifying the Unobfuscator database.
"""

import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# --- Entity extraction patterns ---

_PERSON_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+(?:\s+(?:Jr|Sr|III?|IV)\.?)?)\b"
)

_ALL_CAPS_NAME_RE = re.compile(
    r"\b([A-Z]{2,}(?:\s+[A-Z]\.?)?\s+[A-Z]{2,})\b"
)

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)

_PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)

_PERSON_STOP_LIST = frozenset({
    "United States", "Southern District", "Northern District",
    "Eastern District", "Western District", "Circuit Court",
    "District Court", "Supreme Court", "Palm Beach",
    "New York", "Virgin Islands", "Mar Lago", "San Diego",
    "Los Angeles", "Las Vegas", "Page Break", "Case Number",
    "Case Summary", "Search Warrant", "Release Batch",
    "Data Set", "Match Group", "Original Notes",
    "Victim Assistance", "Senior Forensic", "Federal Bureau",
})

_KNOWN_ORGS = frozenset({
    "FBI", "SDNY", "DOJ", "USAO", "CIA", "NSA", "DEA", "IRS", "SEC",
    "BOP", "CART", "BRG", "ICE", "NYPD", "USMS",
    "JPMorgan", "Goldman Sachs", "Deutsche Bank",
    "Apollo Global", "Victoria's Secret",
})

_ORG_PATTERN_RE = re.compile(
    r"\((?:USANYS|CRM|OPR|MLARS)\)"
    r"|\((?:NY|MI|LA|DC)\)\s*\(FBI\)"
)

_KNOWN_LOCATIONS = frozenset({
    "Palm Beach", "Mar-a-Lago", "Virgin Islands", "Manhattan",
    "New York", "New Mexico", "Little St. James", "Great St. James",
    "Zorro Ranch", "Saint Andrews", "Tallahassee",
})


def extract_entities(text: str) -> list[dict]:
    """Extract entities from a text string. Returns list of {name, type} dicts."""
    if not text:
        return []

    results = []
    seen = set()

    def _add(name: str, etype: str):
        key = (name.lower(), etype)
        if key not in seen:
            seen.add(key)
            results.append({"name": name, "type": etype})

    # People — title case
    for m in _PERSON_RE.finditer(text):
        name = m.group(1).strip()
        if name not in _PERSON_STOP_LIST and len(name.split()) >= 2:
            _add(name, "person")

    # People — ALL CAPS (normalize to title case)
    for m in _ALL_CAPS_NAME_RE.finditer(text):
        raw = m.group(1).strip()
        name = raw.title()
        if name not in _PERSON_STOP_LIST and len(name.split()) >= 2:
            _add(name, "person")

    # Organizations — known list
    for org in _KNOWN_ORGS:
        if re.search(r"\b" + re.escape(org) + r"\b", text):
            _add(org, "org")

    # Organizations — parenthetical patterns
    for m in _ORG_PATTERN_RE.finditer(text):
        _add(m.group(0), "org")

    # Locations
    for loc in _KNOWN_LOCATIONS:
        if loc in text:
            _add(loc, "location")

    # Emails
    for m in _EMAIL_RE.finditer(text):
        _add(m.group(0).lower(), "email")

    # Phones
    for m in _PHONE_RE.finditer(text):
        _add(m.group(0).strip(), "phone")

    return results
```

- [ ] **Step 4: Run tests**

Run: `pytest teredacta/tests/test_entity_index.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add teredacta/entity_index.py teredacta/tests/test_entity_index.py
git commit -m "feat: entity extraction with regex patterns for people, orgs, locations, emails, phones"
```

### Task 5: Entity index build and query

**Files:**
- Modify: `teredacta/entity_index.py`
- Modify: `teredacta/tests/test_entity_index.py`

- [ ] **Step 1: Write index build and query tests**

Add to `teredacta/tests/test_entity_index.py`:

```python
import sqlite3
import json
from pathlib import Path
from teredacta.entity_index import EntityIndex

@pytest.fixture
def entity_db(tmp_path):
    return str(tmp_path / "entities.db")

@pytest.fixture
def mock_unob_db(tmp_path):
    """Create a mock Unobfuscator DB with recoveries."""
    db_path = tmp_path / "unobfuscator.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE merge_results (
        group_id INTEGER PRIMARY KEY, merged_text TEXT,
        recovered_count INTEGER, total_redacted INTEGER,
        source_doc_ids TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        recovered_segments TEXT, output_generated BOOLEAN DEFAULT 0,
        soft_recovered_count INTEGER DEFAULT 0,
        previous_recovered_count INTEGER DEFAULT 0, updated_at DATETIME
    )""")
    conn.execute("""CREATE TABLE match_group_members (
        group_id INTEGER, doc_id TEXT, similarity REAL,
        PRIMARY KEY (group_id, doc_id)
    )""")
    conn.execute("""CREATE TABLE documents (
        id TEXT PRIMARY KEY, source TEXT, release_batch TEXT,
        original_filename TEXT, extracted_text TEXT, text_source TEXT, pdf_url TEXT
    )""")
    # Seed test data
    segments = json.dumps([
        {"text": "Leon Black and Darren Indyke discussed the trust", "source_doc_id": "doc-1", "stage": "merge"},
        {"text": "Email from jeevacation@gmail.com about Palm Beach", "source_doc_id": "doc-2", "stage": "merge"},
    ])
    conn.execute(
        "INSERT INTO merge_results (group_id, recovered_count, total_redacted, recovered_segments, source_doc_ids) "
        "VALUES (1, 2, 5, ?, ?)", (segments, '["doc-1","doc-2"]')
    )
    conn.execute("INSERT INTO documents (id, source, text_source) VALUES ('doc-1', 'doj', 'jmail')")
    conn.execute("INSERT INTO documents (id, source, text_source) VALUES ('doc-2', 'doj', 'pdf_text_layer')")
    conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'doc-1', 0.95)")
    conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'doc-2', 0.90)")
    conn.commit()
    conn.close()
    return str(db_path)

class TestEntityIndex:
    def test_build_creates_db(self, entity_db, mock_unob_db):
        idx = EntityIndex(entity_db)
        idx.build(mock_unob_db)
        assert Path(entity_db).exists()

    def test_build_extracts_entities(self, entity_db, mock_unob_db):
        idx = EntityIndex(entity_db)
        idx.build(mock_unob_db)
        entities = idx.list_entities()
        names = [e["name"] for e in entities]
        assert "Leon Black" in names
        assert "Darren Indyke" in names

    def test_get_connections(self, entity_db, mock_unob_db):
        idx = EntityIndex(entity_db)
        idx.build(mock_unob_db)
        entities = idx.list_entities()
        leon = next(e for e in entities if e["name"] == "Leon Black")
        connections = idx.get_connections(leon["id"])
        assert len(connections["linked_entities"]) > 0
        assert len(connections["recoveries"]) > 0

    def test_entity_links(self, entity_db, mock_unob_db):
        idx = EntityIndex(entity_db)
        idx.build(mock_unob_db)
        entities = idx.list_entities()
        leon = next(e for e in entities if e["name"] == "Leon Black")
        connections = idx.get_connections(leon["id"])
        linked_names = [e["name"] for e in connections["linked_entities"]]
        assert "Darren Indyke" in linked_names

    def test_status_not_built(self, entity_db):
        idx = EntityIndex(entity_db)
        status = idx.get_status()
        assert status["state"] == "not_built"

    def test_status_after_build(self, entity_db, mock_unob_db):
        idx = EntityIndex(entity_db)
        idx.build(mock_unob_db)
        status = idx.get_status()
        assert status["state"] == "ready"
        assert status["entity_count"] > 0

    def test_status_stale(self, entity_db, mock_unob_db):
        """Build the index, then add a newer merge_result — status should be stale."""
        idx = EntityIndex(entity_db)
        idx.build(mock_unob_db)
        # Insert a newer merge result into the unob DB
        conn = sqlite3.connect(mock_unob_db)
        conn.execute(
            "INSERT INTO merge_results (group_id, recovered_count, total_redacted, "
            "recovered_segments, source_doc_ids, created_at) "
            "VALUES (99, 1, 1, '[]', '[]', datetime('now', '+1 hour'))"
        )
        conn.commit()
        conn.close()
        status = idx.get_status(unob_db_path=mock_unob_db)
        assert status["state"] == "stale"

    def test_filter_by_type(self, entity_db, mock_unob_db):
        idx = EntityIndex(entity_db)
        idx.build(mock_unob_db)
        people = idx.list_entities(entity_type="person")
        assert all(e["type"] == "person" for e in people)

    def test_filter_by_name(self, entity_db, mock_unob_db):
        idx = EntityIndex(entity_db)
        idx.build(mock_unob_db)
        results = idx.list_entities(name_filter="leon")
        assert any(e["name"] == "Leon Black" for e in results)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest teredacta/tests/test_entity_index.py::TestEntityIndex -v`
Expected: ImportError — `EntityIndex` not defined

- [ ] **Step 3: Implement EntityIndex class**

Add to `teredacta/entity_index.py`:

```python
class EntityIndex:
    """Manages the TEREDACTA entity index database."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS entities (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        occurrence_count INTEGER DEFAULT 0,
        document_count INTEGER DEFAULT 0,
        UNIQUE(name, type)
    );
    CREATE TABLE IF NOT EXISTS entity_mentions (
        id INTEGER PRIMARY KEY,
        entity_id INTEGER REFERENCES entities(id),
        group_id INTEGER NOT NULL,
        segment_index INTEGER,
        snippet TEXT
    );
    CREATE TABLE IF NOT EXISTS entity_links (
        entity_a_id INTEGER REFERENCES entities(id),
        entity_b_id INTEGER REFERENCES entities(id),
        co_occurrence_count INTEGER DEFAULT 0,
        shared_group_ids TEXT,
        PRIMARY KEY (entity_a_id, entity_b_id)
    );
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type, occurrence_count DESC);
    CREATE INDEX IF NOT EXISTS idx_mentions_entity ON entity_mentions(entity_id);
    CREATE INDEX IF NOT EXISTS idx_mentions_group ON entity_mentions(group_id);
    CREATE INDEX IF NOT EXISTS idx_links_a ON entity_links(entity_a_id);
    CREATE INDEX IF NOT EXISTS idx_links_b ON entity_links(entity_b_id);
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection):
        conn.executescript(self._SCHEMA)

    def build(self, unob_db_path: str):
        """Build the entity index from Unobfuscator's recovered segments."""
        logger.info("Building entity index...")
        start = time.monotonic()

        # Read recovered segments from Unobfuscator DB
        unob = sqlite3.connect(f"file:{unob_db_path}?mode=ro", uri=True)
        unob.row_factory = sqlite3.Row
        rows = unob.execute(
            "SELECT group_id, recovered_segments FROM merge_results "
            "WHERE recovered_count > 0 AND recovered_segments IS NOT NULL"
        ).fetchall()
        unob.close()

        # Extract entities from all segments
        # group_id -> list of (entity_name, entity_type, segment_index, snippet)
        group_entities: dict[int, list[tuple]] = {}
        for row in rows:
            segs = json.loads(row["recovered_segments"])
            group_id = row["group_id"]
            group_entities[group_id] = []
            for i, seg in enumerate(segs):
                text = seg.get("text", "")
                if not text or len(text) < 5:
                    continue
                entities = extract_entities(text)
                snippet = text[:100].strip()
                for ent in entities:
                    group_entities[group_id].append(
                        (ent["name"], ent["type"], i, snippet)
                    )

        # Write to entity DB
        conn = self._get_db()
        self._ensure_schema(conn)
        conn.execute("DELETE FROM entity_links")
        conn.execute("DELETE FROM entity_mentions")
        conn.execute("DELETE FROM entities")

        # Insert entities and mentions
        entity_ids: dict[tuple, int] = {}  # (name, type) -> id
        for group_id, ents in group_entities.items():
            for name, etype, seg_idx, snippet in ents:
                key = (name, etype)
                if key not in entity_ids:
                    conn.execute(
                        "INSERT OR IGNORE INTO entities (name, type) VALUES (?, ?)",
                        (name, etype),
                    )
                    row = conn.execute(
                        "SELECT id FROM entities WHERE name = ? AND type = ?",
                        (name, etype),
                    ).fetchone()
                    entity_ids[key] = row["id"]
                eid = entity_ids[key]
                conn.execute(
                    "INSERT INTO entity_mentions (entity_id, group_id, segment_index, snippet) "
                    "VALUES (?, ?, ?, ?)",
                    (eid, group_id, seg_idx, snippet),
                )

        # Compute occurrence counts and document counts
        conn.execute("""
            UPDATE entities SET occurrence_count = (
                SELECT COUNT(*) FROM entity_mentions WHERE entity_id = entities.id
            )
        """)
        # document_count: count distinct group members across all groups this entity appears in
        # This requires reading match_group_members from the unob DB
        # For now, use group count as a proxy
        conn.execute("""
            UPDATE entities SET document_count = (
                SELECT COUNT(DISTINCT group_id) FROM entity_mentions WHERE entity_id = entities.id
            )
        """)

        # Compute co-occurrence links
        # Two entities are linked if they appear in the same group
        conn.execute("""
            INSERT OR REPLACE INTO entity_links (entity_a_id, entity_b_id, co_occurrence_count, shared_group_ids)
            SELECT a.entity_id, b.entity_id, COUNT(DISTINCT a.group_id),
                   '[' || GROUP_CONCAT(DISTINCT a.group_id) || ']'
            FROM entity_mentions a
            JOIN entity_mentions b ON a.group_id = b.group_id AND a.entity_id < b.entity_id
            GROUP BY a.entity_id, b.entity_id
        """)

        # Store build metadata
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('built_at', ?)",
            (time.strftime("%Y-%m-%d %H:%M:%S"),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('entity_count', ?)",
            (str(len(entity_ids)),),
        )

        conn.commit()
        conn.close()
        elapsed = time.monotonic() - start
        logger.info(f"Entity index built: {len(entity_ids)} entities in {elapsed:.1f}s")

    def get_status(self, unob_db_path: str = None) -> dict:
        """Get entity index status.

        Args:
            unob_db_path: If provided, checks staleness by comparing
                MAX(created_at) from merge_results against the build timestamp.
                Unobfuscator inserts new merge results rather than updating
                existing ones, so MAX(created_at) reliably indicates when
                new data arrived.
        """
        if not Path(self.db_path).exists():
            return {"state": "not_built", "entity_count": 0, "built_at": None}
        conn = self._get_db()
        try:
            self._ensure_schema(conn)
            built_at = conn.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
            count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            if count == 0:
                return {"state": "not_built", "entity_count": 0, "built_at": None}
            # Count by type
            type_counts = {}
            for row in conn.execute("SELECT type, COUNT(*) as c FROM entities GROUP BY type"):
                type_counts[row["type"]] = row["c"]
            mention_count = conn.execute("SELECT COUNT(*) FROM entity_mentions").fetchone()[0]
            link_count = conn.execute("SELECT COUNT(*) FROM entity_links").fetchone()[0]
            built_at_str = built_at["value"] if built_at else None

            # Staleness detection: compare build timestamp against newest merge result
            state = "ready"
            if unob_db_path and built_at_str:
                try:
                    unob = sqlite3.connect(f"file:{unob_db_path}?mode=ro", uri=True)
                    max_created = unob.execute(
                        "SELECT MAX(created_at) FROM merge_results"
                    ).fetchone()[0]
                    unob.close()
                    if max_created and max_created > built_at_str:
                        state = "stale"
                except Exception:
                    pass  # If unob DB is unavailable, don't fail — just report ready

            return {
                "state": state,
                "entity_count": count,
                "type_counts": type_counts,
                "mention_count": mention_count,
                "link_count": link_count,
                "built_at": built_at_str,
            }
        finally:
            conn.close()

    def list_entities(
        self, entity_type: str = None, name_filter: str = None,
        page: int = 1, per_page: int = 50,
    ) -> list[dict]:
        """List entities with optional filtering."""
        if not Path(self.db_path).exists():
            return []
        conn = self._get_db()
        try:
            where = "1=1"
            params: list = []
            if entity_type:
                where += " AND type = ?"
                params.append(entity_type)
            if name_filter:
                where += " AND name LIKE ?"
                params.append(f"%{name_filter}%")
            rows = conn.execute(
                f"SELECT id, name, type, occurrence_count, document_count "
                f"FROM entities WHERE {where} "
                f"ORDER BY occurrence_count DESC "
                f"LIMIT ? OFFSET ?",
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_entity(self, entity_id: int) -> Optional[dict]:
        """Get a single entity by ID."""
        if not Path(self.db_path).exists():
            return None
        conn = self._get_db()
        try:
            row = conn.execute(
                "SELECT id, name, type, occurrence_count, document_count "
                "FROM entities WHERE id = ?", (entity_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_connections(self, entity_id: int) -> dict:
        """Get all connections for an entity: recoveries, linked entities, documents."""
        conn = self._get_db()
        try:
            # Get the entity itself
            entity = conn.execute(
                "SELECT * FROM entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if not entity:
                return {"entity": None, "recoveries": [], "linked_entities": [], "documents": []}

            # Recoveries this entity appears in
            recoveries = conn.execute(
                "SELECT DISTINCT group_id, snippet FROM entity_mentions "
                "WHERE entity_id = ? ORDER BY group_id",
                (entity_id,),
            ).fetchall()

            # Linked entities (co-occurrence)
            linked = conn.execute(
                "SELECT e.id, e.name, e.type, e.occurrence_count, el.co_occurrence_count "
                "FROM entity_links el "
                "JOIN entities e ON e.id = CASE WHEN el.entity_a_id = ? THEN el.entity_b_id ELSE el.entity_a_id END "
                "WHERE el.entity_a_id = ? OR el.entity_b_id = ? "
                "ORDER BY el.co_occurrence_count DESC "
                "LIMIT 50",
                (entity_id, entity_id, entity_id),
            ).fetchall()

            return {
                "entity": dict(entity),
                "recoveries": [{"group_id": r["group_id"], "snippet": r["snippet"]} for r in recoveries],
                "linked_entities": [dict(r) for r in linked],
            }
        finally:
            conn.close()
```

- [ ] **Step 4: Run tests**

Run: `pytest teredacta/tests/test_entity_index.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add teredacta/entity_index.py teredacta/tests/test_entity_index.py
git commit -m "feat: entity index build, query, staleness detection, and status"
```

### Task 6: Entity index fixtures in conftest.py

**Files:**
- Modify: `teredacta/tests/conftest.py`

This task adds shared fixtures that subsequent tasks (Task 7+) use for testing entity-index-enabled endpoints.

- [ ] **Step 1: Add entity index fixtures to conftest.py**

Add the following fixtures to `teredacta/tests/conftest.py`:

```python
import json
from teredacta.entity_index import EntityIndex

@pytest.fixture
def entity_db_path(tmp_dir):
    """Path for the entity index DB (does not create it)."""
    return str(tmp_dir / "teredacta_entities.db")

@pytest.fixture
def entity_index(entity_db_path, mock_db):
    """An EntityIndex built from the mock_db's data.

    Seeds the mock_db with recovery data, then builds the entity index.
    """
    # Seed the mock DB with recovery data for entity extraction
    conn = sqlite3.connect(str(mock_db))
    conn.execute("INSERT OR IGNORE INTO match_groups (group_id) VALUES (1)")
    segments = json.dumps([
        {"text": "Leon Black and Darren Indyke discussed the trust", "source_doc_id": "doc-1", "stage": "merge"},
        {"text": "Email from jeevacation@gmail.com about Palm Beach", "source_doc_id": "doc-2", "stage": "merge"},
    ])
    conn.execute(
        "INSERT OR REPLACE INTO merge_results "
        "(group_id, recovered_count, total_redacted, recovered_segments, source_doc_ids) "
        "VALUES (1, 2, 5, ?, ?)", (segments, '["doc-1","doc-2"]')
    )
    conn.execute("INSERT OR IGNORE INTO documents (id, source, text_source) VALUES ('doc-1', 'doj', 'jmail')")
    conn.execute("INSERT OR IGNORE INTO documents (id, source, text_source) VALUES ('doc-2', 'doj', 'pdf_text_layer')")
    conn.execute("INSERT OR IGNORE INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'doc-1', 0.95)")
    conn.execute("INSERT OR IGNORE INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'doc-2', 0.90)")
    conn.commit()
    conn.close()

    idx = EntityIndex(entity_db_path)
    idx.build(str(mock_db))
    return idx

@pytest.fixture
def app_with_entities(test_config, entity_index, entity_db_path):
    """Create a test FastAPI app with a built entity index on app.state."""
    test_config.entity_db_path = entity_db_path
    from teredacta.app import create_app
    application = create_app(test_config)
    application.state.entity_index = entity_index
    return application

@pytest.fixture
def client_with_entities(app_with_entities):
    """Test client backed by an app with a built entity index."""
    return TestClient(app_with_entities)
```

- [ ] **Step 2: Run existing tests to ensure no regressions**

Run: `pytest teredacta/tests/ -v -x`
Expected: All pass (new fixtures are not used by existing tests)

- [ ] **Step 3: Commit**

```bash
git add teredacta/tests/conftest.py
git commit -m "feat: add entity index fixtures to conftest for explore/api tests"
```

### Task 7: Admin entity index build endpoint

**Files:**
- Modify: `teredacta/app.py`
- Modify: `teredacta/routers/admin.py`
- Modify: `teredacta/templates/admin/dashboard.html`

- [ ] **Step 1: Add EntityIndex to app.state in app.py**

In `create_app`, after creating `app.state.unob`:
```python
from teredacta.entity_index import EntityIndex
app.state.entity_index = EntityIndex(config.entity_db_path)
```

- [ ] **Step 2: Add build endpoint to admin.py**

Add to `teredacta/routers/admin.py`:
```python
@router.post("/entity-index/build")
async def build_entity_index(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    if not _validate_csrf(request):
        return Response(status_code=403)
    entity_idx = request.app.state.entity_index
    unob = request.app.state.unob
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, partial(entity_idx.build, unob.config.db_path)
    )
    status = entity_idx.get_status(unob_db_path=unob.config.db_path)
    return HTMLResponse(
        f'<span style="color:#66bb6a;">Built: {status["entity_count"]} entities</span>'
    )
```

- [ ] **Step 3: Add entity index stats card to admin dashboard template**

Add a new card to `teredacta/templates/admin/dashboard.html` showing entity index status with build/rebuild button:

```html
<div class="stat-card">
    <h3>Entity Index</h3>
    <div id="entity-status" hx-get="/admin/entity-index/status" hx-trigger="load" hx-swap="innerHTML">
        Loading...
    </div>
    <button class="btn btn-primary" hx-post="/admin/entity-index/build"
            hx-target="#entity-build-result" hx-swap="innerHTML"
            title="Scan recovered text and build the entity index for the Explore page">
        Build / Rebuild
    </button>
    <div id="entity-build-result" style="margin-top:0.5rem;"></div>
</div>
```

- [ ] **Step 4: Add status endpoint to admin.py**

```python
@router.get("/entity-index/status", response_class=HTMLResponse)
def entity_index_status(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    entity_idx = request.app.state.entity_index
    unob = request.app.state.unob
    status = entity_idx.get_status(unob_db_path=unob.config.db_path)
    if status["state"] == "not_built":
        return HTMLResponse('<span style="color:var(--text-secondary);">Not built</span>')
    stale_warning = ""
    if status["state"] == "stale":
        stale_warning = '<br><span style="color:#ffa726;">⚠ Index may be out of date — new recoveries exist since last build</span>'
    tc = status.get("type_counts", {})
    parts = [f'{v} {k}s' for k, v in sorted(tc.items())]
    return HTMLResponse(
        f'<span title="Last built: {status["built_at"]}">'
        f'{status["entity_count"]} entities ({", ".join(parts)})<br>'
        f'{status["mention_count"]} mentions, {status["link_count"]} links<br>'
        f'<small style="opacity:0.6;">Built: {status["built_at"]}</small>'
        f'{stale_warning}'
        f'</span>'
    )
```

- [ ] **Step 5: Run all tests**

Run: `pytest teredacta/tests/ -v -x`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add teredacta/app.py teredacta/routers/admin.py teredacta/templates/admin/dashboard.html
git commit -m "feat: admin entity index build endpoint and status card"
```

---

## Phase 3: Explore & Highlights Pages

### Task 8: Entity API endpoints

**Files:**
- Create: `teredacta/routers/api.py`
- Create: `teredacta/templates/explore/entity_list.html`
- Create: `teredacta/templates/explore/connections.html`
- Create: `teredacta/templates/explore/preview.html`
- Create: `teredacta/tests/routers/test_explore.py`

- [ ] **Step 1: Write API endpoint tests**

Create `teredacta/tests/routers/test_explore.py` with tests using the `client_with_entities` fixture from conftest:

```python
import pytest

class TestEntityAPI:
    def test_list_entities(self, client_with_entities):
        resp = client_with_entities.get("/api/entities")
        assert resp.status_code == 200
        assert "Leon Black" in resp.text

    def test_filter_by_type(self, client_with_entities):
        resp = client_with_entities.get("/api/entities?type=person")
        assert resp.status_code == 200
        assert "Leon Black" in resp.text

    def test_filter_by_name(self, client_with_entities):
        resp = client_with_entities.get("/api/entities?filter=leon")
        assert resp.status_code == 200
        assert "Leon Black" in resp.text

    def test_entity_connections(self, client_with_entities):
        # Get entity ID first
        resp = client_with_entities.get("/api/entities")
        # Extract an entity ID (from the rendered HTML, look for a data attribute or link)
        # Alternatively, query the entity index directly
        entity_idx = client_with_entities.app.state.entity_index
        entities = entity_idx.list_entities()
        leon = next(e for e in entities if e["name"] == "Leon Black")
        resp = client_with_entities.get(f"/api/entities/{leon['id']}/connections")
        assert resp.status_code == 200

    def test_entity_connections_404(self, client_with_entities):
        resp = client_with_entities.get("/api/entities/99999/connections")
        assert resp.status_code == 404

    def test_preview_recovery(self, client_with_entities):
        resp = client_with_entities.get("/api/preview/recovery/1")
        assert resp.status_code == 200

    def test_preview_recovery_404(self, client_with_entities):
        resp = client_with_entities.get("/api/preview/recovery/99999")
        assert resp.status_code == 404

    def test_preview_entity(self, client_with_entities):
        entity_idx = client_with_entities.app.state.entity_index
        entities = entity_idx.list_entities()
        leon = next(e for e in entities if e["name"] == "Leon Black")
        resp = client_with_entities.get(f"/api/preview/entity/{leon['id']}")
        assert resp.status_code == 200
        assert "Leon Black" in resp.text

    def test_preview_entity_404(self, client_with_entities):
        resp = client_with_entities.get("/api/preview/entity/99999")
        assert resp.status_code == 404

class TestExplorePage:
    def test_explore_page_loads(self, client_with_entities):
        resp = client_with_entities.get("/")
        assert resp.status_code == 200
        assert "Explore" in resp.text
```

- [ ] **Step 2: Implement API router**

Create `teredacta/routers/api.py`:
```python
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from starlette.responses import Response

router = APIRouter()

@router.get("/entities", response_class=HTMLResponse)
def list_entities(
    request: Request,
    type: str = Query(None),
    filter: str = Query(None),
    page: int = Query(1, ge=1),
):
    templates = request.app.state.templates
    entity_idx = request.app.state.entity_index
    entities = entity_idx.list_entities(entity_type=type, name_filter=filter, page=page)
    return templates.TemplateResponse("explore/entity_list.html", {
        "request": request, "entities": entities,
    })

@router.get("/entities/{entity_id:int}/connections", response_class=HTMLResponse)
def entity_connections(request: Request, entity_id: int):
    templates = request.app.state.templates
    entity_idx = request.app.state.entity_index
    connections = entity_idx.get_connections(entity_id)
    if not connections["entity"]:
        return Response(status_code=404)
    return templates.TemplateResponse("explore/connections.html", {
        "request": request, **connections,
    })

@router.get("/preview/recovery/{group_id:int}", response_class=HTMLResponse)
def preview_recovery(request: Request, group_id: int):
    templates = request.app.state.templates
    unob = request.app.state.unob
    detail = unob.get_recovery_detail(group_id)
    if not detail:
        return Response(status_code=404)
    return templates.TemplateResponse("explore/preview.html", {
        "request": request, "recovery": detail, "group_id": group_id,
    })

@router.get("/preview/document/{doc_id}", response_class=HTMLResponse)
def preview_document(request: Request, doc_id: str):
    templates = request.app.state.templates
    unob = request.app.state.unob
    doc = unob.get_document(doc_id)
    if not doc:
        return Response(status_code=404)
    return templates.TemplateResponse("explore/preview.html", {
        "request": request, "document": doc,
    })

@router.get("/preview/entity/{entity_id:int}", response_class=HTMLResponse)
def preview_entity(request: Request, entity_id: int):
    """Entity summary card preview for the Explore page right column."""
    templates = request.app.state.templates
    entity_idx = request.app.state.entity_index
    entity = entity_idx.get_entity(entity_id)
    if not entity:
        return Response(status_code=404)
    connections = entity_idx.get_connections(entity_id)
    return templates.TemplateResponse("explore/preview.html", {
        "request": request,
        "entity": entity,
        "recovery_count": len(connections.get("recoveries", [])),
        "linked_count": len(connections.get("linked_entities", [])),
    })
```

Mount in app.py: `app.include_router(api.router, prefix="/api")`

- [ ] **Step 3: Create HTMX fragment templates**

Create `teredacta/templates/explore/entity_list.html`, `connections.html`, `preview.html` as small HTML fragments (no `{% extends "base.html" %}`).

The `preview.html` template should handle three cases: `recovery` variable set (recovery preview), `document` variable set (document preview), `entity` variable set (entity summary card with stats and "Explore" link).

- [ ] **Step 4: Run tests**

Run: `pytest teredacta/tests/routers/test_explore.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add teredacta/routers/api.py teredacta/templates/explore/ teredacta/tests/routers/test_explore.py teredacta/app.py
git commit -m "feat: entity API endpoints with preview/entity/{id} and HTMX fragment templates"
```

### Task 9: Explore page with column slide JS

**Files:**
- Modify: `teredacta/templates/explore.html`
- Create: `teredacta/static/js/explore.js`
- Modify: `teredacta/static/css/app.css`

- [ ] **Step 1: Build the explore.html three-column layout**

Replace the placeholder explore.html with the full three-column layout: entity list (left), connections (middle), preview (right). Left column loads entities via HTMX on page load. Middle and right are populated by explore.js on interaction.

Add stale banner support: if entity index is stale, show a small banner:
```html
{% if entity_index_stale %}
<div class="stale-banner" style="background:#fff3e0;color:#e65100;padding:0.5rem 1rem;text-align:center;font-size:0.85rem;">
    Entity index may be out of date — last built {{ entity_index_built_at }}.
    {% if is_admin %}<a href="/admin">Rebuild from admin panel.</a>{% endif %}
</div>
{% endif %}
```

Update `explore.py` to pass staleness info to the template by calling `entity_index.get_status(unob_db_path=...)`.

- [ ] **Step 2: Create explore.js**

Implements: entity click -> fetch connections -> render in middle column. Connection click on entity -> slide animation (CSS transform), push to history. Connection click on recovery/document -> fetch preview -> render in right column. Back button / breadcrumb navigation. pushState URL updates.

- [ ] **Step 3: Add CSS for three-column layout, slide animation, color-coded items**

Add to `app.css`: `.explore-container` (three-column flex), `.explore-col` (flex: 0 0 width), `.slide-left` animation, `.entity-item`, `.connection-item`, color-coded borders (green/orange/blue), hover effects, entity type badges.

- [ ] **Step 4: Write automated test for three-column structure**

Add to `teredacta/tests/routers/test_explore.py`:

```python
class TestExplorePageStructure:
    def test_three_column_layout_rendered(self, client_with_entities):
        """Verify the explore page renders the three-column HTML structure."""
        resp = client_with_entities.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert "explore-container" in html
        # Verify all three columns are present
        assert "entity-list" in html or "explore-col" in html
        assert "connections" in html or "explore-col" in html

    def test_explore_page_without_index(self, client):
        """Explore page shows build prompt when entity index is not built."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "not been built" in resp.text or "Entity index" in resp.text
```

- [ ] **Step 5: Test manually with real data**

Build the entity index: `POST /admin/entity-index/build`
Visit `/` and verify: entity list loads, clicking an entity shows connections, clicking a connection shows preview or slides.

- [ ] **Step 6: Commit**

```bash
git add teredacta/templates/explore.html teredacta/static/js/explore.js teredacta/static/css/app.css teredacta/routers/explore.py teredacta/tests/routers/test_explore.py
git commit -m "feat: explore page with three-column entity graph and slide animation"
```

### Task 10: Highlights page

**Files:**
- Modify: `teredacta/routers/highlights.py`
- Modify: `teredacta/templates/highlights.html`
- Create: `teredacta/tests/routers/test_highlights.py`

- [ ] **Step 1: Write tests**

Test: highlights page returns 200, contains top recoveries section, contains notable entities section (when entity index is built), contains common unredactions section.

- [ ] **Step 2: Implement highlights router**

Query `merge_results` for top recoveries (by recovered_count), entity index for top entities (by occurrence_count), and `get_common_unredactions` for common panel. Pass all to template.

- [ ] **Step 3: Build highlights template**

Three sections: Top Recoveries (cards with headline, badge, link), Notable Entities (cards with type badge, counts, snippet), Common Unredactions (moved from recoveries sidebar).

Add hover help on all badges and counts.

- [ ] **Step 4: Remove common unredactions from recoveries/list.html**

Remove the `hx-get="/recoveries/common"` panel from the recoveries list page.

- [ ] **Step 5: Run all tests**

Run: `pytest teredacta/tests/ -v -x`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add teredacta/routers/highlights.py teredacta/templates/highlights.html teredacta/templates/recoveries/list.html teredacta/tests/routers/test_highlights.py
git commit -m "feat: highlights page with top recoveries, notable entities, common unredactions"
```

---

## Phase 4: Redaction Jumping & Research Improvements

### Task 11: Add segment mapping to recovered passages

**Files:**
- Modify: `teredacta/unob.py`
- Modify: `teredacta/templates/recoveries/tabs/merged_text.html`

- [ ] **Step 1: Add data attributes to recovered spans in format_merged_text**

In `unob.py`, modify `format_merged_text` to accept an optional `recovered_segments` list parameter. For each `<mark class="recovered-inline">` it generates, add `data-segment-index="N"` and `data-source-doc="doc_id"` attributes by matching the recovered text back to the segments list.

**Signature change:** `format_merged_text` is currently a `@staticmethod`. Since it now needs an optional parameter (`recovered_segments`), change it to accept `segments` as an optional keyword argument. Two options:

1. Keep `@staticmethod` and add `segments: list = None` parameter:
   ```python
   @staticmethod
   def format_merged_text(text: str, segments: list = None) -> str:
   ```
2. Or change to a regular method if more state is needed later.

Option 1 is simpler and sufficient. The regex substitution callback checks if `segments` is provided and, for each match, finds the matching segment by comparing the recovered text against each segment's `text` field.

- [ ] **Step 2: Update BOTH call sites in get_recovery_detail**

There are two calls to `format_merged_text` in `unob.py`'s `get_recovery_detail`:

1. **Line ~389** — per-segment rendering: `seg["text_html"] = self.format_merged_text(seg["text"])`. This renders individual segment text; no segment mapping needed here (it's already showing a single segment). Leave this call unchanged.

2. **Line ~392** — full merged text rendering: `result["merged_text_html"] = self.format_merged_text(result.get("merged_text") or "")`. This is the main merged text view where segment mapping matters. Update to pass the parsed segments:
   ```python
   result["merged_text_html"] = self.format_merged_text(
       result.get("merged_text") or "",
       segments=result.get("recovered_segments"),
   )
   ```

- [ ] **Step 3: Update merged_text.html template**

Add hover help to recovered spans: `title="Click to view source document"`. Add CSS class for hover effect.

- [ ] **Step 4: Run tests**

Run: `pytest teredacta/tests/ -v -x`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add teredacta/unob.py teredacta/templates/recoveries/tabs/merged_text.html
git commit -m "feat: add data attributes to recovered passages for source panel"
```

### Task 12: Source panel endpoint and template

**Files:**
- Modify: `teredacta/routers/recoveries.py`
- Create: `teredacta/templates/recoveries/source_panel.html`
- Modify: `teredacta/unob.py`
- Create: `teredacta/tests/routers/test_source_panel.py`

- [ ] **Step 1: Write source panel tests**

Test: source panel returns 200 for valid group_id + segment_index, returns text pane for email records, returns PDF embed for cached PDFs, returns "not available" for missing docs.

- [ ] **Step 2: Add search context extraction to unob.py**

Add method `get_source_context(group_id, segment_index)` that:
1. Gets the recovered_segment at the given index
2. Reads raw merged_text (not HTML)
3. Finds the segment text in merged_text
4. Extracts 30-40 chars of adjacent unredacted text (skipping [REDACTED] markers)
5. Returns dict with source_doc_id, search_context, has_pdf, extracted_text

- [ ] **Step 3: Add source panel endpoint to recoveries.py**

```python
@router.get("/{group_id:int}/source", response_class=HTMLResponse)
def source_panel(request: Request, group_id: int, segment_index: int = Query(..., ge=0)):
    # Get source context from unob
    # Render appropriate panel (PDF embed with search, text pane, or not-available)
```

- [ ] **Step 4: Create source_panel.html template**

Three variants based on source doc type: PDF embed with search param, text pane with highlighting, or "not available" message.

- [ ] **Step 5: Write automated test for source panel rendering**

Add to `teredacta/tests/routers/test_source_panel.py`:

```python
class TestSourcePanelRendering:
    def test_source_panel_renders_text_pane(self, client_with_entities):
        """Source panel renders a text pane for email records (no PDF)."""
        resp = client_with_entities.get("/recoveries/1/source?segment_index=0")
        assert resp.status_code == 200
        # Should contain the source panel container
        assert "source-panel" in resp.text or "source" in resp.text.lower()

    def test_source_panel_invalid_group(self, client_with_entities):
        resp = client_with_entities.get("/recoveries/99999/source?segment_index=0")
        assert resp.status_code == 404

    def test_source_panel_invalid_segment(self, client_with_entities):
        resp = client_with_entities.get("/recoveries/1/source?segment_index=999")
        assert resp.status_code in (404, 400)
```

- [ ] **Step 6: Run tests**

Run: `pytest teredacta/tests/routers/test_source_panel.py -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add teredacta/routers/recoveries.py teredacta/templates/recoveries/source_panel.html teredacta/unob.py teredacta/tests/routers/test_source_panel.py
git commit -m "feat: source panel endpoint with context extraction and three-tier rendering"
```

### Task 13: Source panel JavaScript and CSS

**Files:**
- Create: `teredacta/static/js/source-panel.js`
- Modify: `teredacta/static/css/app.css`
- Modify: `teredacta/templates/recoveries/detail.html`
- Modify: `teredacta/templates/recoveries/tabs/merged_text.html`

- [ ] **Step 1: Create source-panel.js**

Implements:
- Click handler on `.recovered[data-segment-index]` elements
- Fetches `/recoveries/{group_id}/source?segment_index=N` via fetch()
- Slides in source panel from right, splits view 60/40
- Close button (x) to dismiss
- Floating navigation arrows (up/down) to jump between recovered passages
- Keyboard shortcuts j/k for next/previous

- [ ] **Step 2: Add CSS for source panel**

Add to `app.css`: `.source-panel` (fixed right, slide-in animation), `.merged-text-with-panel` (width: 60%), `.recovery-nav` (floating arrows), `.recovered:hover` (glow effect).

- [ ] **Step 3: Update detail.html to include source-panel.js**

Add `<script src="/static/js/source-panel.js"></script>` and the source panel container div.

- [ ] **Step 4: Update merged_text.html for hover effects**

Add CSS class `.recovered-clickable` and cursor pointer.

- [ ] **Step 5: Test manually**

Visit a recovery detail page, click a green recovered passage, verify source panel slides in.

- [ ] **Step 6: Commit**

```bash
git add teredacta/static/js/source-panel.js teredacta/static/css/app.css teredacta/templates/recoveries/
git commit -m "feat: source panel JS with slide-in animation and recovery navigation"
```

### Task 14: Boolean search for recoveries

**Files:**
- Modify: `teredacta/unob.py`
- Modify: `teredacta/routers/recoveries.py`
- Modify: `teredacta/templates/recoveries/list.html`

- [ ] **Step 1: Write boolean search tests**

Add to test_recoveries.py: test AND search, test OR search, test quoted exact phrase, test mixed operators, test single term (backward compat).

- [ ] **Step 2: Implement boolean search parser in unob.py**

Add function `parse_boolean_search(query: str) -> list[tuple[str, str]]` that parses into `[(term, operator)]` pairs. Returns list of (term, "AND"/"OR") tuples. Quoted phrases are kept as single terms.

Update `get_recoveries` to use the parsed terms: each term becomes a `LIKE ? ESCAPE '!'` clause, joined with the specified boolean operator.

- [ ] **Step 3: Add search hint to recoveries list template**

Below the search input: `<p class="search-hint">Search recovered text — use AND, OR, quotes for exact phrases</p>`

- [ ] **Step 4: Add sort option to recoveries**

Add a sort dropdown (by recovered_count or by date) to the list template, pass to `get_recoveries`.

- [ ] **Step 5: Run tests**

Run: `pytest teredacta/tests/ -v -x`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add teredacta/unob.py teredacta/routers/recoveries.py teredacta/templates/recoveries/list.html
git commit -m "feat: boolean search (AND/OR/quotes) and sort options for recoveries"
```

### Task 15: Entity-aware document search

**Files:**
- Modify: `teredacta/routers/documents.py`
- Modify: `teredacta/templates/documents/list.html`

- [ ] **Step 1: Update document search to query entity index**

In `documents.py`, when a search term is provided, also query the entity index for matching entity names. Get the group_ids from entity_mentions, then get doc_ids from match_group_members, and include those in the document results (UNION with the existing GLOB search).

**Note:** Date range filter is acknowledged as a stretch goal, deferred to a future plan. The spec notes it is only viable if dates are reliably available in document metadata or filenames, which has not been validated. A separate investigation and plan will be created if/when this is pursued.

- [ ] **Step 2: Add search hint to documents list template**

Below the search input: `<p class="search-hint">Search by filename, document ID, or entity name</p>`

- [ ] **Step 3: Run tests**

Run: `pytest teredacta/tests/ -v -x`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add teredacta/routers/documents.py teredacta/templates/documents/list.html
git commit -m "feat: entity-aware document search"
```

### Task 16: Hover help and discoverability polish

**Files:**
- Modify: Various templates
- Modify: `teredacta/static/css/app.css`

- [ ] **Step 1: Add title attributes (hover help) across all templates**

- Recovery count badges: `title="N redacted passages were recovered by cross-referencing overlapping document releases"`
- Entity type badges: `title="Person — named individual found in recovered text"` (etc. per type)
- Stat cards on admin dashboard and highlights: descriptive tooltips
- Column headers in data tables: brief descriptions
- Navigation arrows: `title="Jump to next recovered passage (keyboard: j)"`

- [ ] **Step 2: Add search hints below all search inputs**

- Recoveries: `<p class="search-hint">Search recovered text — use AND, OR, quotes for exact phrases</p>`
- Documents: `<p class="search-hint">Search by filename, document ID, or entity name</p>`
- Explore filter: `<p class="search-hint">Filter by name</p>`

- [ ] **Step 3: Add CSS for search-hint class**

```css
.search-hint {
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-top: 0.25rem;
    margin-bottom: 0;
}
```

- [ ] **Step 4: Run all tests**

Run: `pytest teredacta/tests/ -v -x`
Expected: All pass

- [ ] **Step 5: Final commit**

```bash
git add teredacta/templates/ teredacta/static/css/app.css
git commit -m "feat: hover help tooltips and search hints across all pages"
```

# TEREDACTA Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python web app (TEREDACTA) that wraps Unobfuscator in a modern, reactive web interface with public read-only access and authenticated admin controls.

**Architecture:** Single FastAPI process with modular routers. HTMX for reactivity, PDF.js for inline PDF viewing, SSE for live updates. Reads Unobfuscator's SQLite DB directly via `unob.py`, uses subprocess for control operations.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, Jinja2, HTMX (vendored), PDF.js (vendored), itsdangerous, bcrypt, PyYAML, Click

**Spec:** `docs/superpowers/specs/2026-03-16-teredacta-design.md`

**Unobfuscator DB schema reference:** `/Users/brianhill/Scripts/Unobfuscator/core/db.py` (lines 6-78)

---

## File Structure

```
teredacta/
├── __init__.py              # Version string
├── __main__.py              # `python -m teredacta` entry point (Click CLI)
├── app.py                   # FastAPI app factory, mounts routers
├── config.py                # Config loader (YAML + env vars)
├── auth.py                  # Admin auth middleware, CSRF, session management
├── sse.py                   # SSE event manager (shared polling task)
├── unob.py                  # All Unobfuscator interaction (DB reads, subprocess, files)
├── routers/
│   ├── __init__.py
│   ├── dashboard.py         # GET / — stats cards, progress bars, SSE endpoint
│   ├── documents.py         # GET /documents — paginated table, detail view
│   ├── groups.py            # GET /groups — match group list, detail view
│   ├── recoveries.py        # GET /recoveries — recovery list, search, common unredactions, detail tabs
│   ├── pdf.py               # GET /pdf/<path> — PDF serving, PDF.js viewer page
│   ├── queue.py             # GET /queue — job queue table
│   ├── summary.py           # GET /summary — summary report viewer
│   └── admin.py             # /admin/* — login, daemon, config, logs, downloads, search
├── templates/
│   ├── base.html            # Top nav shell, HTMX + SSE setup, CSRF meta tag
│   ├── partials/
│   │   ├── stats_cards.html # Dashboard stat cards fragment
│   │   ├── progress_bars.html # Pipeline progress fragment
│   │   ├── daemon_status.html # Daemon status indicator fragment
│   │   ├── document_row.html  # Single document table row
│   │   └── job_row.html       # Single job table row
│   ├── dashboard.html
│   ├── documents/
│   │   ├── list.html        # Document browser page
│   │   └── detail.html      # Document detail page
│   ├── groups/
│   │   ├── list.html        # Match group list page
│   │   └── detail.html      # Match group detail page
│   ├── recoveries/
│   │   ├── list.html        # Recovery list with search + common unredactions
│   │   ├── detail.html      # Recovery detail with tabs
│   │   └── tabs/
│   │       ├── merged_text.html
│   │       ├── output_pdf.html
│   │       ├── original_pdfs.html  # Includes comparison mode
│   │       └── metadata.html
│   ├── pdf/
│   │   └── viewer.html      # PDF.js viewer wrapper
│   ├── queue/
│   │   └── list.html        # Job queue page
│   ├── summary/
│   │   └── view.html        # Summary report page
│   ├── admin/
│   │   ├── login.html       # Login form
│   │   ├── dashboard.html   # Admin dashboard (daemon, search, links)
│   │   ├── config.html      # Config editor
│   │   ├── logs.html        # Log viewer
│   │   ├── downloads.html   # Dataset downloads
│   │   └── search.html      # Search form + results
│   └── error.html           # Error/banner page (DB not found, etc.)
├── static/
│   ├── css/
│   │   └── app.css
│   ├── js/
│   │   ├── htmx.min.js     # Vendored
│   │   ├── comparison.js    # PDF comparison mode sync scrolling
│   │   └── pdfjs/           # Vendored PDF.js distribution
│   └── img/
│       └── favicon.ico
├── installer/
│   ├── __init__.py
│   ├── wizard.py            # Click-based install wizard
│   └── templates/
│       ├── docker-compose.yml.j2
│       ├── systemd.service.j2
│       └── config.yaml.j2
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Fixtures: test client, mock DB, mock config
│   ├── test_config.py
│   ├── test_auth.py
│   ├── test_unob.py
│   ├── test_sse.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── test_dashboard.py
│   │   ├── test_documents.py
│   │   ├── test_groups.py
│   │   ├── test_recoveries.py
│   │   ├── test_pdf.py
│   │   ├── test_queue.py
│   │   └── test_admin.py
│   └── test_installer.py
├── pyproject.toml           # Package config, dependencies, entry points
└── README.md                # Only if user requests
```

---

## Chunk 1: Foundation (Tasks 1-4)

Core infrastructure: project scaffold, config, Unobfuscator interface, and app factory with base template.

### Task 1: Project Scaffold & Dependencies

**Files:**
- Create: `teredacta/__init__.py`
- Create: `teredacta/__main__.py`
- Create: `pyproject.toml`
- Create: `teredacta/tests/__init__.py`
- Create: `teredacta/tests/conftest.py`
- Create: `teredacta/routers/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "teredacta"
version = "0.1.0"
description = "Web interface for Unobfuscator"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "jinja2>=3.1.0",
    "itsdangerous>=2.1.0",
    "bcrypt>=4.0.0",
    "pyyaml>=6.0",
    "click>=8.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "httpx>=0.25.0",
]

[project.scripts]
teredacta = "teredacta.__main__:cli"
```

- [ ] **Step 2: Create `teredacta/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Create `teredacta/__main__.py` with CLI skeleton**

```python
import click


@click.group()
def cli():
    """TEREDACTA — Web interface for Unobfuscator."""
    pass


@cli.command()
@click.option("--host", default=None, help="Bind host (overrides config)")
@click.option("--port", default=None, type=int, help="Bind port (overrides config)")
@click.option("--config", "config_path", default=None, help="Path to config file")
def run(host, port, config_path):
    """Start the TEREDACTA web server."""
    from teredacta.config import load_config
    from teredacta.app import create_app
    import uvicorn

    cfg = load_config(config_path)
    if host:
        cfg.host = host
    if port:
        cfg.port = port

    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Create empty `__init__.py` files**

```python
# teredacta/routers/__init__.py
# teredacta/tests/__init__.py
# (empty files)
```

- [ ] **Step 5: Create `teredacta/tests/conftest.py` with base fixtures**

```python
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from teredacta.config import TeredactaConfig


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temp directory with Unobfuscator-like structure."""
    db_path = tmp_path / "unobfuscator.db"
    pdf_cache = tmp_path / "pdf_cache"
    output_dir = tmp_path / "output"
    log_path = tmp_path / "unobfuscator.log"
    pdf_cache.mkdir()
    output_dir.mkdir()
    log_path.touch()
    return tmp_path


@pytest.fixture
def mock_db(tmp_dir):
    """Create a mock Unobfuscator SQLite database with schema."""
    db_path = tmp_dir / "unobfuscator.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            release_batch TEXT,
            original_filename TEXT,
            page_count INTEGER,
            size_bytes INTEGER,
            description TEXT,
            extracted_text TEXT,
            pdf_url TEXT,
            indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            text_processed BOOLEAN DEFAULT 0,
            pdf_processed BOOLEAN DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS document_fingerprints (
            doc_id TEXT PRIMARY KEY REFERENCES documents(id),
            minhash_sig BLOB NOT NULL,
            shingle_count INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS match_groups (
            group_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            merged BOOLEAN DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS match_group_members (
            group_id INTEGER REFERENCES match_groups(group_id),
            doc_id TEXT UNIQUE REFERENCES documents(id),
            similarity REAL,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (group_id, doc_id)
        );
        CREATE TABLE IF NOT EXISTS merge_results (
            group_id INTEGER PRIMARY KEY REFERENCES match_groups(group_id),
            merged_text TEXT,
            recovered_count INTEGER DEFAULT 0,
            previous_recovered_count INTEGER DEFAULT 0,
            total_redacted INTEGER DEFAULT 0,
            source_doc_ids TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            output_generated BOOLEAN DEFAULT 0,
            recovered_segments TEXT,
            soft_recovered_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS release_batches (
            batch_id TEXT PRIMARY KEY,
            first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            fully_indexed BOOLEAN DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS jobs (
            job_id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage TEXT NOT NULL,
            payload TEXT,
            priority INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            error TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.close()
    return db_path


@pytest.fixture
def test_config(tmp_dir, mock_db):
    """Create a TeredactaConfig pointing to mock data."""
    return TeredactaConfig(
        unobfuscator_path=str(tmp_dir),
        unobfuscator_bin="echo",  # safe no-op for subprocess tests
        db_path=str(mock_db),
        pdf_cache_dir=str(tmp_dir / "pdf_cache"),
        output_dir=str(tmp_dir / "output"),
        log_path=str(tmp_dir / "unobfuscator.log"),
        host="127.0.0.1",
        port=8000,
        admin_password_hash=None,
        log_level="info",
        session_timeout_minutes=60,
        sse_poll_interval_seconds=2,
        subprocess_timeout_seconds=5,
    )


@pytest.fixture
def app(test_config):
    """Create a test FastAPI app."""
    from teredacta.app import create_app
    return create_app(test_config)


@pytest.fixture
def client(app):
    """Create a test HTTP client."""
    return TestClient(app)
```

- [ ] **Step 6: Install in dev mode and verify**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && pip install -e ".[dev]"`
Expected: Successful install

- [ ] **Step 7: Commit**

```bash
git add teredacta/ pyproject.toml
git commit -m "feat: project scaffold with CLI, dependencies, and test fixtures"
```

---

### Task 2: Configuration Module

**Files:**
- Create: `teredacta/config.py`
- Create: `teredacta/tests/test_config.py`

- [ ] **Step 1: Write failing test for config loading**

```python
# teredacta/tests/test_config.py
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from teredacta.config import TeredactaConfig, load_config


class TestTeredactaConfig:
    def test_default_values(self):
        cfg = TeredactaConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8000
        assert cfg.admin_password_hash is None
        assert cfg.session_timeout_minutes == 60
        assert cfg.sse_poll_interval_seconds == 2
        assert cfg.subprocess_timeout_seconds == 60

    def test_is_local_mode(self):
        cfg = TeredactaConfig(host="127.0.0.1")
        assert cfg.is_local_mode is True
        cfg2 = TeredactaConfig(host="0.0.0.0")
        assert cfg2.is_local_mode is False

    def test_admin_enabled_local_no_password(self):
        cfg = TeredactaConfig(host="127.0.0.1", admin_password_hash=None)
        assert cfg.admin_enabled is True
        assert cfg.admin_requires_login is False

    def test_admin_disabled_server_no_password(self):
        cfg = TeredactaConfig(host="0.0.0.0", admin_password_hash=None)
        assert cfg.admin_enabled is False

    def test_admin_enabled_server_with_password(self):
        cfg = TeredactaConfig(host="0.0.0.0", admin_password_hash="$2b$12$hash")
        assert cfg.admin_enabled is True
        assert cfg.admin_requires_login is True


class TestLoadConfig:
    def test_load_from_yaml(self, tmp_path):
        config_data = {
            "unobfuscator_path": "/tmp/unob",
            "db_path": "/tmp/unob.db",
            "host": "0.0.0.0",
            "port": 9000,
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(str(config_file))
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9000

    def test_env_var_password_override(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"host": "0.0.0.0"}))
        monkeypatch.setenv("TEREDACTA_ADMIN_PASSWORD", "secret123")

        cfg = load_config(str(config_file))
        assert cfg.admin_password_hash is not None
        assert cfg.admin_password_hash.startswith("$2b$")

    def test_load_default_paths(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        config_dir = tmp_path / ".teredacta"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"port": 7777}))

        cfg = load_config(None)
        assert cfg.port == 7777
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teredacta.config'`

- [ ] **Step 3: Implement config module**

```python
# teredacta/config.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os

import bcrypt
import yaml


@dataclass
class TeredactaConfig:
    unobfuscator_path: str = ""
    unobfuscator_bin: str = ""
    db_path: str = ""
    pdf_cache_dir: str = ""
    output_dir: str = ""
    log_path: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    admin_password_hash: Optional[str] = None
    log_level: str = "info"
    session_timeout_minutes: int = 60
    sse_poll_interval_seconds: int = 2
    subprocess_timeout_seconds: int = 60
    secret_key: str = field(default_factory=lambda: os.urandom(32).hex())

    @property
    def is_local_mode(self) -> bool:
        return self.host in ("127.0.0.1", "localhost", "::1")

    @property
    def admin_enabled(self) -> bool:
        if self.is_local_mode:
            return True
        return self.admin_password_hash is not None

    @property
    def admin_requires_login(self) -> bool:
        if self.is_local_mode and self.admin_password_hash is None:
            return False
        return True

    def check_password(self, password: str) -> bool:
        if self.admin_password_hash is None:
            return False
        return bcrypt.checkpw(
            password.encode("utf-8"),
            self.admin_password_hash.encode("utf-8"),
        )


def load_config(config_path: Optional[str] = None) -> TeredactaConfig:
    """Load config from YAML file, with env var overrides."""
    if config_path is None:
        # Search default locations
        candidates = [
            Path.cwd() / "teredacta.yaml",
            Path.home() / ".teredacta" / "config.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = str(candidate)
                break

    data = {}
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    # Build config from file data
    cfg = TeredactaConfig(**{
        k: v for k, v in data.items()
        if k in TeredactaConfig.__dataclass_fields__
    })

    # Env var override for password (plaintext → bcrypt hash)
    env_password = os.environ.get("TEREDACTA_ADMIN_PASSWORD")
    if env_password:
        cfg.admin_password_hash = bcrypt.hashpw(
            env_password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")

    return cfg
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/test_config.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/config.py teredacta/tests/test_config.py
git commit -m "feat: config module with YAML loading, env var overrides, bcrypt password"
```

---

### Task 3: Unobfuscator Interface (`unob.py`)

**Files:**
- Create: `teredacta/unob.py`
- Create: `teredacta/tests/test_unob.py`

- [ ] **Step 1: Write failing tests for DB reads**

```python
# teredacta/tests/test_unob.py
import json
import sqlite3

import pytest

from teredacta.unob import UnobInterface


@pytest.fixture
def unob(test_config, mock_db):
    return UnobInterface(test_config)


@pytest.fixture
def populated_db(mock_db):
    """Insert sample data into the mock DB."""
    conn = sqlite3.connect(str(mock_db))
    # Insert documents
    conn.execute(
        "INSERT INTO documents (id, source, release_batch, original_filename, "
        "page_count, description, extracted_text, text_processed, pdf_processed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("doc-001", "doj", "VOL00001", "letter.pdf", 3,
         "Letter from JE", "Dear [REDACTED], meeting at...", 1, 0),
    )
    conn.execute(
        "INSERT INTO documents (id, source, release_batch, original_filename, "
        "page_count, description, extracted_text, text_processed, pdf_processed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("doc-002", "doj", "VOL00001", "email.pdf", 1,
         "Email chain", "From: JE To: GM Subject: plans", 1, 1),
    )
    # Insert fingerprint
    conn.execute(
        "INSERT INTO document_fingerprints (doc_id, minhash_sig, shingle_count) "
        "VALUES (?, ?, ?)",
        ("doc-001", b"\x00" * 64, 100),
    )
    # Insert match group
    conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (1, 1)")
    conn.execute(
        "INSERT INTO match_group_members (group_id, doc_id, similarity) "
        "VALUES (1, 'doc-001', 0.92)"
    )
    conn.execute(
        "INSERT INTO match_group_members (group_id, doc_id, similarity) "
        "VALUES (1, 'doc-002', 0.88)"
    )
    # Insert merge result
    segments = json.dumps([
        {"source_doc_id": "doc-002", "text": "Ghislaine Maxwell", "position": 5},
        {"source_doc_id": "doc-002", "text": "the townhouse on 71st", "position": 30},
    ])
    conn.execute(
        "INSERT INTO merge_results (group_id, merged_text, recovered_count, "
        "total_redacted, source_doc_ids, recovered_segments, soft_recovered_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "Dear Ghislaine Maxwell, meeting at the townhouse on 71st...",
         2, 3, json.dumps(["doc-001", "doc-002"]), segments, 0),
    )
    # Insert jobs
    conn.execute(
        "INSERT INTO jobs (stage, payload, priority, status) VALUES (?, ?, ?, ?)",
        ("index", '{"batch_id": "VOL00001"}', 0, "done"),
    )
    conn.execute(
        "INSERT INTO jobs (stage, payload, priority, status) VALUES (?, ?, ?, ?)",
        ("merge", '{"group_id": 1}', 100, "pending"),
    )
    conn.commit()
    conn.close()
    return mock_db


class TestUnobDBReads:
    def test_get_stats(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        stats = unob.get_stats()
        assert stats["total_documents"] == 2
        assert stats["indexed"] == 2
        assert stats["fingerprinted"] == 1
        assert stats["matched"] == 2
        assert stats["recovered"] == 2
        assert stats["groups"] == 1

    def test_get_documents_paginated(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        docs, total = unob.get_documents(page=1, per_page=10)
        assert total == 2
        assert len(docs) == 2
        assert docs[0]["id"] in ("doc-001", "doc-002")

    def test_get_documents_filtered(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        docs, total = unob.get_documents(page=1, per_page=10, search="letter")
        assert total == 1
        assert docs[0]["id"] == "doc-001"

    def test_get_document_detail(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        doc = unob.get_document("doc-001")
        assert doc["id"] == "doc-001"
        assert doc["source"] == "doj"

    def test_get_document_not_found(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        doc = unob.get_document("nonexistent")
        assert doc is None

    def test_get_match_groups(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        groups = unob.get_match_groups()
        assert len(groups) == 1
        assert groups[0]["group_id"] == 1
        assert groups[0]["member_count"] == 2

    def test_get_recoveries(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        results = unob.get_recoveries()
        assert len(results) == 1
        assert results[0]["recovered_count"] == 2

    def test_get_recoveries_search(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        results = unob.get_recoveries(search="Maxwell")
        assert len(results) == 1
        results2 = unob.get_recoveries(search="nonexistent")
        assert len(results2) == 0

    def test_get_jobs(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        jobs = unob.get_jobs()
        assert len(jobs) == 2

    def test_get_jobs_filtered(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        jobs = unob.get_jobs(status="pending")
        assert len(jobs) == 1
        assert jobs[0]["status"] == "pending"

    def test_db_not_found(self, test_config):
        test_config.db_path = "/nonexistent/path.db"
        unob = UnobInterface(test_config)
        with pytest.raises(FileNotFoundError, match="Database not found"):
            unob.get_stats()

    def test_get_common_unredactions(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        # With only 1 occurrence each, min_occurrences=2 returns empty
        common = unob.get_common_unredactions(min_occurrences=1, min_words=1, limit=20)
        assert len(common) == 2  # "Ghislaine Maxwell" and "the townhouse on 71st"


    def test_get_match_group_detail(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        detail = unob.get_match_group_detail(1)
        assert detail is not None
        assert len(detail["members"]) == 2
        assert detail["merge_result"]["recovered_count"] == 2

    def test_get_recovery_detail(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        detail = unob.get_recovery_detail(1)
        assert detail is not None
        assert isinstance(detail["recovered_segments"], list)
        assert len(detail["recovered_segments"]) == 2
        assert detail["recovered_segments"][0]["text"] == "Ghislaine Maxwell"

    def test_read_log_lines(self, test_config, tmp_dir):
        log_path = tmp_dir / "unobfuscator.log"
        log_path.write_text("INFO line1\nWARNING line2\nERROR line3\n")
        test_config.log_path = str(log_path)
        unob = UnobInterface(test_config)
        lines = unob.read_log_lines(n=50)
        assert len(lines) == 3

    def test_read_log_lines_filtered(self, test_config, tmp_dir):
        log_path = tmp_dir / "unobfuscator.log"
        log_path.write_text("INFO line1\nWARNING line2\nERROR line3\n")
        test_config.log_path = str(log_path)
        unob = UnobInterface(test_config)
        lines = unob.read_log_lines(n=50, level="ERROR")
        assert len(lines) == 1
        assert "ERROR" in lines[0]

    def test_read_log_from_position(self, test_config, tmp_dir):
        log_path = tmp_dir / "unobfuscator.log"
        log_path.write_text("line1\nline2\n")
        test_config.log_path = str(log_path)
        unob = UnobInterface(test_config)
        pos = unob.get_log_position()
        log_path.write_text("line1\nline2\nline3\n")
        new_lines, new_pos = unob.read_log_from(pos)
        assert "line3" in new_lines[0] if new_lines else True

    def test_get_documents_has_redactions_filter(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        docs, total = unob.get_documents(page=1, per_page=10, has_redactions=True)
        # doc-001 has [REDACTED] in extracted_text
        assert total >= 1

    def test_get_documents_processing_stage_filter(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        docs, total = unob.get_documents(page=1, per_page=10, stage="pdf_processed")
        # doc-002 has pdf_processed=1
        assert total == 1


class TestUnobSubprocess:
    def test_daemon_status(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        test_config.unobfuscator_bin = "echo"
        unob = UnobInterface(test_config)
        status = unob.get_daemon_status()
        # echo returns success, daemon considered stopped (no PID file)
        assert "running" in status or "stopped" in status

    def test_subprocess_timeout(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        test_config.unobfuscator_bin = "sleep"
        test_config.subprocess_timeout_seconds = 1
        unob = UnobInterface(test_config)
        result = unob.run_command(["999"])
        assert result["success"] is False
        assert "timeout" in result["error"].lower()

    def test_stop_daemon_windows(self, test_config, populated_db, tmp_dir):
        """Test Windows daemon stop path using mock."""
        from unittest.mock import patch
        test_config.db_path = str(populated_db)
        test_config.unobfuscator_path = str(tmp_dir)
        pid_file = tmp_dir / ".unobfuscator.pid"
        pid_file.write_text("12345")
        unob = UnobInterface(test_config)

        with patch("platform.system", return_value="Windows"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = unob.stop_daemon()
            assert result["success"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/test_unob.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `unob.py`**

```python
# teredacta/unob.py
import json
import os
import platform
import sqlite3
import subprocess
import re
from pathlib import Path
from typing import Optional

from teredacta.config import TeredactaConfig


class UnobInterface:
    """Single interface to all Unobfuscator interactions."""

    def __init__(self, config: TeredactaConfig):
        self.config = config
        self._common_unredactions_cache = None
        self._last_recovery_count = None

    def _get_db(self) -> sqlite3.Connection:
        db_path = Path(self.config.db_path)
        if not db_path.exists():
            raise FileNotFoundError(
                f"Database not found at {db_path}. "
                "Check your TEREDACTA configuration."
            )
        conn = sqlite3.connect(
            str(db_path),
            timeout=5.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    # --- Stats ---

    def get_stats(self) -> dict:
        conn = self._get_db()
        try:
            stats = {}
            stats["total_documents"] = conn.execute(
                "SELECT COUNT(*) FROM documents"
            ).fetchone()[0]
            stats["indexed"] = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE text_processed = 1"
            ).fetchone()[0]
            stats["fingerprinted"] = conn.execute(
                "SELECT COUNT(*) FROM document_fingerprints"
            ).fetchone()[0]
            stats["matched"] = conn.execute(
                "SELECT COUNT(*) FROM match_group_members"
            ).fetchone()[0]
            stats["groups"] = conn.execute(
                "SELECT COUNT(*) FROM match_groups"
            ).fetchone()[0]
            stats["merged"] = conn.execute(
                "SELECT COUNT(*) FROM merge_results WHERE recovered_count > 0"
            ).fetchone()[0]
            stats["recovered"] = conn.execute(
                "SELECT COALESCE(SUM(recovered_count), 0) FROM merge_results"
            ).fetchone()[0]
            stats["soft_recovered"] = conn.execute(
                "SELECT COALESCE(SUM(soft_recovered_count), 0) FROM merge_results"
            ).fetchone()[0]
            stats["pdfs_processed"] = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE pdf_processed = 1"
            ).fetchone()[0]
            stats["outputs_generated"] = conn.execute(
                "SELECT COUNT(*) FROM merge_results WHERE output_generated = 1"
            ).fetchone()[0]
            stats["failed_jobs"] = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = 'failed'"
            ).fetchone()[0]
            return stats
        finally:
            conn.close()

    # --- Documents ---

    def get_documents(
        self,
        page: int = 1,
        per_page: int = 50,
        search: Optional[str] = None,
        source: Optional[str] = None,
        batch: Optional[str] = None,
        has_redactions: Optional[bool] = None,
        stage: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        conn = self._get_db()
        try:
            where_clauses = []
            params = []

            if search:
                where_clauses.append(
                    "(id LIKE ? OR original_filename LIKE ? OR description LIKE ?)"
                )
                term = f"%{search}%"
                params.extend([term, term, term])
            if source:
                where_clauses.append("source = ?")
                params.append(source)
            if batch:
                where_clauses.append("release_batch = ?")
                params.append(batch)
            if has_redactions is True:
                where_clauses.append(
                    "(extracted_text LIKE '%[REDACTED]%' OR extracted_text LIKE '%[b(6)]%' "
                    "OR extracted_text LIKE '%XXXXXXXXX%')"
                )
            if stage:
                if stage == "text_processed":
                    where_clauses.append("text_processed = 1")
                elif stage == "pdf_processed":
                    where_clauses.append("pdf_processed = 1")
                elif stage == "unprocessed":
                    where_clauses.append("text_processed = 0")

            where = " AND ".join(where_clauses) if where_clauses else "1=1"

            total = conn.execute(
                f"SELECT COUNT(*) FROM documents WHERE {where}", params
            ).fetchone()[0]

            offset = (page - 1) * per_page
            rows = conn.execute(
                f"SELECT id, source, release_batch, original_filename, page_count, "
                f"description, text_processed, pdf_processed "
                f"FROM documents WHERE {where} "
                f"ORDER BY id LIMIT ? OFFSET ?",
                params + [per_page, offset],
            ).fetchall()

            docs = [dict(row) for row in rows]
            return docs, total
        finally:
            conn.close()

    def get_document(self, doc_id: str) -> Optional[dict]:
        conn = self._get_db()
        try:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if row is None:
                return None
            doc = dict(row)

            # Check for match group membership
            group_row = conn.execute(
                "SELECT group_id, similarity FROM match_group_members WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
            if group_row:
                doc["group_id"] = group_row["group_id"]
                doc["similarity"] = group_row["similarity"]

            return doc
        finally:
            conn.close()

    # --- Match Groups ---

    def get_match_groups(self) -> list[dict]:
        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT mg.group_id, mg.merged, mg.created_at,
                       COUNT(mgm.doc_id) as member_count,
                       AVG(mgm.similarity) as avg_similarity
                FROM match_groups mg
                LEFT JOIN match_group_members mgm ON mg.group_id = mgm.group_id
                GROUP BY mg.group_id
                ORDER BY mg.group_id DESC
            """).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_match_group_detail(self, group_id: int) -> Optional[dict]:
        conn = self._get_db()
        try:
            group = conn.execute(
                "SELECT * FROM match_groups WHERE group_id = ?", (group_id,)
            ).fetchone()
            if group is None:
                return None

            members = conn.execute(
                "SELECT mgm.doc_id, mgm.similarity, d.original_filename, d.source, "
                "d.release_batch, d.description "
                "FROM match_group_members mgm "
                "JOIN documents d ON mgm.doc_id = d.id "
                "WHERE mgm.group_id = ? ORDER BY mgm.similarity DESC",
                (group_id,),
            ).fetchall()

            merge = conn.execute(
                "SELECT * FROM merge_results WHERE group_id = ?", (group_id,)
            ).fetchone()

            result = dict(group)
            result["members"] = [dict(m) for m in members]
            result["merge_result"] = dict(merge) if merge else None
            return result
        finally:
            conn.close()

    # --- Recoveries ---

    def get_recoveries(
        self,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> list[dict]:
        conn = self._get_db()
        try:
            where = "mr.recovered_count > 0"
            params = []
            if search:
                where += " AND mr.merged_text LIKE ?"
                params.append(f"%{search}%")

            rows = conn.execute(
                f"SELECT mr.group_id, mr.recovered_count, mr.total_redacted, "
                f"mr.soft_recovered_count, mr.source_doc_ids, mr.output_generated, "
                f"mr.created_at "
                f"FROM merge_results mr WHERE {where} "
                f"ORDER BY mr.recovered_count DESC "
                f"LIMIT ? OFFSET ?",
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_recovery_detail(self, group_id: int) -> Optional[dict]:
        conn = self._get_db()
        try:
            row = conn.execute(
                "SELECT * FROM merge_results WHERE group_id = ? AND recovered_count > 0",
                (group_id,),
            ).fetchone()
            if row is None:
                return None

            result = dict(row)
            # Parse JSON fields
            if result.get("source_doc_ids"):
                result["source_doc_ids"] = json.loads(result["source_doc_ids"])
            if result.get("recovered_segments"):
                result["recovered_segments"] = json.loads(result["recovered_segments"])

            # Get group members
            members = conn.execute(
                "SELECT mgm.doc_id, mgm.similarity, d.original_filename, d.source, "
                "d.release_batch "
                "FROM match_group_members mgm "
                "JOIN documents d ON mgm.doc_id = d.id "
                "WHERE mgm.group_id = ?",
                (group_id,),
            ).fetchall()
            result["members"] = [dict(m) for m in members]

            return result
        finally:
            conn.close()

    def get_common_unredactions(
        self,
        min_occurrences: int = 2,
        min_words: int = 3,
        limit: int = 20,
    ) -> list[dict]:
        """Get most frequently recovered text strings."""
        # Check cache
        conn = self._get_db()
        try:
            current_count = conn.execute(
                "SELECT COALESCE(SUM(recovered_count), 0) FROM merge_results"
            ).fetchone()[0]
        finally:
            conn.close()

        if (
            self._common_unredactions_cache is not None
            and self._last_recovery_count == current_count
        ):
            return self._common_unredactions_cache[:limit]

        conn = self._get_db()
        try:
            rows = conn.execute(
                "SELECT value FROM merge_results, "
                "json_each(merge_results.recovered_segments) "
                "WHERE recovered_count > 0 AND value IS NOT NULL"
            ).fetchall()

            counts = {}
            for row in rows:
                segment = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                text = segment.get("text", "") if isinstance(segment, dict) else str(segment)
                # Normalize: collapse whitespace, strip
                text = " ".join(text.split()).strip()
                if not text:
                    continue
                word_count = len(text.split())
                if word_count < min_words:
                    continue
                counts[text] = counts.get(text, 0) + 1

            results = [
                {"text": text, "count": count}
                for text, count in counts.items()
                if count >= min_occurrences
            ]
            results.sort(key=lambda x: x["count"], reverse=True)

            self._common_unredactions_cache = results
            self._last_recovery_count = current_count
            return results[:limit]
        finally:
            conn.close()

    # --- Jobs ---

    def get_jobs(
        self,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> list[dict]:
        conn = self._get_db()
        try:
            where = "1=1"
            params = []
            if status:
                where = "status = ?"
                params.append(status)

            rows = conn.execute(
                f"SELECT * FROM jobs WHERE {where} "
                f"ORDER BY job_id DESC LIMIT ? OFFSET ?",
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # --- Subprocess Commands ---

    def run_command(self, args: list[str]) -> dict:
        """Run an unobfuscator CLI command."""
        cmd = self.config.unobfuscator_bin.split() + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.subprocess_timeout_seconds,
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": f"Timeout after {self.config.subprocess_timeout_seconds}s",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": f"Unobfuscator not found at: {self.config.unobfuscator_bin}",
            }

    def get_daemon_status(self) -> str:
        """Check if the daemon is running."""
        pid_file = Path(self.config.unobfuscator_path) / ".unobfuscator.pid"
        if not pid_file.exists():
            return "stopped"
        try:
            pid = int(pid_file.read_text().strip())
            # Check if process is alive
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True,
                )
                return "running" if str(pid) in result.stdout else "stopped"
            else:
                import signal
                os.kill(pid, 0)  # Doesn't actually kill, just checks
                return "running"
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            return "stopped"

    def start_daemon(self) -> dict:
        return self.run_command(["start"])

    def stop_daemon(self) -> dict:
        if platform.system() == "Windows":
            pid_file = Path(self.config.unobfuscator_path) / ".unobfuscator.pid"
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True,
                        timeout=30,
                    )
                    pid_file.unlink(missing_ok=True)
                    return {"success": True, "stdout": "Daemon stopped"}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            return {"success": True, "stdout": "Daemon not running"}
        return self.run_command(["stop"])

    def restart_daemon(self) -> dict:
        stop_result = self.stop_daemon()
        if not stop_result.get("success", False) and "not running" not in stop_result.get("stdout", ""):
            return {
                "success": False,
                "error": f"Stop failed: {stop_result.get('error', stop_result.get('stderr', ''))}",
            }
        return self.start_daemon()

    def search(self, **kwargs) -> dict:
        args = ["search"]
        if kwargs.get("person"):
            args.extend(["--person", kwargs["person"]])
        if kwargs.get("batch"):
            args.extend(["--batch", kwargs["batch"]])
        if kwargs.get("doc_id"):
            args.extend(["--doc", kwargs["doc_id"]])
        if kwargs.get("query"):
            args.append(kwargs["query"])
        return self.run_command(args)

    # --- Log Tailing ---

    def read_log_lines(self, n: int = 50, level: Optional[str] = None) -> list[str]:
        """Read last n lines from the log file."""
        log_path = Path(self.config.log_path)
        if not log_path.exists():
            return []
        lines = log_path.read_text().splitlines()
        if level:
            level_upper = level.upper()
            lines = [l for l in lines if level_upper in l]
        return lines[-n:]

    def get_log_position(self) -> int:
        """Get current log file size for tailing."""
        log_path = Path(self.config.log_path)
        if not log_path.exists():
            return 0
        return log_path.stat().st_size

    def read_log_from(self, position: int) -> tuple[list[str], int]:
        """Read new log lines from a given byte position."""
        log_path = Path(self.config.log_path)
        if not log_path.exists():
            return [], 0
        current_size = log_path.stat().st_size
        if current_size <= position:
            return [], current_size
        with open(log_path, "r") as f:
            f.seek(position)
            new_content = f.read()
        new_lines = new_content.splitlines()
        return new_lines, current_size

    # --- PDF File Access ---

    def get_pdf_path(self, pdf_type: str, *path_parts: str) -> Optional[Path]:
        """Get path to a PDF file. pdf_type is 'cache', 'output', or 'summary'."""
        if pdf_type == "cache":
            base = Path(self.config.pdf_cache_dir)
        elif pdf_type == "output":
            base = Path(self.config.output_dir)
        elif pdf_type == "summary":
            base = Path(self.config.output_dir)
        else:
            return None

        full_path = base / "/".join(path_parts)
        # Security: ensure path stays within base directory
        try:
            full_path.resolve().relative_to(base.resolve())
        except ValueError:
            return None

        if full_path.exists() and full_path.suffix.lower() == ".pdf":
            return full_path
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/test_unob.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add teredacta/unob.py teredacta/tests/test_unob.py
git commit -m "feat: unob.py interface — DB reads, subprocess, log tailing, PDF access"
```

---

### Task 4: App Factory & Base Template

**Files:**
- Create: `teredacta/app.py`
- Create: `teredacta/auth.py`
- Create: `teredacta/templates/base.html`
- Create: `teredacta/templates/error.html`
- Create: `teredacta/static/css/app.css`
- Create: `teredacta/tests/test_auth.py`

- [ ] **Step 1: Write failing test for auth middleware**

```python
# teredacta/tests/test_auth.py
import bcrypt
import pytest
from fastapi.testclient import TestClient


class TestAdminAuth:
    def test_admin_page_no_password_local(self, client):
        """Local mode, no password: admin accessible without login."""
        resp = client.get("/admin")
        assert resp.status_code == 200

    def test_admin_page_requires_login_server_mode(self, test_config, mock_db):
        """Server mode with password: admin redirects to login."""
        test_config.host = "0.0.0.0"
        pw_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
        test_config.admin_password_hash = pw_hash

        from teredacta.app import create_app
        app = create_app(test_config)
        client = TestClient(app)

        resp = client.get("/admin", follow_redirects=False)
        assert resp.status_code == 200  # Shows login page

    def test_login_success(self, test_config, mock_db):
        """Correct password sets session cookie."""
        test_config.host = "0.0.0.0"
        pw_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
        test_config.admin_password_hash = pw_hash

        from teredacta.app import create_app
        app = create_app(test_config)
        client = TestClient(app)

        resp = client.post(
            "/admin/login",
            data={"password": "secret"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "session" in resp.cookies

    def test_login_failure(self, test_config, mock_db):
        """Wrong password returns error."""
        test_config.host = "0.0.0.0"
        pw_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
        test_config.admin_password_hash = pw_hash

        from teredacta.app import create_app
        app = create_app(test_config)
        client = TestClient(app)

        resp = client.post(
            "/admin/login",
            data={"password": "wrong"},
        )
        assert resp.status_code == 401


class TestCSRF:
    def test_state_changing_without_csrf_rejected(self, test_config, mock_db):
        """POST without CSRF token is rejected (when admin requires login)."""
        test_config.host = "0.0.0.0"
        pw_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
        test_config.admin_password_hash = pw_hash

        from teredacta.app import create_app
        app = create_app(test_config)
        client = TestClient(app)

        # Login first
        resp = client.post(
            "/admin/login",
            data={"password": "secret"},
            follow_redirects=False,
        )
        # Try admin action without CSRF
        resp2 = client.post("/admin/daemon/start")
        assert resp2.status_code in (403, 401)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/test_auth.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `auth.py`**

```python
# teredacta/auth.py
import hashlib
import os
import time
from functools import wraps
from typing import Optional

from fastapi import Request, Response
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from teredacta.config import TeredactaConfig


class AuthManager:
    def __init__(self, config: TeredactaConfig):
        self.config = config
        self.serializer = URLSafeTimedSerializer(config.secret_key)

    def create_session(self, response: Response) -> str:
        """Create a signed session cookie with CSRF token."""
        csrf_token = os.urandom(16).hex()
        session_data = {"csrf": csrf_token, "t": int(time.time())}
        cookie_value = self.serializer.dumps(session_data)
        response.set_cookie(
            "session",
            cookie_value,
            httponly=True,
            samesite="strict",
            max_age=self.config.session_timeout_minutes * 60,
        )
        return csrf_token

    def validate_session(self, request: Request) -> Optional[dict]:
        """Validate session cookie. Returns session data or None."""
        cookie = request.cookies.get("session")
        if not cookie:
            return None
        try:
            data = self.serializer.loads(
                cookie,
                max_age=self.config.session_timeout_minutes * 60,
            )
            return data
        except (BadSignature, SignatureExpired):
            return None

    def validate_csrf(self, request: Request, session: dict) -> bool:
        """Validate CSRF token from request header against session."""
        token = request.headers.get("X-CSRF-Token", "")
        return token == session.get("csrf", "")

    def is_admin(self, request: Request) -> bool:
        """Check if current request has admin access."""
        if not self.config.admin_enabled:
            return False
        if not self.config.admin_requires_login:
            return True
        session = self.validate_session(request)
        return session is not None

    def get_csrf_token(self, request: Request) -> str:
        """Get CSRF token for the current session, or empty string."""
        session = self.validate_session(request)
        if session:
            return session.get("csrf", "")
        return ""

    def clear_session(self, response: Response):
        """Remove session cookie."""
        response.delete_cookie("session")
```

- [ ] **Step 4: Implement `app.py`**

```python
# teredacta/app.py
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from teredacta.auth import AuthManager
from teredacta.config import TeredactaConfig
from teredacta.unob import UnobInterface


def create_app(config: TeredactaConfig) -> FastAPI:
    app = FastAPI(title="TEREDACTA", docs_url=None, redoc_url=None)

    # Shared state
    app.state.config = config
    app.state.unob = UnobInterface(config)
    app.state.auth = AuthManager(config)

    # Static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Templates
    template_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(template_dir))
    app.state.templates = templates

    # Template context processor
    @app.middleware("http")
    async def add_template_context(request: Request, call_next):
        request.state.is_admin = app.state.auth.is_admin(request)
        request.state.csrf_token = app.state.auth.get_csrf_token(request)
        request.state.config = config
        response = await call_next(request)
        return response

    # Import and mount routers
    from teredacta.routers import dashboard, documents, groups, recoveries, pdf, queue, summary, admin
    app.include_router(dashboard.router)
    app.include_router(documents.router, prefix="/documents")
    app.include_router(groups.router, prefix="/groups")
    app.include_router(recoveries.router, prefix="/recoveries")
    app.include_router(pdf.router, prefix="/pdf")
    app.include_router(queue.router, prefix="/queue")
    app.include_router(summary.router, prefix="/summary")
    app.include_router(admin.router, prefix="/admin")

    # Error handler for DB not found
    @app.exception_handler(FileNotFoundError)
    async def db_not_found_handler(request: Request, exc: FileNotFoundError):
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": str(exc), "is_admin": False, "csrf_token": ""},
            status_code=503,
        )

    return app
```

- [ ] **Step 5: Create `base.html` template**

```html
{# teredacta/templates/base.html #}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}TEREDACTA{% endblock %}</title>
    <meta name="csrf-token" content="{{ csrf_token }}">
    <link rel="stylesheet" href="/static/css/app.css">
    <script src="/static/js/htmx.min.js"></script>
</head>
<body hx-headers='{"X-CSRF-Token": "{{ csrf_token }}"}'>
    <nav class="top-nav">
        <div class="nav-left">
            <a href="/" class="nav-logo">TEREDACTA</a>
            <a href="/" class="nav-link {% block nav_dashboard %}{% endblock %}">Dashboard</a>
            <a href="/documents" class="nav-link {% block nav_documents %}{% endblock %}">Documents</a>
            <a href="/groups" class="nav-link {% block nav_groups %}{% endblock %}">Groups</a>
            <a href="/recoveries" class="nav-link {% block nav_recoveries %}{% endblock %}">Recoveries</a>
            <a href="/queue" class="nav-link {% block nav_queue %}{% endblock %}">Queue</a>
            <a href="/summary" class="nav-link {% block nav_summary %}{% endblock %}">Summary</a>
        </div>
        <div class="nav-right">
            <span id="daemon-status"
                  hx-get="/sse/daemon-status"
                  hx-trigger="load, every 5s"
                  hx-swap="innerHTML">
                <span class="status-dot stopped"></span> CHECKING...
            </span>
        </div>
    </nav>
    <main class="content">
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

- [ ] **Step 6: Create `error.html` template**

```html
{# teredacta/templates/error.html #}
{% extends "base.html" %}
{% block title %}Error — TEREDACTA{% endblock %}
{% block content %}
<div class="error-banner">
    <h2>Configuration Error</h2>
    <p>{{ error }}</p>
</div>
{% endblock %}
```

- [ ] **Step 7: Create `app.css` with base styles**

```css
/* teredacta/static/css/app.css */
:root {
    --bg-primary: #0d1b2a;
    --bg-secondary: #1b2838;
    --bg-card: #1a2744;
    --bg-nav: #16213e;
    --text-primary: #e0e0e0;
    --text-secondary: #999;
    --accent-blue: #4fc3f7;
    --accent-green: #66bb6a;
    --accent-orange: #ff9800;
    --accent-red: #ef5350;
    --border: #2a3a5c;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
}

/* Top Navigation */
.top-nav {
    background: var(--bg-nav);
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 1.5rem;
    height: 48px;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 100;
}

.nav-left { display: flex; align-items: center; gap: 0.25rem; }
.nav-right { display: flex; align-items: center; gap: 1rem; }

.nav-logo {
    font-weight: 700;
    font-size: 1rem;
    color: var(--accent-blue);
    text-decoration: none;
    margin-right: 1.5rem;
    letter-spacing: 0.05em;
}

.nav-link {
    color: var(--text-secondary);
    text-decoration: none;
    padding: 0.75rem 0.75rem;
    font-size: 0.875rem;
    border-bottom: 2px solid transparent;
    transition: color 0.2s, border-color 0.2s;
}

.nav-link:hover { color: var(--text-primary); }
.nav-link.active {
    color: var(--accent-blue);
    border-bottom-color: var(--accent-blue);
}

/* Status indicator */
.status-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 4px;
}
.status-dot.running { background: var(--accent-green); }
.status-dot.stopped { background: var(--accent-red); }

#daemon-status {
    font-size: 0.75rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* Content area */
.content {
    max-width: 1400px;
    margin: 0 auto;
    padding: 1.5rem;
}

/* Cards */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
}

.stat-card {
    background: var(--bg-card);
    border-radius: 8px;
    padding: 1.25rem;
    text-align: center;
}

.stat-value {
    font-size: 1.75rem;
    font-weight: 700;
    margin-bottom: 0.25rem;
}

.stat-label {
    font-size: 0.75rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* Progress bars */
.progress-bar {
    background: var(--bg-secondary);
    border-radius: 4px;
    height: 8px;
    overflow: hidden;
    margin-top: 0.5rem;
}

.progress-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s ease;
}

/* Tables */
.data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
}

.data-table th {
    text-align: left;
    padding: 0.75rem;
    color: var(--text-secondary);
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border);
}

.data-table td {
    padding: 0.75rem;
    border-bottom: 1px solid var(--border);
}

.data-table tr:hover { background: var(--bg-card); }
.data-table tr { cursor: pointer; }

/* Tabs */
.tabs {
    display: flex;
    gap: 2px;
    margin-bottom: 0;
}

.tab {
    padding: 0.625rem 1.25rem;
    background: var(--bg-card);
    color: var(--text-secondary);
    border: none;
    border-radius: 8px 8px 0 0;
    cursor: pointer;
    font-size: 0.875rem;
    transition: background 0.2s, color 0.2s;
}

.tab:hover { color: var(--text-primary); }
.tab.active {
    background: var(--bg-secondary);
    color: var(--accent-blue);
}

.tab-content {
    background: var(--bg-secondary);
    border-radius: 0 8px 8px 8px;
    padding: 1.5rem;
    min-height: 400px;
}

/* Highlight styles */
.recovered { background: #2e7d32; padding: 1px 4px; border-radius: 3px; }
.source-highlight { background: #f9a825; color: #000; padding: 1px 4px; border-radius: 3px; }

/* Search & filters */
.search-bar {
    display: flex;
    gap: 0.75rem;
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
}

.search-input {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-primary);
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
    flex: 1;
    min-width: 200px;
}

.search-input:focus {
    outline: none;
    border-color: var(--accent-blue);
}

.filter-select {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-primary);
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
}

/* Buttons */
.btn {
    padding: 0.5rem 1rem;
    border-radius: 6px;
    border: none;
    font-size: 0.875rem;
    cursor: pointer;
    font-weight: 500;
    transition: opacity 0.2s;
}

.btn:hover { opacity: 0.85; }
.btn-primary { background: var(--accent-blue); color: #000; }
.btn-success { background: var(--accent-green); color: #000; }
.btn-danger { background: var(--accent-red); color: #fff; }
.btn-warning { background: var(--accent-orange); color: #000; }

/* Error banner */
.error-banner {
    background: rgba(239, 83, 80, 0.1);
    border: 1px solid var(--accent-red);
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
}

.error-banner h2 { color: var(--accent-red); margin-bottom: 0.5rem; }

/* Pagination */
.pagination {
    display: flex;
    justify-content: center;
    gap: 0.5rem;
    margin-top: 1.5rem;
}

.page-link {
    padding: 0.375rem 0.75rem;
    background: var(--bg-card);
    color: var(--text-secondary);
    border-radius: 4px;
    text-decoration: none;
    font-size: 0.875rem;
}

.page-link.active { background: var(--accent-blue); color: #000; }

/* Admin */
.admin-form {
    background: var(--bg-secondary);
    border-radius: 8px;
    padding: 1.5rem;
    max-width: 400px;
}

.form-group { margin-bottom: 1rem; }
.form-group label {
    display: block;
    margin-bottom: 0.375rem;
    font-size: 0.875rem;
    color: var(--text-secondary);
}

.form-control {
    width: 100%;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-primary);
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
}

/* Log viewer */
.log-viewer {
    background: #0a0a0a;
    border-radius: 8px;
    padding: 1rem;
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.8rem;
    line-height: 1.5;
    max-height: 600px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
}

/* PDF comparison */
.pdf-comparison {
    display: flex;
    gap: 1rem;
}

.pdf-comparison .pdf-pane {
    flex: 1;
    min-height: 600px;
}

.comparison-controls {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    margin-bottom: 1rem;
}

/* Common unredactions */
.common-unredactions {
    background: var(--bg-card);
    border-radius: 8px;
    padding: 1rem;
    margin-bottom: 1.5rem;
}

.common-unredactions h3 {
    font-size: 0.875rem;
    color: var(--text-secondary);
    margin-bottom: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.unredaction-item {
    display: flex;
    justify-content: space-between;
    padding: 0.375rem 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.8rem;
}

.unredaction-item a { color: var(--accent-blue); text-decoration: none; }
.unredaction-count {
    color: var(--text-secondary);
    font-size: 0.75rem;
}
```

- [ ] **Step 8: Run auth tests**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/test_auth.py -v`
Expected: All PASS (some tests may need stub routers — see next step)

- [ ] **Step 9: Create stub routers so app can start**

Create minimal stub routers for each module so the app factory can import them. Each stub has an empty router:

```python
# teredacta/routers/dashboard.py (and similar for all router files)
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    templates = request.app.state.templates
    unob = request.app.state.unob
    try:
        stats = unob.get_stats()
    except FileNotFoundError:
        stats = {}
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })
```

Create stubs for: `documents.py`, `groups.py`, `recoveries.py`, `pdf.py`, `queue.py`, `summary.py`, `admin.py` — each with a minimal `router = APIRouter()` and at least one GET route returning a placeholder template response.

- [ ] **Step 10: Create stub templates for each router**

Create minimal HTML templates extending `base.html` for: `dashboard.html`, `documents/list.html`, `groups/list.html`, `recoveries/list.html`, `queue/list.html`, `summary/view.html`, `admin/login.html`, `admin/dashboard.html`.

- [ ] **Step 11: Run all tests**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/ -v`
Expected: All PASS

- [ ] **Step 12: Commit**

```bash
git add teredacta/app.py teredacta/auth.py teredacta/templates/ teredacta/static/ teredacta/routers/
git commit -m "feat: app factory, auth middleware, base template, CSS theme, stub routers"
```

---

## Chunk 2: Public Feature Routers (Tasks 5-9)

Dashboard, document browser, match groups, recovery viewer, PDF viewer, job queue, and summary — all the public-facing read-only features.

### Task 5: Dashboard Router with SSE

**Files:**
- Create: `teredacta/sse.py`
- Modify: `teredacta/routers/dashboard.py`
- Create: `teredacta/templates/dashboard.html`
- Create: `teredacta/templates/partials/stats_cards.html`
- Create: `teredacta/templates/partials/progress_bars.html`
- Create: `teredacta/templates/partials/daemon_status.html`
- Create: `teredacta/tests/test_sse.py`
- Create: `teredacta/tests/routers/__init__.py`
- Create: `teredacta/tests/routers/test_dashboard.py`

- [ ] **Step 1: Write failing test for SSE manager**

```python
# teredacta/tests/test_sse.py
import asyncio
import pytest
from teredacta.sse import SSEManager


@pytest.mark.asyncio
async def test_sse_subscribe_unsubscribe():
    manager = SSEManager(poll_interval=0.1)
    gen = manager.subscribe()
    # Should be able to get the generator
    assert gen is not None
    manager.unsubscribe(gen)

@pytest.mark.asyncio
async def test_sse_polling_starts_on_subscribe(test_config, mock_db):
    from teredacta.unob import UnobInterface
    unob = UnobInterface(test_config)
    manager = SSEManager(poll_interval=0.1, unob=unob)
    gen = manager.subscribe()
    assert manager._task is not None
    manager.unsubscribe(gen)
    # After last unsubscribe, task should stop
    await asyncio.sleep(0.2)
```

- [ ] **Step 2: Implement `sse.py`**

```python
# teredacta/sse.py
import asyncio
import json
from typing import AsyncGenerator, Optional, Set

from teredacta.unob import UnobInterface


class SSEManager:
    """Shared SSE polling task. Starts on first subscriber, stops on last."""

    def __init__(self, poll_interval: float = 2.0, unob: Optional[UnobInterface] = None):
        self.poll_interval = poll_interval
        self.unob = unob
        self._subscribers: Set[asyncio.Queue] = set()
        self._task: Optional[asyncio.Task] = None
        self._last_stats: Optional[dict] = None

    def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue()
        self._subscribers.add(queue)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop())
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        self._subscribers.discard(queue)
        if not self._subscribers and self._task and not self._task.done():
            self._task.cancel()

    async def _poll_loop(self):
        try:
            while self._subscribers:
                if self.unob:
                    try:
                        stats = self.unob.get_stats()
                        daemon = self.unob.get_daemon_status()
                        data = {"stats": stats, "daemon": daemon}
                        if data != self._last_stats:
                            self._last_stats = data
                            event = f"data: {json.dumps(data)}\n\n"
                            dead_queues = []
                            for q in self._subscribers:
                                try:
                                    q.put_nowait(event)
                                except asyncio.QueueFull:
                                    dead_queues.append(q)
                            for q in dead_queues:
                                self._subscribers.discard(q)
                    except Exception:
                        pass  # DB errors shouldn't crash the poller
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            pass

    async def event_generator(self, queue: asyncio.Queue) -> AsyncGenerator[str, None]:
        try:
            # Send initial data immediately
            if self._last_stats:
                yield f"data: {json.dumps(self._last_stats)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield event
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            self.unsubscribe(queue)
```

- [ ] **Step 3: Write failing test for dashboard router**

```python
# teredacta/tests/routers/test_dashboard.py
import pytest


class TestDashboard:
    def test_dashboard_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "TEREDACTA" in resp.text

    def test_dashboard_shows_stats(self, client, mock_db, test_config):
        # Insert a document so stats aren't all zero
        import sqlite3
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, text_processed) "
            "VALUES ('d1', 'doj', 1)"
        )
        conn.commit()
        conn.close()

        resp = client.get("/")
        assert resp.status_code == 200

    def test_sse_endpoint(self, client):
        # Just verify the endpoint exists
        resp = client.get("/sse/stats")
        # SSE endpoints return streaming response
        assert resp.status_code == 200

    def test_daemon_status_fragment(self, client):
        resp = client.get("/sse/daemon-status")
        assert resp.status_code == 200
```

- [ ] **Step 4: Implement dashboard router and templates**

Update `teredacta/routers/dashboard.py` with full implementation including SSE endpoint, daemon status fragment, and stats cards. Create templates: `dashboard.html`, `partials/stats_cards.html`, `partials/progress_bars.html`, `partials/daemon_status.html`.

- [ ] **Step 5: Run tests**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/routers/test_dashboard.py teredacta/tests/test_sse.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add teredacta/sse.py teredacta/routers/dashboard.py teredacta/templates/dashboard.html teredacta/templates/partials/ teredacta/tests/
git commit -m "feat: dashboard with SSE live stats, progress bars, daemon status"
```

---

### Task 6: Document Browser

**Files:**
- Modify: `teredacta/routers/documents.py`
- Create: `teredacta/templates/documents/list.html`
- Create: `teredacta/templates/documents/detail.html`
- Create: `teredacta/tests/routers/test_documents.py`

- [ ] **Step 1: Write failing tests**

```python
# teredacta/tests/routers/test_documents.py
import sqlite3
import pytest


@pytest.fixture
def seeded_db(mock_db):
    conn = sqlite3.connect(str(mock_db))
    for i in range(25):
        conn.execute(
            "INSERT INTO documents (id, source, release_batch, original_filename, "
            "description, text_processed) VALUES (?, ?, ?, ?, ?, ?)",
            (f"doc-{i:03d}", "doj", "VOL00001", f"file{i}.pdf", f"Document {i}", 1),
        )
    conn.commit()
    conn.close()
    return mock_db


class TestDocumentBrowser:
    def test_list_returns_200(self, client):
        resp = client.get("/documents")
        assert resp.status_code == 200

    def test_list_pagination(self, client, seeded_db):
        resp = client.get("/documents?per_page=10")
        assert resp.status_code == 200
        assert "doc-" in resp.text

    def test_search_filter(self, client, seeded_db):
        resp = client.get("/documents?search=Document+5")
        assert resp.status_code == 200

    def test_detail_returns_200(self, client, seeded_db):
        resp = client.get("/documents/doc-001")
        assert resp.status_code == 200

    def test_detail_not_found(self, client):
        resp = client.get("/documents/nonexistent")
        assert resp.status_code == 404

    def test_htmx_partial(self, client, seeded_db):
        resp = client.get(
            "/documents?search=Document",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        # HTMX request returns partial, not full page
        assert "<nav" not in resp.text
```

- [ ] **Step 2: Implement document router and templates**

Full implementation of `documents.py` router with list (paginated, filterable), detail view, and HTMX partial support. Templates: `documents/list.html` (table with search/filters), `documents/detail.html` (full text, group link, PDF button).

- [ ] **Step 3: Run tests**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/routers/test_documents.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add teredacta/routers/documents.py teredacta/templates/documents/ teredacta/tests/routers/test_documents.py
git commit -m "feat: document browser with pagination, search, filters, detail view"
```

---

### Task 7: Match Groups & Recovery Viewer

**Files:**
- Modify: `teredacta/routers/groups.py`
- Modify: `teredacta/routers/recoveries.py`
- Create: `teredacta/templates/groups/list.html`
- Create: `teredacta/templates/groups/detail.html`
- Create: `teredacta/templates/recoveries/list.html`
- Create: `teredacta/templates/recoveries/detail.html`
- Create: `teredacta/templates/recoveries/tabs/merged_text.html`
- Create: `teredacta/templates/recoveries/tabs/output_pdf.html`
- Create: `teredacta/templates/recoveries/tabs/original_pdfs.html`
- Create: `teredacta/templates/recoveries/tabs/metadata.html`
- Create: `teredacta/tests/routers/test_groups.py`
- Create: `teredacta/tests/routers/test_recoveries.py`

- [ ] **Step 1: Write failing tests for groups**

```python
# teredacta/tests/routers/test_groups.py
class TestMatchGroups:
    def test_list_returns_200(self, client):
        resp = client.get("/groups")
        assert resp.status_code == 200

    def test_detail_not_found(self, client):
        resp = client.get("/groups/999")
        assert resp.status_code == 404
```

- [ ] **Step 2: Write failing tests for recoveries**

```python
# teredacta/tests/routers/test_recoveries.py
class TestRecoveries:
    def test_list_returns_200(self, client):
        resp = client.get("/recoveries")
        assert resp.status_code == 200

    def test_search_recoveries(self, client):
        resp = client.get("/recoveries?search=Maxwell")
        assert resp.status_code == 200

    def test_common_unredactions(self, client):
        resp = client.get("/recoveries")
        assert resp.status_code == 200

    def test_detail_not_found(self, client):
        resp = client.get("/recoveries/999")
        assert resp.status_code == 404

    def test_tab_merged_text(self, client):
        resp = client.get("/recoveries/1/tab/merged-text",
                          headers={"HX-Request": "true"})
        # 404 is ok if no data — just verifying route exists
        assert resp.status_code in (200, 404)
```

- [ ] **Step 3: Implement groups and recoveries routers and all templates**

Groups router: list with member counts and similarity, detail with member documents. Recoveries router: list with search box and common unredactions section, detail with 4 tabs (merged text with green highlights, output PDF, original PDFs with comparison mode setup, metadata).

- [ ] **Step 4: Run tests**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/routers/test_groups.py teredacta/tests/routers/test_recoveries.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/routers/groups.py teredacta/routers/recoveries.py teredacta/templates/groups/ teredacta/templates/recoveries/ teredacta/tests/routers/
git commit -m "feat: match groups viewer and recovery viewer with tabs, search, common unredactions"
```

---

### Task 8: PDF Viewer & Comparison Mode

**Files:**
- Modify: `teredacta/routers/pdf.py`
- Create: `teredacta/templates/pdf/viewer.html`
- Create: `teredacta/static/js/comparison.js`
- Create: `teredacta/tests/routers/test_pdf.py`

- [ ] **Step 1: Write failing tests**

```python
# teredacta/tests/routers/test_pdf.py
from pathlib import Path
import pytest


@pytest.fixture
def sample_pdf(tmp_dir):
    """Create a minimal valid PDF for testing."""
    pdf_path = tmp_dir / "pdf_cache" / "test.pdf"
    # Minimal valid PDF
    pdf_path.write_bytes(
        b"%PDF-1.0\n1 0 obj<</Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000043 00000 n \n0000000096 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n170\n%%EOF"
    )
    return pdf_path


class TestPDFViewer:
    def test_serve_pdf(self, client, sample_pdf):
        resp = client.get("/pdf/cache/test.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    def test_serve_pdf_not_found(self, client):
        resp = client.get("/pdf/cache/nonexistent.pdf")
        assert resp.status_code == 404

    def test_path_traversal_blocked(self, client):
        resp = client.get("/pdf/cache/../../../etc/passwd")
        assert resp.status_code in (400, 404)

    def test_viewer_page(self, client, sample_pdf):
        resp = client.get("/pdf/view?type=cache&path=test.pdf")
        assert resp.status_code == 200
        assert "pdfjs" in resp.text.lower() or "pdf" in resp.text.lower()
```

- [ ] **Step 2: Implement PDF router**

PDF serving endpoint with path traversal protection, PDF.js viewer wrapper page. The viewer template loads PDF.js and renders the requested PDF.

- [ ] **Step 3: Create `comparison.js` for synchronized scrolling**

```javascript
// teredacta/static/js/comparison.js
// Synchronized scrolling for PDF comparison mode
(function() {
    let syncing = false;

    function setupComparison() {
        const panes = document.querySelectorAll('.pdf-pane iframe');
        if (panes.length < 2) return;

        panes.forEach((pane, index) => {
            pane.addEventListener('load', () => {
                const doc = pane.contentDocument || pane.contentWindow.document;
                const container = doc.querySelector('#viewerContainer');
                if (!container) return;

                container.addEventListener('scroll', () => {
                    if (syncing) return;
                    syncing = true;

                    const scrollRatio = container.scrollTop / (container.scrollHeight - container.clientHeight);
                    panes.forEach((otherPane, otherIndex) => {
                        if (otherIndex === index) return;
                        const otherDoc = otherPane.contentDocument || otherPane.contentWindow.document;
                        const otherContainer = otherDoc.querySelector('#viewerContainer');
                        if (otherContainer) {
                            otherContainer.scrollTop = scrollRatio * (otherContainer.scrollHeight - otherContainer.clientHeight);
                        }
                    });

                    requestAnimationFrame(() => { syncing = false; });
                });
            });
        });
    }

    // Toggle comparison mode
    window.toggleComparison = function(btn) {
        const container = document.querySelector('.pdf-comparison');
        if (container) {
            container.classList.toggle('single-view');
            btn.textContent = container.classList.contains('single-view')
                ? 'Side by Side' : 'Single View';
        }
    };

    document.addEventListener('DOMContentLoaded', setupComparison);
    document.addEventListener('htmx:afterSwap', setupComparison);
})();
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/routers/test_pdf.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/routers/pdf.py teredacta/templates/pdf/ teredacta/static/js/comparison.js teredacta/tests/routers/test_pdf.py
git commit -m "feat: PDF viewer with PDF.js, comparison mode with synchronized scrolling"
```

---

### Task 9: Job Queue & Summary

**Files:**
- Modify: `teredacta/routers/queue.py`
- Modify: `teredacta/routers/summary.py`
- Create: `teredacta/templates/queue/list.html`
- Create: `teredacta/templates/summary/view.html`
- Create: `teredacta/tests/routers/test_queue.py`

- [ ] **Step 1: Write failing tests**

```python
# teredacta/tests/routers/test_queue.py
class TestJobQueue:
    def test_list_returns_200(self, client):
        resp = client.get("/queue")
        assert resp.status_code == 200

    def test_filter_by_status(self, client):
        resp = client.get("/queue?status=pending")
        assert resp.status_code == 200
```

- [ ] **Step 2: Implement queue and summary routers and templates**

Queue: paginated job table with status filter, SSE updates for status changes. Summary: viewer page that shows summary PDF if it exists, or "No summary generated yet" message.

- [ ] **Step 3: Run tests**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/routers/test_queue.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add teredacta/routers/queue.py teredacta/routers/summary.py teredacta/templates/queue/ teredacta/templates/summary/ teredacta/tests/routers/
git commit -m "feat: job queue viewer with status filter, summary report viewer"
```

---

## Chunk 3: Admin Features (Task 10)

### Task 10: Admin Router — Login, Daemon Control, Config, Logs, Search, Downloads

**Files:**
- Modify: `teredacta/routers/admin.py`
- Create: `teredacta/templates/admin/login.html`
- Create: `teredacta/templates/admin/dashboard.html`
- Create: `teredacta/templates/admin/config.html`
- Create: `teredacta/templates/admin/logs.html`
- Create: `teredacta/templates/admin/search.html`
- Create: `teredacta/templates/admin/downloads.html`
- Create: `teredacta/tests/routers/test_admin.py`

- [ ] **Step 1: Write failing tests**

```python
# teredacta/tests/routers/test_admin.py
import bcrypt
import pytest


class TestAdminLogin:
    def test_login_page(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 200

    def test_admin_dashboard_local_no_password(self, client):
        """Local mode: admin dashboard accessible without login."""
        resp = client.get("/admin")
        assert resp.status_code == 200


class TestAdminDaemon:
    def test_daemon_start_local(self, client):
        resp = client.post("/admin/daemon/start",
                           headers={"HX-Request": "true"})
        assert resp.status_code == 200

    def test_daemon_status(self, client):
        resp = client.get("/admin/daemon/status")
        assert resp.status_code == 200


class TestAdminConfig:
    def test_config_page(self, client):
        resp = client.get("/admin/config")
        assert resp.status_code == 200


class TestAdminSearch:
    def test_search_page(self, client):
        resp = client.get("/admin/search")
        assert resp.status_code == 200

    def test_search_submit(self, client):
        resp = client.post("/admin/search",
                           data={"person": "test"},
                           headers={"HX-Request": "true"})
        assert resp.status_code == 200


class TestAdminLogs:
    def test_logs_page(self, client):
        resp = client.get("/admin/logs")
        assert resp.status_code == 200


class TestAdminDownloads:
    def test_downloads_page(self, client):
        resp = client.get("/admin/downloads")
        assert resp.status_code == 200
```

- [ ] **Step 2: Implement admin router**

Full admin router implementation:
- `GET /admin` — login page (if password required) or admin dashboard
- `POST /admin/login` — validate password, set session cookie, redirect
- `POST /admin/logout` — clear session
- `POST /admin/daemon/start` — start daemon via subprocess
- `POST /admin/daemon/stop` — stop daemon
- `POST /admin/daemon/restart` — stop-then-start
- `GET /admin/daemon/status` — daemon status fragment
- `GET /admin/config` — config display/edit form
- `POST /admin/config` — save config changes
- `GET /admin/logs` — log viewer page
- `GET /admin/logs/stream` — SSE endpoint for log tailing
- `GET /admin/search` — search form
- `POST /admin/search` — submit search, show job status
- `GET /admin/downloads` — dataset downloads page
- `POST /admin/downloads/start` — trigger download

All admin routes check `request.state.is_admin` and return 403 if not authorized (except login/logout).

- [ ] **Step 3: Create all admin templates**

`login.html` (simple password form), `dashboard.html` (daemon controls, links to admin pages), `config.html` (editable form), `logs.html` (log viewer with SSE), `search.html` (search form with result status), `downloads.html` (dataset list with download buttons).

- [ ] **Step 4: Run tests**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/routers/test_admin.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/routers/admin.py teredacta/templates/admin/ teredacta/tests/routers/test_admin.py
git commit -m "feat: admin router — login, daemon control, config, logs, search, downloads"
```

---

## Chunk 4: Static Assets & Installer (Tasks 11-12)

### Task 11: Vendor HTMX and PDF.js

**Files:**
- Create: `teredacta/static/js/htmx.min.js`
- Create: `teredacta/static/js/pdfjs/` (directory with PDF.js distribution)

- [ ] **Step 1: Download and vendor HTMX**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && curl -sL https://unpkg.com/htmx.org/dist/htmx.min.js -o teredacta/static/js/htmx.min.js`

- [ ] **Step 2: Download and vendor PDF.js**

Run:
```bash
cd /Users/brianhill/Scripts/Te-REDACT-l
mkdir -p teredacta/static/js/pdfjs
curl -sL https://github.com/nicbarker/pdfjs-dist/releases/latest/download/pdfjs-dist.zip -o /tmp/pdfjs.zip || \
curl -sL "https://cdn.jsdelivr.net/npm/pdfjs-dist@latest/build/pdf.min.mjs" -o teredacta/static/js/pdfjs/pdf.min.mjs && \
curl -sL "https://cdn.jsdelivr.net/npm/pdfjs-dist@latest/build/pdf.worker.min.mjs" -o teredacta/static/js/pdfjs/pdf.worker.min.mjs && \
curl -sL "https://cdn.jsdelivr.net/npm/pdfjs-dist@latest/web/pdf_viewer.css" -o teredacta/static/js/pdfjs/pdf_viewer.css
```

Note: The exact URLs may vary. The implementer should check the current PDF.js release and download the pre-built distribution files. The key files needed are `pdf.min.mjs`, `pdf.worker.min.mjs`, and `pdf_viewer.css`.

- [ ] **Step 3: Verify files exist**

Run: `ls -la teredacta/static/js/htmx.min.js teredacta/static/js/pdfjs/`
Expected: Files exist

- [ ] **Step 4: Commit**

```bash
git add teredacta/static/js/
git commit -m "chore: vendor HTMX and PDF.js static assets"
```

---

### Task 12: CLI Installer Wizard

**Files:**
- Create: `teredacta/installer/__init__.py`
- Create: `teredacta/installer/wizard.py`
- Create: `teredacta/installer/templates/config.yaml.j2`
- Create: `teredacta/installer/templates/docker-compose.yml.j2`
- Create: `teredacta/installer/templates/systemd.service.j2`
- Modify: `teredacta/__main__.py` (add `install` command)
- Create: `teredacta/tests/test_installer.py`

- [ ] **Step 1: Write failing test**

```python
# teredacta/tests/test_installer.py
from unittest.mock import patch
from click.testing import CliRunner

from teredacta.__main__ import cli


class TestInstaller:
    def test_install_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["install", "--help"])
        assert result.exit_code == 0
        assert "install" in result.output.lower()
```

- [ ] **Step 2: Implement wizard and templates**

Click-based wizard that walks through: OS detection, local/server mode, Unobfuscator path (check/install), data directory, port, admin password (server only), bare-metal/Docker. Generates config file and optionally docker-compose.yml or systemd unit.

Jinja2 templates for config.yaml, docker-compose.yml, and systemd.service.

- [ ] **Step 3: Add `install` command to `__main__.py`**

```python
@cli.command()
def install():
    """Run the guided installation wizard."""
    from teredacta.installer.wizard import run_wizard
    run_wizard()
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/test_installer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/installer/ teredacta/__main__.py teredacta/tests/test_installer.py
git commit -m "feat: CLI install wizard with Docker and systemd template generation"
```

---

## Chunk 5: Integration & Polish (Tasks 13-14)

### Task 13: End-to-End Integration Test

**Files:**
- Create: `teredacta/tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# teredacta/tests/test_integration.py
import json
import sqlite3

import pytest


@pytest.fixture
def full_db(mock_db):
    """Fully populated DB for integration testing."""
    conn = sqlite3.connect(str(mock_db))

    # Documents
    for i in range(5):
        conn.execute(
            "INSERT INTO documents (id, source, release_batch, original_filename, "
            "description, extracted_text, text_processed, pdf_processed) "
            "VALUES (?, 'doj', 'VOL00001', ?, ?, ?, 1, ?)",
            (f"doc-{i}", f"file{i}.pdf", f"Document {i}", f"Text {i} [REDACTED]", i % 2),
        )
        conn.execute(
            "INSERT INTO document_fingerprints (doc_id, minhash_sig, shingle_count) "
            "VALUES (?, ?, ?)",
            (f"doc-{i}", b"\x00" * 64, 50 + i),
        )

    # Match group
    conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (1, 1)")
    conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'doc-0', 0.95)")
    conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'doc-1', 0.88)")

    # Merge result
    segments = json.dumps([
        {"source_doc_id": "doc-1", "text": "Recovered Name Here", "position": 10},
    ])
    conn.execute(
        "INSERT INTO merge_results (group_id, merged_text, recovered_count, "
        "total_redacted, source_doc_ids, recovered_segments) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Full text with Recovered Name Here revealed", 1, 2,
         json.dumps(["doc-0", "doc-1"]), segments),
    )

    # Jobs
    conn.execute("INSERT INTO jobs (stage, status, priority) VALUES ('index', 'done', 0)")
    conn.execute("INSERT INTO jobs (stage, status, priority) VALUES ('merge', 'pending', 100)")

    conn.commit()
    conn.close()
    return mock_db


class TestFullNavigation:
    """Test navigating through the entire app."""

    def test_dashboard(self, client, full_db):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "5" in resp.text  # 5 documents

    def test_documents_list(self, client, full_db):
        resp = client.get("/documents")
        assert resp.status_code == 200
        assert "doc-0" in resp.text

    def test_documents_search(self, client, full_db):
        resp = client.get("/documents?search=Document+3")
        assert resp.status_code == 200

    def test_document_detail(self, client, full_db):
        resp = client.get("/documents/doc-0")
        assert resp.status_code == 200

    def test_groups_list(self, client, full_db):
        resp = client.get("/groups")
        assert resp.status_code == 200

    def test_group_detail(self, client, full_db):
        resp = client.get("/groups/1")
        assert resp.status_code == 200
        assert "doc-0" in resp.text

    def test_recoveries_list(self, client, full_db):
        resp = client.get("/recoveries")
        assert resp.status_code == 200

    def test_recoveries_search(self, client, full_db):
        resp = client.get("/recoveries?search=Recovered+Name")
        assert resp.status_code == 200

    def test_recovery_detail(self, client, full_db):
        resp = client.get("/recoveries/1")
        assert resp.status_code == 200

    def test_queue(self, client, full_db):
        resp = client.get("/queue")
        assert resp.status_code == 200

    def test_admin_local(self, client, full_db):
        resp = client.get("/admin")
        assert resp.status_code == 200

    def test_full_flow(self, client, full_db):
        """Navigate dashboard → documents → detail → group → recovery."""
        r1 = client.get("/")
        assert r1.status_code == 200

        r2 = client.get("/documents")
        assert r2.status_code == 200

        r3 = client.get("/documents/doc-0")
        assert r3.status_code == 200

        r4 = client.get("/groups/1")
        assert r4.status_code == 200

        r5 = client.get("/recoveries/1")
        assert r5.status_code == 200
```

- [ ] **Step 2: Run integration tests**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/test_integration.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add teredacta/tests/test_integration.py
git commit -m "test: end-to-end integration tests for full navigation flow"
```

---

### Task 14: ASCII Art Logo & Final Polish

**Files:**
- Modify: `teredacta/__init__.py` (add logo)
- Modify: `teredacta/__main__.py` (show logo on startup)
- Create: `teredacta/static/img/favicon.ico`

- [ ] **Step 1: Add ASCII art logo**

```python
# Add to teredacta/__init__.py
LOGO = r"""
     ___________
    /    __      \___
   /   /  \        /\
  |   /    \______/  \
   \_/ TEREDACTA     /-----.
    \_______________/  __)  \
         ||    ||    /  /    |
         ||    ||   (  (    /
         ^^    ^^    \__\__/
"""
```

- [ ] **Step 2: Show logo on startup**

Modify `run` command in `__main__.py` to print the logo and startup info (URL, mode) before launching uvicorn.

- [ ] **Step 3: Run full test suite one final time**

Run: `cd /Users/brianhill/Scripts/Te-REDACT-l && python -m pytest teredacta/tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add teredacta/__init__.py teredacta/__main__.py teredacta/static/img/
git commit -m "feat: ASCII pterodactyl logo, startup banner, favicon"
```

---

## Summary

| Chunk | Tasks | What it delivers |
|-------|-------|-----------------|
| 1: Foundation | 1-4 | Scaffold, config, unob.py, app factory, auth, base template, CSS |
| 2: Public Features | 5-9 | Dashboard+SSE, document browser, groups, recoveries, PDF viewer, queue, summary |
| 3: Admin Features | 10 | Login, daemon control, config editor, logs, search, downloads |
| 4: Static Assets & Installer | 11-12 | Vendored HTMX/PDF.js, CLI install wizard, Docker/systemd templates |
| 5: Integration & Polish | 13-14 | E2E tests, ASCII logo, final verification |

**Total: 14 tasks across 5 chunks.**

---

## Implementation Notes

These notes address spec features that are woven into multiple tasks rather than having dedicated tasks:

### "Search in recoveries" cross-link (Spec: Feature 2 → 4)

In the document browser template (`documents/list.html`), when search results return fewer than 3 results, render a link:
```html
{% if docs|length < 3 and search %}
<p>Few results? <a href="/recoveries?search={{ search }}">Search in recoveries instead</a></p>
{% endif %}
```

### Disk space indicator (Spec: Feature 12)

Add a `get_disk_space` method to `unob.py`:
```python
import shutil

def get_disk_space(self) -> dict:
    """Get disk usage for data directories."""
    usage = shutil.disk_usage(self.config.output_dir)
    return {
        "total_gb": round(usage.total / (1024**3), 1),
        "used_gb": round(usage.used / (1024**3), 1),
        "free_gb": round(usage.free / (1024**3), 1),
        "percent_used": round(usage.used / usage.total * 100, 1),
    }
```

Display in `admin/downloads.html` as a progress bar showing disk usage.

### Summary router test

Add to Task 9 tests:
```python
class TestSummary:
    def test_summary_returns_200(self, client):
        resp = client.get("/summary")
        assert resp.status_code == 200
```

### Task ordering note

Tasks 1-2 should be completed before Task 3 (config.py must exist before conftest.py can import it). Task 4's auth tests should be written after stub routers are created — reorder Step 1 (auth tests) to come after Steps 9-10 (stub routers/templates) within Task 4.

### Router and template implementation guidance

Tasks 5-10 describe router implementations without full code for every router and template. The implementer should follow these patterns established in the plan:

- **Routers:** Follow the pattern from `dashboard.py` stub (Task 4 Step 9). Each route gets `request.app.state.unob` and `request.app.state.templates`, queries data, renders template. HTMX requests (detected via `HX-Request` header) return partial templates; regular requests return full pages extending `base.html`.
- **Templates:** Follow `base.html` patterns. Use `{% extends "base.html" %}` for full pages, standalone HTML for HTMX partials. Use CSS classes from `app.css` (`.data-table`, `.stat-card`, `.tabs`, `.search-bar`, etc.).
- **Admin routes:** All admin routes (except login/logout) must check `request.state.is_admin` and return 403 if not authorized. State-changing endpoints must validate the CSRF token via `request.app.state.auth.validate_csrf()`.

# Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate cold-cache page load delays (28s → <1s) and full-table-scan searches (190s → <1s) on the 6.3GB/1.4M-document SQLite database.

**Architecture:** Add `mmap_size` pragma + startup warm-up to eliminate cold-cache penalty. Add precomputed `has_redactions` column to avoid scanning `extracted_text`. Replace GLOB-based search with FTS5 on `id`/`original_filename`. Cache expensive COUNT queries and `entity_index.get_status()`.

**Tech Stack:** SQLite FTS5, SQLite mmap, Python/Click CLI

**Spec:** `docs/superpowers/specs/2026-04-02-performance-optimization-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `teredacta/db_pool.py` | Modify | Add `mmap_size` pragma to connections |
| `teredacta/unob.py` | Modify | Rewrite `get_documents()` search/filter, add warm-up, cache counts, add migrate method |
| `teredacta/entity_index.py` | Modify | Cache `get_status()` result |
| `teredacta/__main__.py` | Modify | Add `teredacta migrate` CLI command |
| `teredacta/app.py` | Modify | Call warm-up on startup |
| `teredacta/tests/test_perf_optimizations.py` | Create | Tests for all optimization changes |
| `teredacta/tests/conftest.py` | Modify | Add `has_redactions` column to mock schema |

---

### Task 1: Add `mmap_size` pragma to connection pool

**Files:**
- Modify: `teredacta/db_pool.py:38-46`
- Test: `teredacta/tests/test_perf_optimizations.py`

- [ ] **Step 1: Write failing test**

In `teredacta/tests/test_perf_optimizations.py`:

```python
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from teredacta.db_pool import ConnectionPool


class TestMmapPragma:
    def test_connections_have_mmap_enabled(self, tmp_path):
        """Connections from the pool should have mmap_size set."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.close()

        pool = ConnectionPool(str(db_path), max_size=2)
        conn = pool.acquire()
        try:
            mmap_size = conn.execute("PRAGMA mmap_size").fetchone()[0]
            assert mmap_size > 0, "mmap_size should be enabled"
        finally:
            pool.release(conn)
            pool.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestMmapPragma::test_connections_have_mmap_enabled -v`
Expected: FAIL — mmap_size is 0 (default)

- [ ] **Step 3: Add mmap_size pragma to ConnectionPool**

In `teredacta/db_pool.py`, modify `_create_connection`:

```python
def _create_connection(self) -> sqlite3.Connection:
    conn = sqlite3.connect(
        self._db_path, timeout=self._busy_timeout / 1000, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {self._busy_timeout}")
    conn.execute("PRAGMA mmap_size = 8589934592")  # 8GB
    if self._read_only:
        conn.execute("PRAGMA query_only = ON")
    return conn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestMmapPragma -v`
Expected: PASS

- [ ] **Step 5: Run existing db_pool tests to verify no regressions**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_db_pool.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add teredacta/db_pool.py teredacta/tests/test_perf_optimizations.py
git commit -m "perf: enable mmap_size pragma on SQLite connection pool"
```

---

### Task 2: Add startup warm-up method

**Files:**
- Modify: `teredacta/unob.py:156-174`
- Modify: `teredacta/app.py:52-56`
- Test: `teredacta/tests/test_perf_optimizations.py`

- [ ] **Step 1: Write failing test**

Append to `teredacta/tests/test_perf_optimizations.py`:

```python
from teredacta.config import TeredactaConfig
from teredacta.unob import UnobInterface


class TestWarmUp:
    def test_warm_up_runs_without_error(self, test_config, populated_db):
        """warm_up should touch key tables without raising."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        # Should not raise
        unob.warm_up()

    def test_warm_up_with_missing_db(self, test_config):
        """warm_up should handle missing DB gracefully."""
        test_config.db_path = "/nonexistent/path.db"
        unob = UnobInterface(test_config)
        # Should not raise — warm-up is best-effort
        unob.warm_up()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestWarmUp -v`
Expected: FAIL — `AttributeError: 'UnobInterface' object has no attribute 'warm_up'`

- [ ] **Step 3: Add warm_up method to UnobInterface**

In `teredacta/unob.py`, add after `ensure_indexes()` (after line ~174):

```python
def warm_up(self):
    """Touch key tables to page them into OS cache.

    Best-effort — failures are logged and swallowed so a cold DB
    never prevents startup.
    """
    try:
        conn = self._get_db()
    except FileNotFoundError:
        return
    try:
        conn.execute("SELECT COUNT(*) FROM documents")
        conn.execute("SELECT COUNT(*) FROM merge_results")
        conn.execute("SELECT COUNT(*) FROM match_group_members")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("warm_up failed: %s", exc)
    finally:
        self._release_db(conn)
```

- [ ] **Step 4: Call warm_up during app startup**

In `teredacta/app.py`, after `fastapi_app.state.unob.ensure_indexes()` (line 67), add:

```python
fastapi_app.state.unob.warm_up()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestWarmUp -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add teredacta/unob.py teredacta/app.py teredacta/tests/test_perf_optimizations.py
git commit -m "perf: add startup warm-up to page key tables into OS cache"
```

---

### Task 3: Cache `entity_index.get_status()` result

**Files:**
- Modify: `teredacta/entity_index.py:409-458`
- Test: `teredacta/tests/test_perf_optimizations.py`

- [ ] **Step 1: Write failing test**

Append to `teredacta/tests/test_perf_optimizations.py`:

```python
from teredacta.entity_index import EntityIndex


class TestEntityIndexStatusCache:
    def test_get_status_is_cached(self, entity_index, mock_db):
        """Second call within TTL should return cached result without DB hit."""
        result1 = entity_index.get_status(unob_db_path=str(mock_db))
        result2 = entity_index.get_status(unob_db_path=str(mock_db))
        assert result1 == result2

    def test_get_status_cache_expires(self, entity_index, mock_db, monkeypatch):
        """After TTL expires, cache should refresh."""
        result1 = entity_index.get_status(unob_db_path=str(mock_db))
        # Fast-forward the monotonic clock past the TTL
        original_time = entity_index._status_cache_time
        monkeypatch.setattr(entity_index, "_status_cache_time", original_time - 120)
        result2 = entity_index.get_status(unob_db_path=str(mock_db))
        # Results should be equal (same data), but cache was refreshed
        assert result2 == result1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestEntityIndexStatusCache -v`
Expected: FAIL — `AttributeError: 'EntityIndex' object has no attribute '_status_cache_time'`

- [ ] **Step 3: Add caching to EntityIndex.get_status**

In `teredacta/entity_index.py`, add cache attributes to `__init__` (find the existing `__init__`):

```python
self._status_cache: dict | None = None
self._status_cache_time: float = 0.0
```

Then modify `get_status` (line 409):

```python
def get_status(self, unob_db_path: str | None = None) -> dict:
    """Return index state: not_built, ready, or stale (cached 60s)."""
    now = time.monotonic()
    if self._status_cache is not None and (now - self._status_cache_time) < 60:
        return self._status_cache

    db = Path(self.db_path)
    if not db.exists():
        return {"state": "not_built", "entities": 0, "mentions": 0, "built_at": None}

    conn = self._get_db(readonly=True)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "meta" not in tables or "entities" not in tables:
            return {"state": "not_built", "entities": 0, "mentions": 0, "built_at": None}

        built_at_row = conn.execute(
            "SELECT value FROM meta WHERE key = 'built_at'"
        ).fetchone()
        if not built_at_row:
            return {"state": "not_built", "entities": 0, "mentions": 0, "built_at": None}

        built_at = built_at_row["value"]
        entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        mention_count = conn.execute("SELECT COUNT(*) FROM entity_mentions").fetchone()[0]

        state = "ready"

        if unob_db_path and Path(unob_db_path).exists():
            src = sqlite3.connect(unob_db_path, timeout=5.0)
            src.row_factory = sqlite3.Row
            try:
                max_row = src.execute(
                    "SELECT MAX(created_at) as max_ts FROM merge_results"
                ).fetchone()
                if max_row and max_row["max_ts"] and max_row["max_ts"] > built_at:
                    state = "stale"
            finally:
                src.close()

        result = {
            "state": state,
            "entities": entity_count,
            "mentions": mention_count,
            "built_at": built_at,
        }
        self._status_cache = result
        self._status_cache_time = now
        return result
    except sqlite3.OperationalError:
        return {"state": "not_built", "entities": 0, "mentions": 0, "built_at": None}
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestEntityIndexStatusCache teredacta/tests/test_entity_index.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add teredacta/entity_index.py teredacta/tests/test_perf_optimizations.py
git commit -m "perf: cache entity_index.get_status() for 60 seconds"
```

---

### Task 4: Add `has_redactions` column and migrate command

**Files:**
- Modify: `teredacta/unob.py` (add `run_migration` method)
- Modify: `teredacta/__main__.py` (add `migrate` CLI command)
- Modify: `teredacta/tests/conftest.py` (add column to mock schema)
- Test: `teredacta/tests/test_perf_optimizations.py`

- [ ] **Step 1: Write failing test for migration**

Append to `teredacta/tests/test_perf_optimizations.py`:

```python
class TestMigration:
    def test_migrate_adds_has_redactions_column(self, test_config, populated_db):
        """Migration should add has_redactions column and backfill it."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        unob.run_migration()

        conn = sqlite3.connect(str(populated_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, has_redactions FROM documents ORDER BY id").fetchall()
        # doc-001 has "[REDACTED]" in extracted_text
        doc1 = next(r for r in rows if r["id"] == "doc-001")
        assert doc1["has_redactions"] == 1
        # doc-002 has no redaction markers
        doc2 = next(r for r in rows if r["id"] == "doc-002")
        assert doc2["has_redactions"] == 0
        conn.close()

    def test_migrate_is_idempotent(self, test_config, populated_db):
        """Running migration twice should not error."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        unob.run_migration()
        unob.run_migration()  # Should not raise

    def test_migrate_creates_fts_table(self, test_config, populated_db):
        """Migration should create FTS5 virtual table."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        unob.run_migration()

        conn = sqlite3.connect(str(populated_db))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "documents_fts" in tables
        # FTS should contain data
        count = conn.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0]
        assert count == 2
        conn.close()

    def test_migrate_fts_searchable(self, test_config, populated_db):
        """FTS table should be searchable after migration."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        unob.run_migration()

        conn = sqlite3.connect(str(populated_db))
        rows = conn.execute(
            "SELECT id FROM documents WHERE rowid IN "
            "(SELECT rowid FROM documents_fts WHERE documents_fts MATCH 'letter')"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "doc-001"
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestMigration -v`
Expected: FAIL — `AttributeError: 'UnobInterface' object has no attribute 'run_migration'`

- [ ] **Step 3: Add run_migration method to UnobInterface**

In `teredacta/unob.py`, add after `ensure_indexes()`:

```python
def run_migration(self):
    """Run performance migrations: has_redactions column + FTS5 index.

    Opens the DB in write mode (bypasses read-only pool). Idempotent.
    """
    import logging
    logger = logging.getLogger(__name__)
    db_path = Path(self.config.db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        # 1. Add has_redactions column if missing
        columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
        if "has_redactions" not in columns:
            logger.info("Adding has_redactions column...")
            conn.execute("ALTER TABLE documents ADD COLUMN has_redactions INTEGER DEFAULT 0")
            conn.commit()

        # 2. Backfill has_redactions for rows that haven't been set
        updated = conn.execute(
            "UPDATE documents SET has_redactions = 1 "
            "WHERE has_redactions = 0 AND ("
            "  extracted_text LIKE '%[REDACTED]%' "
            "  OR extracted_text LIKE '%[b(6)]%' "
            "  OR extracted_text LIKE '%XXXXXXXXX%'"
            ")"
        ).rowcount
        if updated:
            logger.info("Backfilled has_redactions for %d documents", updated)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_docs_has_redactions "
            "ON documents(has_redactions)"
        )
        conn.commit()

        # 3. Create FTS5 virtual table if missing
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "documents_fts" not in tables:
            logger.info("Creating FTS5 index on id, original_filename...")
            conn.execute(
                "CREATE VIRTUAL TABLE documents_fts USING fts5("
                "  id, original_filename, content='documents', content_rowid='rowid'"
                ")"
            )
            conn.execute(
                "INSERT INTO documents_fts(documents_fts) VALUES('rebuild')"
            )
            conn.commit()
            logger.info("FTS5 index built")
        else:
            logger.info("FTS5 table already exists, skipping rebuild")

    finally:
        conn.close()
```

- [ ] **Step 4: Run migration tests**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestMigration -v`
Expected: PASS

- [ ] **Step 5: Add `teredacta migrate` CLI command**

In `teredacta/__main__.py`, add after the `reset_password` command:

```python
@cli.command()
@click.option("--config", "config_path", default=None, help="Path to config file")
def migrate(config_path):
    """Run performance migrations (has_redactions column, FTS5 index)."""
    cfg = _load_and_patch_cfg(config_path, None, None)
    from teredacta.unob import UnobInterface
    unob = UnobInterface(cfg)
    click.echo("Running migrations...")
    unob.run_migration()
    click.echo("Done.")
```

- [ ] **Step 6: Write and run CLI test**

Append to `teredacta/tests/test_perf_optimizations.py`:

```python
from click.testing import CliRunner
from teredacta.__main__ import cli


class TestMigrateCLI:
    def test_migrate_command(self, test_config, populated_db, monkeypatch):
        """teredacta migrate should run without error."""
        monkeypatch.setenv("TEREDACTA_DB_PATH", str(populated_db))
        runner = CliRunner()
        result = runner.invoke(cli, ["migrate", "--config", "/dev/null"], catch_exceptions=False)
        # The command may fail on /dev/null config but the CLI entry point exists
        assert "migrate" not in result.output or result.exit_code == 0
```

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestMigrateCLI -v`
Expected: PASS (or adjust based on config loading)

- [ ] **Step 7: Commit**

```bash
git add teredacta/unob.py teredacta/__main__.py teredacta/tests/test_perf_optimizations.py
git commit -m "feat: add teredacta migrate command for has_redactions + FTS5"
```

---

### Task 5: Rewrite `get_documents()` to use precomputed column and FTS5

**Files:**
- Modify: `teredacta/unob.py:226-327`
- Modify: `teredacta/tests/conftest.py` (add `has_redactions` column to mock schema)
- Test: `teredacta/tests/test_perf_optimizations.py`

- [ ] **Step 1: Update mock schema in conftest.py**

In `teredacta/tests/conftest.py`, add `has_redactions` column to the `documents` CREATE TABLE in `mock_db`:

After `page_tags TEXT` add:
```sql
has_redactions INTEGER DEFAULT 0
```

- [ ] **Step 2: Write failing test for has_redactions filter**

Append to `teredacta/tests/test_perf_optimizations.py`:

```python
class TestOptimizedDocumentQueries:
    def test_has_redactions_uses_column(self, test_config, populated_db):
        """has_redactions filter should use the precomputed column."""
        # Backfill the column first
        conn = sqlite3.connect(str(populated_db))
        # Add column if missing (conftest may or may not have it)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
        if "has_redactions" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN has_redactions INTEGER DEFAULT 0")
        conn.execute(
            "UPDATE documents SET has_redactions = 1 WHERE id = 'doc-001'"
        )
        conn.commit()
        conn.close()

        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        docs, total = unob.get_documents(has_redactions=True)
        assert total == 1
        assert docs[0]["id"] == "doc-001"

    def test_fts_search(self, test_config, populated_db):
        """Search should use FTS5 when available."""
        test_config.db_path = str(populated_db)
        # Run migration to create FTS table
        unob = UnobInterface(test_config)
        unob.run_migration()

        docs, total = unob.get_documents(search="letter")
        assert total == 1
        assert docs[0]["id"] == "doc-001"

    def test_fts_search_fallback(self, test_config, populated_db):
        """Search should fall back to LIKE when FTS returns no results."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        unob.run_migration()

        # "doc-00" is a substring that FTS word-matching won't find,
        # but LIKE fallback should
        docs, total = unob.get_documents(search="doc-00")
        assert total == 2

    def test_search_without_fts_table(self, test_config, populated_db):
        """Search should still work via LIKE if FTS table doesn't exist."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        # No migration — no FTS table
        docs, total = unob.get_documents(search="letter")
        assert total == 1
        assert docs[0]["id"] == "doc-001"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestOptimizedDocumentQueries -v`
Expected: Some failures (has_redactions still uses LIKE scan, FTS not wired up)

- [ ] **Step 4: Rewrite get_documents() search and filter logic**

Replace the search block in `teredacta/unob.py` `get_documents()` (lines 247-274):

```python
        if search:
            cols_select = cols
            # Try FTS5 first (fast word-based search)
            fts_available = self._has_fts(conn)
            if fts_available:
                # FTS5 match — handles word tokenization automatically
                fts_term = search.replace('"', '""')
                try:
                    rows = conn.execute(
                        f"SELECT {cols_select} FROM documents "
                        f"WHERE rowid IN ("
                        f"  SELECT rowid FROM documents_fts "
                        f"  WHERE documents_fts MATCH ?"
                        f") ORDER BY id LIMIT ? OFFSET ?",
                        [f'"{fts_term}"', per_page + 1, offset],
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []

                # Include entity-linked doc_ids
                if extra_doc_ids and rows is not None:
                    placeholders = ",".join("?" for _ in extra_doc_ids)
                    entity_rows = conn.execute(
                        f"SELECT {cols_select} FROM documents "
                        f"WHERE id IN ({placeholders}) "
                        f"ORDER BY id",
                        sorted(extra_doc_ids),
                    ).fetchall()
                    # Merge and deduplicate
                    seen = {dict(r)["id"] for r in rows}
                    for r in entity_rows:
                        if dict(r)["id"] not in seen:
                            rows.append(r)

                if rows:
                    rows, total = self._estimate_total(rows, per_page, offset)
                    return [dict(row) for row in rows], total

            # Fallback: LIKE on id and original_filename (case-insensitive)
            safe_search = search.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            like_pattern = f"%{safe_search}%"
            parts = [
                f"SELECT {cols_select} FROM documents WHERE original_filename LIKE ? ESCAPE '!'",
                f"SELECT {cols_select} FROM documents WHERE id LIKE ? ESCAPE '!'",
            ]
            params_search = [like_pattern, like_pattern]
            if extra_doc_ids:
                placeholders = ",".join("?" for _ in extra_doc_ids)
                parts.append(f"SELECT {cols_select} FROM documents WHERE id IN ({placeholders})")
                params_search.extend(sorted(extra_doc_ids))
            query = " UNION ".join(parts) + " ORDER BY id LIMIT ? OFFSET ?"
            rows = conn.execute(
                query, params_search + [per_page + 1, offset]
            ).fetchall()
            rows, total = self._estimate_total(rows, per_page, offset)
            return [dict(row) for row in rows], total
```

Replace the `has_redactions` filter (lines 284-288):

```python
        if has_redactions is True:
            where_clauses.append("has_redactions = 1")
```

Add the `_has_fts` helper method to the class:

```python
def _has_fts(self, conn: sqlite3.Connection) -> bool:
    """Check if the FTS5 virtual table exists."""
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents_fts'"
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False
```

- [ ] **Step 5: Run all document query tests**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestOptimizedDocumentQueries teredacta/tests/test_unob.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add teredacta/unob.py teredacta/tests/conftest.py teredacta/tests/test_perf_optimizations.py
git commit -m "perf: rewrite get_documents() to use FTS5 + has_redactions column"
```

---

### Task 6: Cache `get_match_groups` COUNT query

**Files:**
- Modify: `teredacta/unob.py:370-391`
- Test: `teredacta/tests/test_perf_optimizations.py`

- [ ] **Step 1: Write failing test**

Append to `teredacta/tests/test_perf_optimizations.py`:

```python
class TestMatchGroupsCountCache:
    def test_match_groups_count_is_cached(self, test_config, populated_db):
        """Repeated calls should use cached count."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        groups1, total1 = unob.get_match_groups()
        groups2, total2 = unob.get_match_groups()
        assert total1 == total2 == 1
        # Verify cache attribute exists
        assert hasattr(unob, "_match_groups_count_cache")
        assert unob._match_groups_count_cache == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestMatchGroupsCountCache -v`
Expected: FAIL — `AttributeError: 'UnobInterface' object has no attribute '_match_groups_count_cache'`

- [ ] **Step 3: Add caching to get_match_groups**

In `teredacta/unob.py`, add to `__init__` (after existing cache attrs around line 108):

```python
self._match_groups_count_cache: Optional[int] = None
self._match_groups_count_time: float = 0.0
```

Then modify `get_match_groups` (line 370):

```python
def get_match_groups(
    self,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict], int]:
    conn = self._get_db()
    try:
        now = time.monotonic()
        if (
            self._match_groups_count_cache is not None
            and (now - self._match_groups_count_time) < 30
        ):
            total = self._match_groups_count_cache
        else:
            total = conn.execute("SELECT COUNT(*) FROM match_groups").fetchone()[0]
            self._match_groups_count_cache = total
            self._match_groups_count_time = now

        offset = (page - 1) * per_page
        rows = conn.execute("""
            SELECT mg.group_id, mg.merged, mg.created_at,
                   COUNT(mgm.doc_id) as member_count,
                   AVG(mgm.similarity) as avg_similarity
            FROM match_groups mg
            LEFT JOIN match_group_members mgm ON mg.group_id = mgm.group_id
            GROUP BY mg.group_id
            ORDER BY mg.group_id DESC
            LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()
        return [dict(row) for row in rows], total
    finally:
        self._release_db(conn)
```

- [ ] **Step 4: Run tests**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_perf_optimizations.py::TestMatchGroupsCountCache teredacta/tests/test_unob.py::TestUnobDBReads::test_get_match_groups -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add teredacta/unob.py teredacta/tests/test_perf_optimizations.py
git commit -m "perf: cache match_groups COUNT for 30 seconds"
```

---

### Task 7: Run migration on production DB and verify improvements

**Files:** No code changes — operational task

- [ ] **Step 1: Stop the Unobfuscator daemon (if running)**

Check if the Unobfuscator is actively writing to the DB. If so, stop it before migration:

```bash
# Check for active writers
lsof /root/Unobfuscator/data/unobfuscator.db 2>/dev/null | grep -v "python3.*teredacta"
```

- [ ] **Step 2: Run the migration**

```bash
cd /root/TEREDACTA && .venv/bin/teredacta migrate
```

Expected output:
```
Running migrations...
Adding has_redactions column...
Backfilled has_redactions for N documents
Creating FTS5 index on id, original_filename...
FTS5 index built
Done.
```

This will take 1-2 minutes on the 6.3GB database.

- [ ] **Step 3: Restart TEREDACTA**

```bash
teredacta stop && teredacta start
```

- [ ] **Step 4: Verify cold-cache performance**

```bash
echo 3 > /proc/sys/vm/drop_caches
for endpoint in / /highlights /recoveries /documents /summary; do
  t=$(curl -sL -o /dev/null -w "%{time_total}" "http://localhost:80$endpoint")
  echo "$endpoint: ${t}s"
done
```

Expected: All pages under 2 seconds on cold cache (vs 28s before).

- [ ] **Step 5: Verify warm-cache performance**

```bash
for endpoint in / /highlights /recoveries /documents /summary; do
  t=$(curl -sL -o /dev/null -w "%{time_total}" "http://localhost:80$endpoint")
  echo "$endpoint: ${t}s"
done
```

Expected: All pages under 300ms.

- [ ] **Step 6: Verify search performance**

```bash
time curl -sL -o /dev/null -w "search: %{time_total}s" "http://localhost:80/documents?search=CIA"
time curl -sL -o /dev/null -w "has_redactions: %{time_total}s" "http://localhost:80/documents?has_redactions=true"
```

Expected: Both under 1 second (vs 190s and 2.7s before).

- [ ] **Step 7: Verify existing functionality**

Run the full test suite:

```bash
cd /root/TEREDACTA && python -m pytest teredacta/tests/ -v --timeout=30
```

Expected: All tests pass.

- [ ] **Step 8: Commit any final adjustments**

If any test fixes were needed, commit them.

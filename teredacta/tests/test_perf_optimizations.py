import json
import sqlite3

import pytest

from teredacta.config import TeredactaConfig
from teredacta.db_pool import ConnectionPool
from teredacta.entity_index import EntityIndex
from teredacta.unob import UnobInterface


@pytest.fixture
def populated_db(mock_db):
    """Insert sample data into the mock DB."""
    conn = sqlite3.connect(str(mock_db))
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
         "Email chain", "From: JE To: Ghislaine Maxwell Subject: the townhouse on 71st", 1, 1),
    )
    conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (1, 1)")
    conn.execute(
        "INSERT INTO match_group_members (group_id, doc_id, similarity) "
        "VALUES (1, 'doc-001', 0.92)"
    )
    conn.execute(
        "INSERT INTO match_group_members (group_id, doc_id, similarity) "
        "VALUES (1, 'doc-002', 0.88)"
    )
    segments = json.dumps([
        {"source_doc_id": "doc-002", "text": "Ghislaine Maxwell", "position": 5},
    ])
    conn.execute(
        "INSERT INTO merge_results (group_id, merged_text, recovered_count, "
        "total_redacted, source_doc_ids, recovered_segments, soft_recovered_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "Dear Ghislaine Maxwell, meeting...", 1, 2, json.dumps(["doc-001", "doc-002"]), segments, 0),
    )
    conn.commit()
    conn.close()
    return mock_db


# --- Task 1: mmap_size pragma ---

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


# --- Task 2: startup warm-up ---

class TestWarmUp:
    def test_warm_up_runs_without_error(self, test_config, populated_db):
        """warm_up should touch key tables without raising."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        unob.warm_up()

    def test_warm_up_with_missing_db(self, test_config):
        """warm_up should handle missing DB gracefully."""
        test_config.db_path = "/nonexistent/path.db"
        unob = UnobInterface(test_config)
        unob.warm_up()


# --- Task 3: entity_index status cache ---

class TestEntityIndexStatusCache:
    def test_get_status_is_cached(self, entity_index, mock_db):
        """Second call within TTL should return cached result without DB hit."""
        result1 = entity_index.get_status(unob_db_path=str(mock_db))
        result2 = entity_index.get_status(unob_db_path=str(mock_db))
        assert result1 == result2

    def test_get_status_cache_expires(self, entity_index, mock_db, monkeypatch):
        """After TTL expires, cache should refresh."""
        result1 = entity_index.get_status(unob_db_path=str(mock_db))
        original_time = entity_index._status_cache_time
        monkeypatch.setattr(entity_index, "_status_cache_time", original_time - 120)
        result2 = entity_index.get_status(unob_db_path=str(mock_db))
        assert result2 == result1


# --- Task 4: migration ---

class TestMigration:
    def test_migrate_adds_has_redactions_column(self, test_config, populated_db):
        """Migration should add has_redactions column and backfill it."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        unob.run_migration()

        conn = sqlite3.connect(str(populated_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, has_redactions FROM documents ORDER BY id").fetchall()
        doc1 = next(r for r in rows if r["id"] == "doc-001")
        assert doc1["has_redactions"] == 1
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


# --- Task 6: match_groups COUNT cache ---

class TestMatchGroupsCountCache:
    def test_match_groups_count_is_cached(self, test_config, populated_db):
        """Repeated calls should use cached count."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        groups1, total1 = unob.get_match_groups()
        groups2, total2 = unob.get_match_groups()
        assert total1 == total2 == 1
        assert hasattr(unob, "_match_groups_count_cache")
        assert unob._match_groups_count_cache == 1


# --- Task 5: optimized document queries ---

class TestOptimizedDocumentQueries:
    def test_has_redactions_uses_column(self, test_config, populated_db):
        """has_redactions filter should use the precomputed column."""
        conn = sqlite3.connect(str(populated_db))
        columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
        if "has_redactions" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN has_redactions INTEGER DEFAULT 0")
        conn.execute("UPDATE documents SET has_redactions = 1 WHERE id = 'doc-001'")
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
        unob = UnobInterface(test_config)
        unob.run_migration()

        docs, total = unob.get_documents(search="letter")
        assert total == 1
        assert docs[0]["id"] == "doc-001"

    def test_fts_zero_results_does_not_fallback(self, test_config, populated_db):
        """FTS returning zero results should return empty, not fall through to LIKE."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        unob.run_migration()

        # "doc-00" is a substring that FTS word-tokenization won't match
        docs, total = unob.get_documents(search="doc-00")
        assert total == 0

    def test_like_fallback_without_fts(self, test_config, populated_db):
        """Without FTS table, substring search falls back to LIKE."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        # No migration — no FTS table, so LIKE fallback handles substrings
        docs, total = unob.get_documents(search="doc-00")
        assert total == 2

    def test_search_without_fts_table(self, test_config, populated_db):
        """Search should still work via LIKE if FTS table doesn't exist."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        docs, total = unob.get_documents(search="letter")
        assert total == 1
        assert docs[0]["id"] == "doc-001"

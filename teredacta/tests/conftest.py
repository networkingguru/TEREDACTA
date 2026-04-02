import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from teredacta.config import TeredactaConfig
from teredacta.entity_index import EntityIndex


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
            pdf_processed BOOLEAN DEFAULT 0,
            text_source TEXT,
            ocr_processed BOOLEAN DEFAULT 0,
            page_tags TEXT,
            has_redactions INTEGER DEFAULT 0
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


# ---------------------------------------------------------------------------
# Entity index fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def entity_db_path(tmp_dir):
    """Path for the entity index database."""
    return str(tmp_dir / "teredacta_entities.db")


@pytest.fixture
def entity_index(mock_db, entity_db_path):
    """Build an entity index seeded with recovery data in mock_db."""
    conn = sqlite3.connect(str(mock_db))
    # Seed recovery data — use INSERT OR IGNORE to avoid conflicts with
    # existing mock data that other fixtures may have inserted.
    segments_1 = json.dumps([
        {"text": "Jeffrey Epstein traveled to Palm Beach with FBI escort."},
        {"text": "Contact: jeff@island.com or call 212-555-0100"},
    ])
    segments_2 = json.dumps([
        {"text": "Ghislaine Maxwell met with Goldman Sachs representatives in Manhattan."},
    ])
    segments_3 = json.dumps([
        {"text": "Jeffrey Epstein and Alan Dershowitz at Mar-a-Lago."},
    ])
    conn.execute("INSERT OR IGNORE INTO match_groups (group_id, merged) VALUES (100, 1)")
    conn.execute("INSERT OR IGNORE INTO match_groups (group_id, merged) VALUES (101, 1)")
    conn.execute("INSERT OR IGNORE INTO match_groups (group_id, merged) VALUES (102, 1)")
    conn.execute(
        "INSERT OR REPLACE INTO merge_results "
        "(group_id, recovered_segments, recovered_count, created_at) "
        "VALUES (100, ?, 2, '2020-01-01 00:00:00')",
        (segments_1,),
    )
    conn.execute(
        "INSERT OR REPLACE INTO merge_results "
        "(group_id, recovered_segments, recovered_count, created_at) "
        "VALUES (101, ?, 1, '2020-01-01 00:00:00')",
        (segments_2,),
    )
    conn.execute(
        "INSERT OR REPLACE INTO merge_results "
        "(group_id, recovered_segments, recovered_count, created_at) "
        "VALUES (102, ?, 1, '2020-01-01 00:00:00')",
        (segments_3,),
    )
    conn.commit()
    conn.close()

    idx = EntityIndex(entity_db_path)
    idx.build(str(mock_db))
    return idx


@pytest.fixture
def app_with_entities(test_config, entity_index, entity_db_path):
    """Create a FastAPI app with entity_index on app.state."""
    test_config.entity_db_path = entity_db_path
    from teredacta.app import create_app
    application = create_app(test_config)
    application.app.state.entity_index = entity_index
    return application


@pytest.fixture
def client_with_entities(app_with_entities):
    """TestClient with entity index available."""
    return TestClient(app_with_entities)


# ---------------------------------------------------------------------------
# Stress test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def stress_db(mock_db):
    """Reuse mock_db schema with optional seed data for stress tests."""
    return mock_db


@pytest.fixture
def stress_app(tmp_dir, stress_db):
    """App for stress tests using the shared mock_db schema."""
    cfg = TeredactaConfig(
        unobfuscator_path=str(tmp_dir),
        unobfuscator_bin="echo",
        db_path=str(stress_db),
        pdf_cache_dir=str(tmp_dir / "pdf_cache"),
        output_dir=str(tmp_dir / "output"),
        log_path=str(tmp_dir / "unobfuscator.log"),
        host="127.0.0.1",
        port=8000,
    )
    from teredacta.app import create_app
    return create_app(cfg)

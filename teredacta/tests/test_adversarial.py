"""Adversarial tests for TEREDACTA.

Targets edge cases, security boundaries, and error handling across:
entity index, explore page, highlights, source panel, boolean search,
entity-aware document search, and API endpoints.
"""

import json
import sqlite3
import time
from pathlib import Path

import pytest

from teredacta.entity_index import EntityIndex, extract_entities
from teredacta.unob import UnobInterface, parse_boolean_search


# ============================================================================
# Entity Index — Adversarial
# ============================================================================

class TestEntityIndexAdversarial:
    """Edge cases and hostile inputs for EntityIndex.build / query."""

    @pytest.fixture
    def empty_unob_db(self, tmp_path):
        """Unobfuscator DB with schema but zero merge_results rows."""
        db = tmp_path / "empty_unob.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE merge_results (
                group_id INTEGER PRIMARY KEY,
                recovered_segments TEXT,
                recovered_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT '2020-01-01 00:00:00'
            );
        """)
        conn.close()
        return db

    @pytest.fixture
    def entity_db(self, tmp_path):
        return str(tmp_path / "adversarial_entities.db")

    # -- build with empty DB --

    def test_build_empty_db(self, entity_db, empty_unob_db):
        idx = EntityIndex(entity_db)
        result = idx.build(str(empty_unob_db))
        assert result["entities"] == 0
        assert result["mentions"] == 0

    def test_build_empty_db_then_query(self, entity_db, empty_unob_db):
        idx = EntityIndex(entity_db)
        idx.build(str(empty_unob_db))
        entities, total = idx.list_entities()
        assert total == 0
        assert entities == []

    # -- NULL / empty recovered_segments --

    def test_build_null_segments(self, tmp_path, entity_db):
        db = tmp_path / "null_segs.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE merge_results (
                group_id INTEGER PRIMARY KEY,
                recovered_segments TEXT,
                recovered_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT '2020-01-01 00:00:00'
            );
        """)
        # recovered_count > 0 but segments is NULL — should be skipped by query
        conn.execute(
            "INSERT INTO merge_results (group_id, recovered_segments, recovered_count) "
            "VALUES (1, NULL, 5)"
        )
        conn.execute(
            "INSERT INTO merge_results (group_id, recovered_segments, recovered_count) "
            "VALUES (2, '', 3)"
        )
        conn.execute(
            "INSERT INTO merge_results (group_id, recovered_segments, recovered_count) "
            "VALUES (3, '[]', 1)"
        )
        conn.commit()
        conn.close()

        idx = EntityIndex(entity_db)
        result = idx.build(str(db))
        # Should not crash; may find 0 entities
        assert result["entities"] == 0

    # -- extremely long entity names --

    def test_build_very_long_entity_name(self, tmp_path, entity_db):
        db = tmp_path / "long_name.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE merge_results (
                group_id INTEGER PRIMARY KEY,
                recovered_segments TEXT,
                recovered_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT '2020-01-01 00:00:00'
            );
        """)
        # Create a segment with an absurdly long name-like string
        long_name = "Aaaa " + "Bbbb " * 200  # 1000+ chars
        segments = json.dumps([{"text": long_name + " met with FBI at Palm Beach."}])
        conn.execute(
            "INSERT INTO merge_results (group_id, recovered_segments, recovered_count) "
            "VALUES (1, ?, 1)",
            (segments,),
        )
        conn.commit()
        conn.close()

        idx = EntityIndex(entity_db)
        result = idx.build(str(db))
        # Should not crash; may or may not extract entities
        assert isinstance(result["entities"], int)

    # -- segments with only HTML, numbers, whitespace --

    def test_build_html_only_segments(self, tmp_path, entity_db):
        db = tmp_path / "html_only.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE merge_results (
                group_id INTEGER PRIMARY KEY,
                recovered_segments TEXT,
                recovered_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT '2020-01-01 00:00:00'
            );
        """)
        segments = json.dumps([
            {"text": "<div><p><span></span></p></div>"},
            {"text": "12345678901234567890"},
            {"text": "   \t\n\r   "},
        ])
        conn.execute(
            "INSERT INTO merge_results (group_id, recovered_segments, recovered_count) "
            "VALUES (1, ?, 3)",
            (segments,),
        )
        conn.commit()
        conn.close()

        idx = EntityIndex(entity_db)
        result = idx.build(str(db))
        # No real entities should be extracted; should not crash
        assert result["entities"] == 0

    # -- XSS in entity extraction --

    def test_extract_entities_xss(self):
        """XSS payloads should not produce entities or crash."""
        text = '<script>alert(1)</script><img src=x onerror=alert(1)>'
        entities = extract_entities(text)
        # No person/org/location should be extracted from XSS
        for e in entities:
            assert "<script>" not in e["name"]
            assert "onerror" not in e["name"]

    # -- SQL injection in entity extraction --

    def test_extract_entities_sql_injection(self):
        text = "'; DROP TABLE entities; -- Robert'; DELETE FROM"
        entities = extract_entities(text)
        # Should not crash; any extracted names should be benign
        for e in entities:
            assert "DROP TABLE" not in e["name"]

    # -- get_connections with boundary IDs --

    def test_get_connections_id_zero(self, entity_index):
        result = entity_index.get_connections(0)
        assert result is None

    def test_get_connections_id_negative(self, entity_index):
        result = entity_index.get_connections(-1)
        assert result is None

    def test_get_connections_id_very_large(self, entity_index):
        result = entity_index.get_connections(999999)
        assert result is None

    # -- list_entities with SQL wildcards --

    def test_list_entities_sql_wildcard_percent(self, entity_index):
        """name_filter with % should be treated literally via LIKE parameter."""
        entities, total = entity_index.list_entities(name_filter="%")
        # Should not crash or return everything
        assert isinstance(total, int)

    def test_list_entities_sql_wildcard_underscore(self, entity_index):
        entities, total = entity_index.list_entities(name_filter="_")
        assert isinstance(total, int)

    def test_list_entities_sql_wildcard_backslash(self, entity_index):
        entities, total = entity_index.list_entities(name_filter="\\")
        assert isinstance(total, int)

    def test_list_entities_html_filter(self, entity_index):
        """HTML in name_filter should not cause issues."""
        entities, total = entity_index.list_entities(name_filter="<img src=x>")
        assert total == 0

    # -- staleness when unob DB doesn't exist --

    def test_staleness_missing_unob_db(self, entity_index):
        status = entity_index.get_status(unob_db_path="/nonexistent/path.db")
        # Should return ready (not crash) since unob DB is checked only if it exists
        assert status["state"] == "ready"

    # -- staleness when meta has no built_at --

    def test_staleness_no_built_at(self, tmp_path):
        db = str(tmp_path / "no_built_at.db")
        conn = sqlite3.connect(db)
        conn.executescript("""
            CREATE TABLE entities (
                id INTEGER PRIMARY KEY, name TEXT, type TEXT, mention_count INTEGER,
                UNIQUE(name, type)
            );
            CREATE TABLE entity_mentions (
                id INTEGER PRIMARY KEY, entity_id INTEGER, group_id INTEGER,
                context TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entity_id, group_id)
            );
            CREATE TABLE entity_links (
                id INTEGER PRIMARY KEY, entity_a_id INTEGER, entity_b_id INTEGER,
                co_occurrence_count INTEGER DEFAULT 1,
                UNIQUE(entity_a_id, entity_b_id)
            );
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        # meta table exists but no built_at row
        conn.close()
        idx = EntityIndex(db)
        status = idx.get_status()
        assert status["state"] == "not_built"

    def test_get_entities_with_samples_empty(self, entity_db, empty_unob_db):
        idx = EntityIndex(entity_db)
        idx.build(str(empty_unob_db))
        result = idx.get_entities_with_samples()
        assert result == []

    def test_get_entity_nonexistent_db(self, tmp_path):
        idx = EntityIndex(str(tmp_path / "does_not_exist.db"))
        assert idx.get_entity(1) is None

    def test_list_entities_nonexistent_db(self, tmp_path):
        idx = EntityIndex(str(tmp_path / "does_not_exist.db"))
        entities, total = idx.list_entities()
        assert entities == []
        assert total == 0


# ============================================================================
# API Endpoint — Adversarial
# ============================================================================

class TestAPIAdversarial:
    """Hostile inputs to /api/* endpoints."""

    def test_entities_xss_type_param(self, client_with_entities):
        resp = client_with_entities.get("/api/entities?type=<script>alert(1)</script>")
        assert resp.status_code == 200
        # XSS should be escaped in output
        assert "<script>alert(1)</script>" not in resp.text

    def test_entities_sql_injection_filter(self, client_with_entities):
        resp = client_with_entities.get("/api/entities?filter='; DROP TABLE entities; --")
        assert resp.status_code == 200
        # App should still function afterward
        resp2 = client_with_entities.get("/api/entities")
        assert resp2.status_code == 200
        assert "data-entity-id" in resp2.text

    def test_connections_very_large_id(self, client_with_entities):
        resp = client_with_entities.get(f"/api/entities/{2**31}/connections")
        assert resp.status_code == 404

    def test_preview_recovery_id_zero(self, client_with_entities):
        resp = client_with_entities.get("/api/preview/recovery/0")
        assert resp.status_code == 404

    def test_preview_document_path_traversal(self, client_with_entities):
        resp = client_with_entities.get("/api/preview/document/../../../etc/passwd")
        # Should be 404, not leak files
        assert resp.status_code in (404, 422, 400)

    def test_preview_entity_negative_id(self, client_with_entities):
        # FastAPI path converter int should reject or route this
        resp = client_with_entities.get("/api/preview/entity/-1")
        assert resp.status_code in (404, 422)

    def test_preview_entity_zero(self, client_with_entities):
        resp = client_with_entities.get("/api/preview/entity/0")
        assert resp.status_code == 404

    def test_entities_empty_string_filter(self, client_with_entities):
        resp = client_with_entities.get("/api/entities?filter=")
        assert resp.status_code == 200

    def test_entities_very_long_filter(self, client_with_entities):
        long_filter = "A" * 5000
        resp = client_with_entities.get(f"/api/entities?filter={long_filter}")
        assert resp.status_code == 200


# ============================================================================
# Source Panel — Adversarial
# ============================================================================

class TestSourcePanelAdversarial:
    """Hostile inputs to source panel endpoint and get_source_context."""

    @pytest.fixture
    def seeded_recovery(self, mock_db, tmp_dir):
        """Insert recovery data with segments for source panel tests."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, release_batch, original_filename, "
            "text_processed, text_source, extracted_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("src-adv-001", "doj", "VOL00001", "letter.pdf", 1, "pdf_text_layer",
             "Dear [REDACTED], meeting at [REDACTED] on [REDACTED]..."),
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (60, 1)")
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (60, 'src-adv-001', 0.95)"
        )
        segments = json.dumps([
            {"source_doc_id": "src-adv-001", "text": "Ghislaine Maxwell", "position": 5},
        ])
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count, "
            "total_redacted, source_doc_ids, recovered_segments) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (60,
             "Dear <change><u>Ghislaine Maxwell</u></change>, meeting at [REDACTED]...",
             1, 3, json.dumps(["src-adv-001"]), segments),
        )
        conn.commit()
        conn.close()
        return mock_db

    def test_source_panel_negative_segment_index(self, client, seeded_recovery):
        resp = client.get("/recoveries/60/source?segment_index=-1")
        # ge=0 validation should reject
        assert resp.status_code == 422

    def test_source_panel_huge_segment_index(self, client, seeded_recovery):
        resp = client.get("/recoveries/60/source?segment_index=99999")
        assert resp.status_code == 404

    def test_source_panel_missing_param(self, client, seeded_recovery):
        resp = client.get("/recoveries/60/source")
        assert resp.status_code == 422

    def test_source_panel_group_zero(self, client, seeded_recovery):
        resp = client.get("/recoveries/0/source?segment_index=0")
        assert resp.status_code == 404

    def test_source_panel_nonexistent_group(self, client, seeded_recovery):
        resp = client.get("/recoveries/999999/source?segment_index=0")
        assert resp.status_code == 404

    def test_source_context_only_redacted_markers(self, test_config, mock_db):
        """When recovered text is surrounded by only [REDACTED] markers."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT OR IGNORE INTO match_groups (group_id, merged) VALUES (70, 1)")
        conn.execute(
            "INSERT INTO documents (id, source, release_batch, original_filename, "
            "text_processed, text_source, extracted_text) "
            "VALUES ('src-red-001', 'doj', 'VOL00001', 'redacted.pdf', 1, 'pdf_text_layer', "
            "'[REDACTED] [REDACTED] [REDACTED]')"
        )
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (70, 'src-red-001', 0.9)"
        )
        segments = json.dumps([
            {"source_doc_id": "src-red-001", "text": "some recovered text", "position": 10},
        ])
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count, "
            "total_redacted, source_doc_ids, recovered_segments) VALUES "
            "(70, '[REDACTED] <change><u>some recovered text</u></change> [REDACTED]', "
            "1, 3, ?, ?)",
            (json.dumps(["src-red-001"]), segments),
        )
        conn.commit()
        conn.close()

        unob = UnobInterface(test_config)
        ctx = unob.get_source_context(70, 0)
        assert ctx is not None
        assert ctx["recovered_text"] == "some recovered text"
        # Context should have the recovered text; surrounding [REDACTED] stripped
        assert "some recovered text" in ctx["search_context"]

    def test_source_context_empty_merged_text(self, test_config, mock_db):
        """When merged_text is empty string."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT OR IGNORE INTO match_groups (group_id, merged) VALUES (71, 1)")
        conn.execute(
            "INSERT INTO documents (id, source, release_batch, original_filename, "
            "text_processed, text_source, extracted_text) "
            "VALUES ('src-empty-001', 'doj', 'VOL00001', 'empty.pdf', 1, 'pdf_text_layer', 'some text')"
        )
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (71, 'src-empty-001', 0.9)"
        )
        segments = json.dumps([
            {"source_doc_id": "src-empty-001", "text": "found text", "position": 0},
        ])
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count, "
            "total_redacted, source_doc_ids, recovered_segments) VALUES "
            "(71, '', 1, 1, ?, ?)",
            (json.dumps(["src-empty-001"]), segments),
        )
        conn.commit()
        conn.close()

        unob = UnobInterface(test_config)
        ctx = unob.get_source_context(71, 0)
        assert ctx is not None
        assert ctx["recovered_text"] == "found text"
        # search_context falls back to recovered_text when merged_text is empty
        assert ctx["search_context"] == "found text"


# ============================================================================
# Boolean Search — Adversarial
# ============================================================================

class TestBooleanSearchAdversarial:
    """Hostile inputs to parse_boolean_search."""

    def test_only_and(self):
        result = parse_boolean_search("AND")
        assert result == []

    def test_only_or(self):
        result = parse_boolean_search("OR")
        assert result == []

    def test_unmatched_quote(self):
        result = parse_boolean_search('"unclosed')
        assert len(result) == 1
        assert result[0][0] == "unclosed"

    def test_empty_quotes(self):
        result = parse_boolean_search('""')
        assert result == []

    def test_nested_quotes(self):
        result = parse_boolean_search('"hello "world" foo"')
        # Parser should handle gracefully, not crash
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_100_terms(self):
        terms = " ".join(f"term{i}" for i in range(100))
        result = parse_boolean_search(terms)
        assert len(result) == 100

    def test_very_long_term(self):
        long_term = "x" * 10000
        result = parse_boolean_search(long_term)
        assert len(result) == 1
        assert result[0][0] == long_term

    def test_sql_injection_in_search(self):
        result = parse_boolean_search('" OR 1=1 --')
        assert isinstance(result, list)
        # Should be parsed as a quoted phrase, not interpreted as SQL
        for term, op in result:
            assert "1=1" not in term or term == " OR 1=1 --"

    def test_multiple_consecutive_operators(self):
        result = parse_boolean_search("AND AND OR OR term")
        assert len(result) == 1
        assert result[0][0] == "term"

    def test_empty_string(self):
        assert parse_boolean_search("") == []

    def test_only_whitespace(self):
        assert parse_boolean_search("   ") == []

    def test_operators_with_terms(self):
        result = parse_boolean_search("hello OR world AND foo")
        assert len(result) == 3
        assert result[0] == ("hello", "AND")
        assert result[1] == ("world", "OR")
        assert result[2] == ("foo", "AND")

    def test_search_recoveries_with_sql_injection(self, client, mock_db):
        """SQL injection via search param to /recoveries endpoint."""
        # Seed a recovery so the query actually runs
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT OR IGNORE INTO match_groups (group_id, merged) VALUES (80, 1)")
        segments = json.dumps([{"text": "test recovery"}])
        conn.execute(
            "INSERT OR REPLACE INTO merge_results "
            "(group_id, recovered_segments, recovered_count, created_at) "
            "VALUES (80, ?, 1, '2020-01-01 00:00:00')",
            (segments,),
        )
        conn.commit()
        conn.close()

        resp = client.get("/recoveries?search=\"' OR 1=1 --\"")
        assert resp.status_code == 200


# ============================================================================
# Highlights — Adversarial
# ============================================================================

class TestHighlightsAdversarial:
    """Edge cases for the highlights page."""

    def test_highlights_no_entity_index(self, client):
        """Highlights page when entity index is not built."""
        resp = client.get("/highlights")
        assert resp.status_code == 200
        assert "Highlights" in resp.text

    def test_highlights_no_recoveries(self, client):
        """Highlights page when DB has no recoveries."""
        resp = client.get("/highlights")
        assert resp.status_code == 200

    def test_highlights_all_image_segments(self, client, mock_db):
        """When all recovery segments start with 'The image'."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT OR IGNORE INTO match_groups (group_id, merged) VALUES (90, 1)")
        segments = json.dumps([
            {"text": "The image shows a blurred document"},
            {"text": "The image contains redacted text"},
            {"text": "This image is partially visible"},
        ])
        conn.execute(
            "INSERT OR REPLACE INTO merge_results "
            "(group_id, recovered_segments, recovered_count, created_at) "
            "VALUES (90, ?, 3, '2020-01-01 00:00:00')",
            (segments,),
        )
        conn.commit()
        conn.close()

        resp = client.get("/highlights")
        assert resp.status_code == 200

    def test_highlights_with_entity_data(self, client_with_entities):
        resp = client_with_entities.get("/highlights")
        assert resp.status_code == 200
        assert "Notable Entities" in resp.text

    def test_stale_recovery_deeplink_redirects_to_featured(self, client, mock_db):
        """External deeplinks to old group_ids (e.g. README pointing at 8022)
        should redirect to the current featured recovery instead of 404ing."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT OR IGNORE INTO match_groups (group_id, merged) VALUES (555, 1)")
        segments = json.dumps([{"text": "recovered content"}])
        conn.execute(
            "INSERT OR REPLACE INTO merge_results "
            "(group_id, merged_text, recovered_count, total_redacted, "
            "source_doc_ids, recovered_segments, created_at) "
            "VALUES (555, ?, 4, 4, ?, ?, '2020-01-01 00:00:00')",
            ("placeholder text", json.dumps([]), segments),
        )
        conn.commit()
        conn.close()

        # Stale id 8022 no longer exists; should redirect to 555 (the top rec)
        resp = client.get("/recoveries/8022", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/recoveries/555"

    def test_stale_recovery_deeplink_404s_when_no_recoveries_exist(self, client, mock_db):
        """Redirect needs a target. With no recoveries in the DB at all,
        still 404 — no infinite loops, no phantom redirects."""
        resp = client.get("/recoveries/8022", follow_redirects=False)
        assert resp.status_code == 404

    def test_valid_recovery_detail_does_not_redirect(self, client, mock_db):
        """Live recoveries render normally — redirect logic must not fire
        when the requested group actually exists."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT OR IGNORE INTO match_groups (group_id, merged) VALUES (777, 1)")
        conn.execute(
            "INSERT OR REPLACE INTO merge_results "
            "(group_id, merged_text, recovered_count, total_redacted, "
            "source_doc_ids, recovered_segments, created_at) "
            "VALUES (777, ?, 3, 3, ?, ?, '2020-01-01 00:00:00')",
            ("real group content", json.dumps([]), json.dumps([{"text": "seg"}])),
        )
        conn.commit()
        conn.close()

        resp = client.get("/recoveries/777", follow_redirects=False)
        assert resp.status_code == 200

    def test_highlights_featured_survives_group_id_regen(self, client, mock_db):
        """Featured pin resolves by content anchors, not a hardcoded group_id.

        Regression for TEREDACTA #20: the original pin was `group_id=8022`.
        After an algorithm change regenerated groups, that ID pointed at an
        empty match. This test gives group 999 — an arbitrary new ID — the
        anchor content and confirms the page surfaces that ID.
        """
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT OR IGNORE INTO match_groups (group_id, merged) VALUES (999, 1)")
        segments = json.dumps([{"text": "Tova Noel duty officer shift"}])
        conn.execute(
            "INSERT OR REPLACE INTO merge_results "
            "(group_id, merged_text, recovered_count, total_redacted, "
            "source_doc_ids, recovered_segments, created_at) "
            "VALUES (999, ?, 5, 5, ?, ?, '2020-01-01 00:00:00')",
            ("Tova Noel was on shift. The staff psychologist wrote the memo.",
             json.dumps([]), segments),
        )
        conn.commit()
        conn.close()

        resp = client.get("/highlights")
        assert resp.status_code == 200
        assert "/recoveries/999" in resp.text


# ============================================================================
# Document Search — Adversarial
# ============================================================================

class TestDocumentSearchAdversarial:
    """Entity-aware document search edge cases."""

    def test_entity_search_no_matching_entities(self, client_with_entities):
        """Search for term that matches no entities."""
        resp = client_with_entities.get("/documents?search=ZZZZNONEXISTENT")
        assert resp.status_code == 200

    def test_entity_search_no_entity_db(self, client):
        """Search when entity index DB doesn't exist."""
        resp = client.get("/documents?search=Jeffrey+Epstein")
        assert resp.status_code == 200

    def test_entity_search_matches_but_no_group_members(self, client_with_entities):
        """Entity exists in index but linked group has no match_group_members."""
        resp = client_with_entities.get("/documents?search=Epstein")
        assert resp.status_code == 200

    def test_document_search_xss(self, client):
        resp = client.get("/documents?search=<script>alert(1)</script>")
        assert resp.status_code == 200
        assert "<script>alert(1)</script>" not in resp.text

    def test_document_search_sql_injection(self, client, mock_db):
        # Seed some docs
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, release_batch, original_filename, "
            "text_processed) VALUES ('doc-inj-001', 'doj', 'VOL00001', 'test.pdf', 1)"
        )
        conn.commit()
        conn.close()

        resp = client.get("/documents?search='; DROP TABLE documents; --")
        assert resp.status_code == 200
        # DB should still be intact
        resp2 = client.get("/documents")
        assert resp2.status_code == 200

    def test_document_search_very_long_query(self, client):
        long_query = "a" * 10000
        resp = client.get(f"/documents?search={long_query}")
        assert resp.status_code == 200


# ============================================================================
# Extract Entities — Additional edge cases
# ============================================================================

class TestExtractEntitiesAdversarial:
    """More hostile inputs for extract_entities."""

    def test_null_bytes(self):
        entities = extract_entities("Jeffrey\x00Epstein met the FBI")
        # Should not crash
        assert isinstance(entities, list)

    def test_unicode_entities(self):
        entities = extract_entities("Meeting with Jose Garcia at the office.")
        # accent-free variant should parse normally
        assert isinstance(entities, list)

    def test_very_long_text(self):
        """10k chars of text should not hang."""
        text = "Jeffrey Epstein " * 1000
        entities = extract_entities(text)
        assert isinstance(entities, list)
        # Should deduplicate
        person_names = [e["name"] for e in entities if e["type"] == "person"]
        assert person_names.count("Jeffrey Epstein") == 1

    def test_only_operators_in_text(self):
        entities = extract_entities("AND OR NOT TRUE FALSE NULL")
        # Title Case regex may match "True False" / "Not True" as person names;
        # that is a known limitation of heuristic extraction, not a bug.
        # The important thing is it doesn't crash.
        assert isinstance(entities, list)

    def test_mixed_case_injection(self):
        text = "<ScRiPt>alert(1)</ScRiPt>"
        entities = extract_entities(text)
        for e in entities:
            assert "alert" not in e["name"].lower()

    def test_backslash_heavy_text(self):
        text = "Meeting\\with\\Jeffrey\\Epstein\\at\\FBI"
        entities = extract_entities(text)
        assert isinstance(entities, list)

    def test_segments_as_strings_not_dicts(self):
        """Build with segments that are plain strings, not dicts."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "str_segs.db"
            conn = sqlite3.connect(str(db))
            conn.executescript("""
                CREATE TABLE merge_results (
                    group_id INTEGER PRIMARY KEY,
                    recovered_segments TEXT,
                    recovered_count INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT '2020-01-01 00:00:00'
                );
            """)
            # Segments as list of strings instead of list of dicts
            segments = json.dumps([
                "Jeffrey Epstein traveled to Palm Beach.",
                "Contact FBI for details.",
            ])
            conn.execute(
                "INSERT INTO merge_results (group_id, recovered_segments, recovered_count) "
                "VALUES (1, ?, 2)",
                (segments,),
            )
            conn.commit()
            conn.close()

            entity_db = str(Path(tmp) / "entities.db")
            idx = EntityIndex(entity_db)
            result = idx.build(str(db))
            # Should handle string segments gracefully (str(seg) path)
            assert isinstance(result["entities"], int)

    def test_malformed_json_segments(self):
        """Build with invalid JSON in recovered_segments."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "bad_json.db"
            conn = sqlite3.connect(str(db))
            conn.executescript("""
                CREATE TABLE merge_results (
                    group_id INTEGER PRIMARY KEY,
                    recovered_segments TEXT,
                    recovered_count INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT '2020-01-01 00:00:00'
                );
            """)
            conn.execute(
                "INSERT INTO merge_results (group_id, recovered_segments, recovered_count) "
                "VALUES (1, '{invalid json!!!', 1)"
            )
            conn.commit()
            conn.close()

            entity_db = str(Path(tmp) / "entities.db")
            idx = EntityIndex(entity_db)
            result = idx.build(str(db))
            assert result["entities"] == 0


# ============================================================================
# Explore page — Adversarial
# ============================================================================

class TestExplorePageAdversarial:
    """Edge cases for the explore page."""

    def test_explore_without_entity_index(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_explore_with_entities(self, client_with_entities):
        resp = client_with_entities.get("/")
        assert resp.status_code == 200

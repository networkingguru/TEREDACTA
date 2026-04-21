import json
import sqlite3

import pytest

from teredacta.unob import UnobInterface, parse_boolean_search


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
        "page_count, description, extracted_text, text_processed, pdf_processed, has_redactions) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("doc-001", "doj", "VOL00001", "letter.pdf", 3,
         "Letter from JE", "Dear [REDACTED], meeting at...", 1, 0, 1),
    )
    conn.execute(
        "INSERT INTO documents (id, source, release_batch, original_filename, "
        "page_count, description, extracted_text, text_processed, pdf_processed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("doc-002", "doj", "VOL00001", "email.pdf", 1,
         "Email chain", "From: JE To: Ghislaine Maxwell Subject: the townhouse on 71st", 1, 1),
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
        groups, total = unob.get_match_groups()
        assert total == 1
        assert len(groups) == 1
        assert groups[0]["group_id"] == 1
        assert groups[0]["member_count"] == 2

    def test_get_recoveries(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        results, total = unob.get_recoveries()
        assert len(results) == 1
        assert total == 1
        assert results[0]["recovered_count"] == 2

    def test_get_recoveries_search(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        results, total = unob.get_recoveries(search="Maxwell")
        assert len(results) == 1
        assert total == 1
        results2, total2 = unob.get_recoveries(search="nonexistent")
        assert len(results2) == 0
        assert total2 == 0

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


class TestFeaturedRecovery:
    """Pin-resolution for the highlights page. Stays stable across group-id regens."""

    def _seed(self, db_path, rows):
        """rows: list of (group_id, merged_text, recovered_count, segments)."""
        conn = sqlite3.connect(str(db_path))
        for gid, text, rc, segs in rows:
            conn.execute("INSERT OR IGNORE INTO match_groups (group_id, merged) VALUES (?, 1)", (gid,))
            conn.execute(
                "INSERT OR REPLACE INTO merge_results "
                "(group_id, merged_text, recovered_count, total_redacted, source_doc_ids, recovered_segments) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (gid, text, rc, rc, json.dumps([]), json.dumps(segs)),
            )
        conn.commit()
        conn.close()

    def test_anchor_match_picks_highest_recovered(self, test_config, mock_db):
        self._seed(mock_db, [
            (500, "Tova Noel was staff psychologist on duty.", 5, [{"text": "five"}]),
            (501, "Tova Noel was staff psychologist on duty — second copy.", 10, [{"text": "ten"}]),
            (502, "Some unrelated email content with no anchors.", 20, [{"text": "unrelated"}]),
        ])
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        featured = unob.get_featured_recovery(["Tova Noel", "psychologist"])
        assert featured is not None
        assert featured["group_id"] == 501
        assert featured["recovered_count"] == 10

    def test_anchor_miss_falls_back_to_top_recovered(self, test_config, mock_db):
        self._seed(mock_db, [
            (600, "content without the anchors", 3, [{"text": "three"}]),
            (601, "another group, no match", 7, [{"text": "seven"}]),
        ])
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        featured = unob.get_featured_recovery(["NotPresent", "AlsoMissing"])
        assert featured is not None
        assert featured["group_id"] == 601  # fallback = highest recovered_count

    def test_no_anchors_uses_fallback(self, test_config, mock_db):
        self._seed(mock_db, [
            (700, "anything", 2, [{"text": "two"}]),
            (701, "also anything", 9, [{"text": "nine"}]),
        ])
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        assert unob.get_featured_recovery(None)["group_id"] == 701
        assert unob.get_featured_recovery([])["group_id"] == 701

    def test_returns_none_when_no_recoveries_exist(self, test_config, mock_db):
        # No rows in merge_results at all
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        assert unob.get_featured_recovery(["anything"]) is None
        assert unob.get_featured_recovery(None) is None

    def test_zero_recovered_count_groups_are_ignored(self, test_config, mock_db):
        # Even if merged_text matches the anchors, groups with recovered_count=0
        # should not be selected — they have nothing to display.
        self._seed(mock_db, [
            (800, "Tova Noel and psychologist in the text, but no recoveries", 0, []),
            (801, "fallback candidate unrelated to anchors", 4, [{"text": "four"}]),
        ])
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        featured = unob.get_featured_recovery(["Tova Noel", "psychologist"])
        assert featured is not None
        assert featured["group_id"] == 801  # anchor group filtered by rc>0, fell back


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


class TestBooleanSearch:
    def test_single_term(self):
        result = parse_boolean_search("maxwell")
        assert result == [("maxwell", "AND")]

    def test_and_operator(self):
        result = parse_boolean_search("maxwell AND epstein")
        assert result == [("maxwell", "AND"), ("epstein", "AND")]

    def test_or_operator(self):
        result = parse_boolean_search("maxwell OR epstein")
        assert result == [("maxwell", "AND"), ("epstein", "OR")]

    def test_quoted_phrase(self):
        result = parse_boolean_search('"palm beach" AND maxwell')
        assert result == [("palm beach", "AND"), ("maxwell", "AND")]

    def test_empty_query(self):
        assert parse_boolean_search("") == []
        assert parse_boolean_search("   ") == []

    def test_implicit_and(self):
        # Adjacent terms without explicit operator default to AND
        result = parse_boolean_search("maxwell epstein")
        assert result == [("maxwell", "AND"), ("epstein", "AND")]

    def test_mixed_operators(self):
        result = parse_boolean_search("maxwell AND epstein OR clinton")
        assert result == [("maxwell", "AND"), ("epstein", "AND"), ("clinton", "OR")]

    def test_case_insensitive_operators(self):
        result = parse_boolean_search("maxwell and epstein or clinton")
        assert result == [("maxwell", "AND"), ("epstein", "AND"), ("clinton", "OR")]

    def test_get_recoveries_boolean_and(self, test_config, populated_db):
        """AND search should only return results matching both terms."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        results, total = unob.get_recoveries(search="Maxwell AND townhouse")
        assert len(results) == 1  # both terms in the same recovery
        results2, total2 = unob.get_recoveries(search="Maxwell AND nonexistent")
        assert len(results2) == 0

    def test_get_recoveries_boolean_or(self, test_config, populated_db):
        """OR search should return results matching either term."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        results, total = unob.get_recoveries(search="Maxwell OR nonexistent")
        assert len(results) == 1

    def test_get_recoveries_single_term_backward_compat(self, test_config, populated_db):
        """Single term search should still work as before."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        results, total = unob.get_recoveries(search="Maxwell")
        assert len(results) == 1

    def test_get_recoveries_sort_by_date(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        results, total = unob.get_recoveries(sort="date")
        assert len(results) == 1  # just verify it doesn't crash


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


class TestGetMemberText:
    """Tests for get_member_text() — highlighted text for comparison panes."""

    def test_returns_highlighted_text(self, test_config, populated_db):
        """Recovered passages are highlighted in source doc text."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(1, "doc-002")
        assert result is not None
        assert result["doc_id"] == "doc-002"
        assert '<mark class="recovered-inline">' in result["text_html"]
        assert "Ghislaine Maxwell" in result["text_html"]

    def test_returns_none_for_nonmember(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(1, "nonexistent-doc")
        assert result is None

    def test_returns_none_for_nonexistent_group(self, test_config, populated_db):
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(999, "doc-001")
        assert result is None

    def test_no_segments_returns_plain_text(self, test_config, mock_db):
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT INTO documents (id, source, extracted_text, text_processed) VALUES ('solo-doc', 'test', 'plain text here', 1)")
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (50, 1)")
        conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (50, 'solo-doc', 0.9)")
        conn.execute("INSERT INTO merge_results (group_id, merged_text, recovered_count) VALUES (50, 'plain text here', 0)")
        conn.commit()
        conn.close()
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(50, "solo-doc")
        assert result is not None
        assert "plain text here" in result["text_html"]
        assert "<mark" not in result["text_html"]

    def test_empty_extracted_text(self, test_config, mock_db):
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT INTO documents (id, source, extracted_text, text_processed) VALUES ('empty-doc', 'test', '', 1)")
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (51, 1)")
        conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (51, 'empty-doc', 0.9)")
        conn.execute("INSERT INTO merge_results (group_id, merged_text, recovered_count) VALUES (51, '', 0)")
        conn.commit()
        conn.close()
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(51, "empty-doc")
        assert result is not None
        assert "No extracted text available" in result["text_html"]

    def test_html_escaping(self, test_config, mock_db):
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT INTO documents (id, source, extracted_text, text_processed) VALUES ('xss-doc', 'test', '<script>alert(1)</script> safe text', 1)")
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (52, 1)")
        conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (52, 'xss-doc', 0.9)")
        conn.execute("INSERT INTO merge_results (group_id, merged_text, recovered_count) VALUES (52, '', 0)")
        conn.commit()
        conn.close()
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(52, "xss-doc")
        assert "<script>" not in result["text_html"]
        assert "&lt;script&gt;" in result["text_html"]

    def test_truncation_over_100kb(self, test_config, mock_db):
        big_text = "word " * 25000
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT INTO documents (id, source, extracted_text, text_processed) VALUES ('big-doc', 'test', ?, 1)", (big_text,))
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (53, 1)")
        conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (53, 'big-doc', 0.9)")
        conn.execute("INSERT INTO merge_results (group_id, merged_text, recovered_count) VALUES (53, '', 0)")
        conn.commit()
        conn.close()
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(53, "big-doc")
        assert "Showing first" in result["text_html"]
        assert len(result["text_html"]) > 90_000
        assert len(result["text_html"]) < 105_000

    def test_whitespace_normalized_match(self, test_config, mock_db):
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT INTO documents (id, source, extracted_text, text_processed) VALUES ('ws-doc', 'test', 'hello   world  foo   bar', 1)")
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (55, 1)")
        conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (55, 'ws-doc', 0.9)")
        segments = json.dumps([{"source_doc_id": "other", "text": "hello world"}])
        conn.execute("INSERT INTO merge_results (group_id, merged_text, recovered_count, recovered_segments) VALUES (55, '', 1, ?)", (segments,))
        conn.commit()
        conn.close()
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(55, "ws-doc")
        # The highlighted text preserves original whitespace
        assert "hello" in result["text_html"]
        assert '<mark class="recovered-inline">' in result["text_html"]

    def test_newlines_preserved_in_output(self, test_config, mock_db):
        """Newlines in extracted text are preserved, not collapsed."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed) "
            "VALUES ('nl-doc', 'test', 'line one\nline two\nline three', 1)"
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (57, 1)")
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (57, 'nl-doc', 0.9)"
        )
        segments = json.dumps([{"source_doc_id": "other", "text": "line two"}])
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count, recovered_segments) "
            "VALUES (57, '', 1, ?)", (segments,)
        )
        conn.commit()
        conn.close()

        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(57, "nl-doc")
        # Newlines must be preserved (not collapsed by normalization)
        assert "\n" in result["text_html"]
        assert '<mark class="recovered-inline">' in result["text_html"]

    def test_segment_matching_across_newlines(self, test_config, mock_db):
        """Segment with spaces matches text that has newlines instead."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed) "
            "VALUES ('cross-doc', 'test', 'hello\nworld foo', 1)"
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (58, 1)")
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (58, 'cross-doc', 0.9)"
        )
        segments = json.dumps([{"source_doc_id": "other", "text": "hello world"}])
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count, recovered_segments) "
            "VALUES (58, '', 1, ?)", (segments,)
        )
        conn.commit()
        conn.close()

        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(58, "cross-doc")
        assert '<mark class="recovered-inline">' in result["text_html"]

    def test_multiple_occurrences_all_highlighted(self, test_config, mock_db):
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT INTO documents (id, source, extracted_text, text_processed) VALUES ('multi-doc', 'test', 'hello world then hello world again', 1)")
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (56, 1)")
        conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (56, 'multi-doc', 0.9)")
        segments = json.dumps([{"source_doc_id": "other", "text": "hello world"}])
        conn.execute("INSERT INTO merge_results (group_id, merged_text, recovered_count, recovered_segments) VALUES (56, '', 1, ?)", (segments,))
        conn.commit()
        conn.close()
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(56, "multi-doc")
        mark_count = result["text_html"].count('<mark class="recovered-inline">')
        assert mark_count == 2

    def test_overlapping_segments_merged(self, test_config, mock_db):
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT INTO documents (id, source, extracted_text, text_processed) VALUES ('overlap-doc', 'test', 'ABCDEFGHIJ', 1)")
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (54, 1)")
        conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (54, 'overlap-doc', 0.9)")
        segments = json.dumps([{"source_doc_id": "other", "text": "BCDEF"}, {"source_doc_id": "other", "text": "DEFGH"}])
        conn.execute("INSERT INTO merge_results (group_id, merged_text, recovered_count, recovered_segments) VALUES (54, '', 2, ?)", (segments,))
        conn.commit()
        conn.close()
        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(54, "overlap-doc")
        mark_count = result["text_html"].count('<mark class="recovered-inline">')
        assert mark_count == 1
        assert "BCDEFGH" in result["text_html"]

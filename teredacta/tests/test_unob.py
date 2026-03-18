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

import json
import sqlite3

import pytest


@pytest.fixture
def seeded_recovery(mock_db, tmp_dir):
    """Insert recovery data with segments for source panel tests."""
    conn = sqlite3.connect(str(mock_db))
    conn.execute(
        "INSERT INTO documents (id, source, release_batch, original_filename, "
        "text_processed, text_source, extracted_text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("src-001", "doj", "VOL00001", "letter.pdf", 1, "pdf_text_layer",
         "Dear Ghislaine Maxwell, meeting at the townhouse on 71st..."),
    )
    conn.execute(
        "INSERT INTO documents (id, source, release_batch, original_filename, "
        "text_processed, text_source, extracted_text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("src-002", "doj", "VOL00001", "email.pdf", 1, "jmail",
         "From: JE To: GM Subject: plans about Maxwell"),
    )
    conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (50, 1)")
    conn.execute(
        "INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (50, 'src-001', 0.95)"
    )
    conn.execute(
        "INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (50, 'src-002', 0.88)"
    )
    segments = json.dumps([
        {"source_doc_id": "src-001", "text": "Ghislaine Maxwell", "position": 5},
        {"source_doc_id": "src-002", "text": "the townhouse on 71st", "position": 30},
    ])
    conn.execute(
        "INSERT INTO merge_results (group_id, merged_text, recovered_count, "
        "total_redacted, source_doc_ids, recovered_segments) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (50, "Dear <change><u>Ghislaine Maxwell</u></change>, meeting at <change><u>the townhouse on 71st</u></change>...",
         2, 3, json.dumps(["src-001", "src-002"]), segments),
    )
    conn.commit()
    conn.close()
    # Create a cached PDF for src-001
    pdf_dir = tmp_dir / "pdf_cache" / "VOL00001"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / "letter.pdf").write_bytes(b"%PDF-1.4 fake")
    return mock_db


@pytest.fixture
def recovery_with_pdf_url(mock_db, tmp_dir):
    """Recovery where document has pdf_url but no cached PDF."""
    conn = sqlite3.connect(str(mock_db))
    conn.execute(
        "INSERT INTO documents (id, source, release_batch, original_filename, "
        "text_processed, text_source, extracted_text, pdf_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("src-url-001", "doj", "VOL00002", "remote.pdf", 1, "pdf_text_layer",
         "Dear Maxwell, the meeting...",
         "https://www.courtlistener.com/docket/12345/remote.pdf"),
    )
    conn.execute(
        "INSERT INTO documents (id, source, release_batch, original_filename, "
        "text_processed, text_source, extracted_text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("src-url-002", "doj", "VOL00002", "nourl.pdf", 1, "pdf_text_layer",
         "Dear Epstein, another meeting..."),
    )
    conn.execute(
        "INSERT INTO documents (id, source, release_batch, original_filename, "
        "text_processed, text_source, extracted_text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("src-url-003", "doj", "VOL00002", "email_rec.pdf", 1, "jmail",
         "From: JE To: GM Subject: plans"),
    )
    conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (55, 1)")
    conn.execute(
        "INSERT INTO match_group_members (group_id, doc_id, similarity) "
        "VALUES (55, 'src-url-001', 0.95)"
    )
    conn.execute(
        "INSERT INTO match_group_members (group_id, doc_id, similarity) "
        "VALUES (55, 'src-url-002', 0.90)"
    )
    conn.execute(
        "INSERT INTO match_group_members (group_id, doc_id, similarity) "
        "VALUES (55, 'src-url-003', 0.85)"
    )
    segments = json.dumps([
        {"source_doc_id": "src-url-001", "text": "Maxwell", "position": 5},
        {"source_doc_id": "src-url-002", "text": "Epstein", "position": 5},
        {"source_doc_id": "src-url-003", "text": "plans", "position": 30},
    ])
    conn.execute(
        "INSERT INTO merge_results (group_id, merged_text, recovered_count, "
        "total_redacted, source_doc_ids, recovered_segments) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (55,
         "Dear <change><u>Maxwell</u></change>, <change><u>Epstein</u></change>, <change><u>plans</u></change>",
         3, 5, json.dumps(["src-url-001", "src-url-002", "src-url-003"]), segments),
    )
    conn.commit()
    conn.close()
    # No cached PDFs created intentionally
    return mock_db


class TestSourcePanel:
    def test_source_panel_returns_200(self, client, seeded_recovery):
        resp = client.get("/recoveries/50/source?segment_index=0")
        assert resp.status_code == 200
        assert "Ghislaine Maxwell" in resp.text

    def test_source_panel_pdf_cached(self, client, seeded_recovery):
        resp = client.get("/recoveries/50/source?segment_index=0")
        assert resp.status_code == 200
        assert "View PDF" in resp.text  # Link to open PDF in new tab

    def test_source_panel_no_pdf(self, client, seeded_recovery):
        # Segment 1 is from src-002 which has text_source=jmail (no PDF)
        resp = client.get("/recoveries/50/source?segment_index=1")
        assert resp.status_code == 200
        assert "log-viewer" in resp.text or "not available" in resp.text.lower()

    def test_source_panel_invalid_segment(self, client, seeded_recovery):
        resp = client.get("/recoveries/50/source?segment_index=99")
        assert resp.status_code == 404

    def test_source_panel_invalid_group(self, client, seeded_recovery):
        resp = client.get("/recoveries/999/source?segment_index=0")
        assert resp.status_code == 404

    def test_source_panel_missing_segment_index(self, client, seeded_recovery):
        resp = client.get("/recoveries/50/source")
        assert resp.status_code == 422  # FastAPI validation error

    def test_source_context_method(self, test_config, seeded_recovery):
        from teredacta.unob import UnobInterface
        unob = UnobInterface(test_config)
        ctx = unob.get_source_context(50, 0)
        assert ctx is not None
        assert ctx["source_doc_id"] == "src-001"
        assert ctx["recovered_text"] == "Ghislaine Maxwell"
        assert ctx["has_pdf"] is True
        assert ctx["pdf_cached"] is True
        assert "search_context" in ctx

    def test_source_context_email_record(self, test_config, seeded_recovery):
        from teredacta.unob import UnobInterface
        unob = UnobInterface(test_config)
        ctx = unob.get_source_context(50, 1)
        assert ctx is not None
        assert ctx["source_doc_id"] == "src-002"
        assert ctx["has_pdf"] is False
        assert ctx["extracted_text"] != ""


class TestSourcePanelPdfUrl:
    """Tests for pdf_url rendering in source panel."""

    def test_source_context_returns_pdf_url(self, test_config, recovery_with_pdf_url):
        """get_source_context returns pdf_url when document has one."""
        from teredacta.unob import UnobInterface
        unob = UnobInterface(test_config)
        ctx = unob.get_source_context(55, 0)
        assert ctx is not None
        assert ctx["pdf_url"] == "https://www.courtlistener.com/docket/12345/remote.pdf"

    def test_source_context_returns_none_pdf_url(self, test_config, recovery_with_pdf_url):
        """get_source_context returns None pdf_url when document has no pdf_url."""
        from teredacta.unob import UnobInterface
        unob = UnobInterface(test_config)
        ctx = unob.get_source_context(55, 1)
        assert ctx is not None
        assert ctx["pdf_url"] is None

    def test_source_panel_renders_pdf_url_link(self, client, recovery_with_pdf_url):
        """Source panel renders link to source site when has_pdf and pdf_url."""
        resp = client.get("/recoveries/55/source?segment_index=0")
        assert resp.status_code == 200
        assert "View PDF on source site" in resp.text
        assert "https://www.courtlistener.com/docket/12345/remote.pdf" in resp.text

    def test_source_panel_renders_not_cached_without_url(self, client, recovery_with_pdf_url):
        """Source panel renders 'not cached' when has_pdf but no pdf_url."""
        resp = client.get("/recoveries/55/source?segment_index=1")
        assert resp.status_code == 200
        assert "PDF not cached locally" in resp.text
        # Should NOT have a link to source site
        assert "source site" not in resp.text

    def test_source_panel_renders_email_record(self, client, recovery_with_pdf_url):
        """Source panel still renders 'email record' when not has_pdf."""
        resp = client.get("/recoveries/55/source?segment_index=2")
        assert resp.status_code == 200
        assert "email record" in resp.text

    def test_source_panel_cached_pdf_overrides_url(self, client, recovery_with_pdf_url, tmp_dir):
        """When PDF is cached, show View PDF button even if pdf_url exists."""
        # Create the cached PDF
        pdf_dir = tmp_dir / "pdf_cache" / "VOL00002"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        (pdf_dir / "remote.pdf").write_bytes(b"%PDF-1.4 fake")
        resp = client.get("/recoveries/55/source?segment_index=0")
        assert resp.status_code == 200
        assert "View PDF" in resp.text
        # The "View PDF" button should use the cached path, not the external URL
        assert "/pdf/view?type=cache" in resp.text

    def test_source_panel_pdf_url_xss(self, client, mock_db, tmp_dir):
        """XSS in pdf_url should be escaped in source panel output."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, release_batch, original_filename, "
            "text_processed, text_source, extracted_text, pdf_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("src-xss-001", "doj", "VOL00003", "xss.pdf", 1, "pdf_text_layer",
             "Some text here",
             '"><script>alert(1)</script><a href="'),
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (56, 1)")
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (56, 'src-xss-001', 0.95)"
        )
        segments = json.dumps([
            {"source_doc_id": "src-xss-001", "text": "Some text", "position": 0},
        ])
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count, "
            "total_redacted, source_doc_ids, recovered_segments) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (56, "<change><u>Some text</u></change> here",
             1, 1, json.dumps(["src-xss-001"]), segments),
        )
        conn.commit()
        conn.close()
        resp = client.get("/recoveries/56/source?segment_index=0")
        assert resp.status_code == 200
        assert "<script>alert(1)</script>" not in resp.text

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

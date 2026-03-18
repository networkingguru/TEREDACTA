import json
import sqlite3
import pytest

@pytest.fixture
def full_db(mock_db):
    """Fully populated DB for integration testing."""
    conn = sqlite3.connect(str(mock_db))
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
    conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (1, 1)")
    conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'doc-0', 0.95)")
    conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'doc-1', 0.88)")
    segments = json.dumps([
        {"source_doc_id": "doc-1", "text": "Recovered Name Here", "position": 10},
    ])
    conn.execute(
        "INSERT INTO merge_results (group_id, merged_text, recovered_count, "
        "total_redacted, source_doc_ids, recovered_segments) VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Full text with Recovered Name Here revealed", 1, 2,
         json.dumps(["doc-0", "doc-1"]), segments),
    )
    conn.execute("INSERT INTO jobs (stage, status, priority) VALUES ('index', 'done', 0)")
    conn.execute("INSERT INTO jobs (stage, status, priority) VALUES ('merge', 'pending', 100)")
    conn.commit()
    conn.close()
    return mock_db

class TestFullNavigation:
    def test_dashboard(self, client, full_db):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "5" in resp.text

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

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
        resp = client.get("/documents?search=Document", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        assert "<nav" not in resp.text

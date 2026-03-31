class TestRecoveries:
    def test_list_returns_200(self, client):
        resp = client.get("/recoveries")
        assert resp.status_code == 200

    def test_search_recoveries(self, client):
        resp = client.get("/recoveries?search=Maxwell")
        assert resp.status_code == 200

    def test_common_unredactions_endpoint(self, client):
        resp = client.get("/recoveries/common")
        assert resp.status_code == 200

    def test_search_htmx_returns_partial(self, client):
        resp = client.get("/recoveries?search=Maxwell", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        # Should not contain full HTML page chrome
        assert "<html" not in resp.text.lower()

    def test_detail_not_found(self, client):
        resp = client.get("/recoveries/999")
        assert resp.status_code == 404

    def test_tab_merged_text(self, client):
        resp = client.get("/recoveries/1/tab/merged-text", headers={"HX-Request": "true"})
        assert resp.status_code in (200, 404)


import json
import sqlite3


def _seed_for_member_text(mock_db):
    """Seed DB for member-text endpoint tests."""
    conn = sqlite3.connect(str(mock_db))
    conn.execute(
        "INSERT INTO documents (id, source, extracted_text, text_processed, text_source) "
        "VALUES ('mt-doc-0', 'test', 'Hello [REDACTED] world', 1, 'jmail')"
    )
    conn.execute(
        "INSERT INTO documents (id, source, extracted_text, text_processed, text_source) "
        "VALUES ('mt-doc-1', 'test', 'Hello beautiful world', 1, 'jmail')"
    )
    conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (10, 1)")
    conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (10, 'mt-doc-0', 0.95)")
    conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (10, 'mt-doc-1', 0.90)")
    segments = json.dumps([{"source_doc_id": "mt-doc-1", "text": "beautiful"}])
    conn.execute(
        "INSERT INTO merge_results (group_id, merged_text, recovered_count, source_doc_ids, recovered_segments) "
        "VALUES (10, 'Hello beautiful world', 1, ?, ?)",
        (json.dumps(["mt-doc-0", "mt-doc-1"]), segments),
    )
    conn.commit()
    conn.close()


class TestMemberTextEndpoint:
    def test_returns_200_with_highlighted_html(self, client, mock_db):
        _seed_for_member_text(mock_db)
        resp = client.get("/recoveries/10/member-text?doc_id=mt-doc-1")
        assert resp.status_code == 200
        assert '<mark class="recovered-inline">' in resp.text
        assert "beautiful" in resp.text

    def test_returns_404_for_nonmember(self, client, mock_db):
        _seed_for_member_text(mock_db)
        resp = client.get("/recoveries/10/member-text?doc_id=nonexistent")
        assert resp.status_code == 404

    def test_returns_404_for_nonexistent_group(self, client, mock_db):
        _seed_for_member_text(mock_db)
        resp = client.get("/recoveries/999/member-text?doc_id=mt-doc-0")
        assert resp.status_code == 404

    def test_returns_html_content_type(self, client, mock_db):
        _seed_for_member_text(mock_db)
        resp = client.get("/recoveries/10/member-text?doc_id=mt-doc-0")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

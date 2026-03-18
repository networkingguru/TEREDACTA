import pytest
from unittest.mock import AsyncMock, patch


class TestDashboard:
    def test_dashboard_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "TEREDACTA" in resp.text

    def test_dashboard_shows_stats(self, client, mock_db, test_config):
        import sqlite3
        conn = sqlite3.connect(str(mock_db))
        conn.execute("INSERT INTO documents (id, source, text_processed) VALUES ('d1', 'doj', 1)")
        conn.commit()
        conn.close()
        resp = client.get("/")
        assert resp.status_code == 200

    def test_sse_endpoint_no_sse(self, app, client):
        """When SSE manager is removed, endpoint returns 503."""
        app.state.sse = None
        resp = client.get("/sse/stats")
        assert resp.status_code == 503

    def test_daemon_status_fragment(self, client):
        resp = client.get("/sse/daemon-status")
        assert resp.status_code == 200
        assert "STOPPED" in resp.text or "RUNNING" in resp.text

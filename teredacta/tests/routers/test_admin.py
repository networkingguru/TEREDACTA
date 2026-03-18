import pytest


class TestAdminLogin:
    def test_login_page(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 200

    def test_admin_dashboard_local_no_password(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 200


class TestAdminDaemon:
    def test_daemon_start_local(self, client):
        resp = client.post("/admin/daemon/start", headers={"HX-Request": "true"})
        assert resp.status_code == 200

    def test_daemon_status(self, client):
        resp = client.get("/admin/daemon/status")
        assert resp.status_code == 200


class TestAdminConfig:
    def test_config_page(self, client):
        resp = client.get("/admin/config")
        assert resp.status_code == 200


class TestAdminSearch:
    def test_search_page(self, client):
        resp = client.get("/admin/search")
        assert resp.status_code == 200

    def test_search_submit(self, client):
        resp = client.post("/admin/search", data={"person": "test"}, headers={"HX-Request": "true"})
        assert resp.status_code == 200


class TestAdminLogs:
    def test_logs_page(self, client):
        resp = client.get("/admin/logs")
        assert resp.status_code == 200


class TestAdminDownloads:
    def test_downloads_page(self, client):
        resp = client.get("/admin/downloads")
        assert resp.status_code == 200

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


class TestAdminEntityIndex:
    def test_entity_index_status_not_built(self, client):
        resp = client.get("/admin/entity-index/status")
        assert resp.status_code == 200
        assert "Not built" in resp.text

    def test_entity_index_status_ready(self, client_with_entities):
        resp = client_with_entities.get("/admin/entity-index/status")
        assert resp.status_code == 200
        assert "Ready" in resp.text
        assert "entities" in resp.text

    def test_entity_index_build(self, client_with_entities):
        resp = client_with_entities.post("/admin/entity-index/build")
        assert resp.status_code == 200
        assert "Built" in resp.text
        assert "entities" in resp.text

    def test_entity_index_build_requires_admin(self, app):
        """Non-admin POST should be rejected when login is required."""
        from fastapi.testclient import TestClient
        # Force admin_requires_login by setting a password hash
        import bcrypt
        app.state.config.admin_password_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
        c = TestClient(app)
        resp = c.post("/admin/entity-index/build")
        assert resp.status_code == 403

    def test_dashboard_has_entity_card(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "Entity Index" in resp.text
        assert "entity-index/build" in resp.text

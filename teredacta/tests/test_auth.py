import bcrypt
import pytest
from fastapi.testclient import TestClient

class TestAdminAuth:
    def test_admin_page_no_password_local(self, client):
        resp = client.get("/admin")
        assert resp.status_code == 200

    def test_admin_page_requires_login_server_mode(self, test_config, mock_db):
        test_config.host = "0.0.0.0"
        pw_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
        test_config.admin_password_hash = pw_hash
        from teredacta.app import create_app
        app = create_app(test_config)
        client = TestClient(app, base_url="https://testserver")
        resp = client.get("/admin/")
        assert resp.status_code == 200  # Shows login page

    def test_login_success(self, test_config, mock_db):
        test_config.host = "0.0.0.0"
        pw_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
        test_config.admin_password_hash = pw_hash
        from teredacta.app import create_app
        app = create_app(test_config)
        client = TestClient(app, base_url="https://testserver")
        resp = client.post("/admin/login", data={"password": "secret"}, follow_redirects=False)
        assert resp.status_code == 303
        assert "session" in resp.cookies

    def test_login_failure(self, test_config, mock_db):
        test_config.host = "0.0.0.0"
        pw_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
        test_config.admin_password_hash = pw_hash
        from teredacta.app import create_app
        app = create_app(test_config)
        client = TestClient(app, base_url="https://testserver")
        resp = client.post("/admin/login", data={"password": "wrong"})
        assert resp.status_code == 401

class TestCSRF:
    def test_csrf_token_set_on_login(self, test_config, mock_db):
        test_config.host = "0.0.0.0"
        pw_hash = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
        test_config.admin_password_hash = pw_hash
        from teredacta.app import create_app
        app = create_app(test_config)
        client = TestClient(app, base_url="https://testserver")
        resp = client.post("/admin/login", data={"password": "secret"}, follow_redirects=False)
        assert "session" in resp.cookies
        # Extract CSRF token from session cookie
        from itsdangerous import URLSafeTimedSerializer
        serializer = URLSafeTimedSerializer(test_config.secret_key)
        session_data = serializer.loads(resp.cookies["session"])
        csrf_token = session_data["csrf"]
        # After login, admin endpoints should be accessible with session cookie + CSRF token
        resp2 = client.post("/admin/daemon/start", headers={"X-CSRF-Token": csrf_token})
        assert resp2.status_code == 200

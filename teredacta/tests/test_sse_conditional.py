import pytest
from fastapi.testclient import TestClient

from teredacta.config import TeredactaConfig


@pytest.fixture
def public_client(tmp_dir, mock_db):
    """Client where admin requires login (simulates production)."""
    config = TeredactaConfig(
        unobfuscator_path=str(tmp_dir),
        unobfuscator_bin="echo",
        db_path=str(mock_db),
        pdf_cache_dir=str(tmp_dir / "pdf_cache"),
        output_dir=str(tmp_dir / "output"),
        log_path=str(tmp_dir / "unobfuscator.log"),
        host="0.0.0.0",  # non-local → admin requires login
        port=8000,
        admin_password_hash="$2b$12$fakehashfakehashfakehashfakehashfakehashfakehashfake",
        log_level="info",
        session_timeout_minutes=60,
        sse_poll_interval_seconds=2,
        subprocess_timeout_seconds=5,
    )
    from teredacta.app import create_app
    app = create_app(config)
    return TestClient(app)


def test_public_page_no_sse_polling(public_client):
    """Public pages should not poll /sse/daemon-status."""
    resp = public_client.get("/recoveries")
    assert resp.status_code == 200
    assert "/sse/daemon-status" not in resp.text


def test_admin_page_has_sse_polling(client):
    """Admin pages should still have daemon status polling."""
    # In local mode, admin is auto-enabled
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "daemon-status" in resp.text

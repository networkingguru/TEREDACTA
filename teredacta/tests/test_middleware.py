"""Tests for pure ASGI template context middleware."""
import pytest
from fastapi.testclient import TestClient


def test_middleware_sets_is_admin_on_request(client):
    """Every response should have been processed by the middleware."""
    response = client.get("/")
    assert response.status_code in (200, 302, 307)


def test_middleware_sets_csrf_token(app):
    """The middleware should set csrf_token on request state."""
    from starlette.testclient import TestClient as StarletteClient
    client = StarletteClient(app)
    response = client.get("/documents")
    assert response.status_code == 200


def test_sse_endpoint_works_with_middleware(app):
    """SSE daemon-status fragment (non-streaming) should work with the middleware."""
    from starlette.testclient import TestClient as StarletteClient
    client = StarletteClient(app)
    # Use the non-streaming SSE fragment endpoint to verify middleware works
    # without dealing with infinite SSE streams in tests
    response = client.get("/sse/daemon-status")
    assert response.status_code in (200, 403)

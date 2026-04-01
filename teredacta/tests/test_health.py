"""Tests for health endpoint and pool_status."""

import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from teredacta.db_pool import ConnectionPool


class TestPoolStatus:
    def test_pool_status_empty_pool(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        pool = ConnectionPool(str(db), max_size=4)
        status = pool.pool_status()
        assert status == {"idle": 0, "in_use": 0, "capacity": 4}
        pool.close()

    def test_pool_status_one_acquired(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        pool = ConnectionPool(str(db), max_size=4)
        conn = pool.acquire()
        status = pool.pool_status()
        assert status == {"idle": 0, "in_use": 1, "capacity": 4}
        pool.release(conn)
        pool.close()

    def test_pool_status_acquire_and_release(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        pool = ConnectionPool(str(db), max_size=4)
        conn = pool.acquire()
        pool.release(conn)
        status = pool.pool_status()
        assert status == {"idle": 1, "in_use": 0, "capacity": 4}
        pool.close()

    def test_pool_status_fully_acquired(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        pool = ConnectionPool(str(db), max_size=2)
        c1 = pool.acquire()
        c2 = pool.acquire()
        status = pool.pool_status()
        assert status == {"idle": 0, "in_use": 2, "capacity": 2}
        pool.release(c1)
        pool.release(c2)
        pool.close()


import asyncio
from teredacta.config import TeredactaConfig
from teredacta.sse import SSEManager


class TestSSESubscriberCount:
    """Tests must be async because SSEManager.subscribe() calls asyncio.create_task()."""

    @pytest.mark.asyncio
    async def test_subscriber_count_zero(self):
        sse = SSEManager(poll_interval=1.0, unob=None)
        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_subscriber_count_after_subscribe(self):
        sse = SSEManager(poll_interval=1.0, unob=None)
        q = sse.subscribe()
        assert sse.subscriber_count == 1
        sse.unsubscribe(q)
        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_subscriber_count_multiple(self):
        sse = SSEManager(poll_interval=1.0, unob=None)
        q1 = sse.subscribe()
        q2 = sse.subscribe()
        assert sse.subscriber_count == 2
        sse.unsubscribe(q1)
        assert sse.subscriber_count == 1
        sse.unsubscribe(q2)
        assert sse.subscriber_count == 0


class TestHealthConfig:
    def test_default_health_thresholds(self):
        cfg = TeredactaConfig()
        assert cfg.health_pool_degraded_threshold == 3
        assert cfg.health_sse_degraded_threshold == 20

    def test_custom_health_thresholds(self):
        cfg = TeredactaConfig(
            health_pool_degraded_threshold=5,
            health_sse_degraded_threshold=50,
        )
        assert cfg.health_pool_degraded_threshold == 5
        assert cfg.health_sse_degraded_threshold == 50


class TestHealthEndpoints:
    @pytest.fixture
    def health_client(self, tmp_path):
        """Create a test client with a real DB for health tests."""
        db_path = tmp_path / "test.db"
        sqlite3.connect(str(db_path)).close()
        cfg = TeredactaConfig(
            unobfuscator_path=str(tmp_path),
            unobfuscator_bin="echo",
            db_path=str(db_path),
            pdf_cache_dir=str(tmp_path / "pdf_cache"),
            output_dir=str(tmp_path / "output"),
            log_path=str(tmp_path / "unobfuscator.log"),
            host="127.0.0.1",
            port=8000,
        )
        (tmp_path / "pdf_cache").mkdir(exist_ok=True)
        (tmp_path / "output").mkdir(exist_ok=True)
        (tmp_path / "unobfuscator.log").touch()
        from teredacta.app import create_app
        app = create_app(cfg)
        return TestClient(app)

    def test_liveness_returns_ok(self, health_client):
        resp = health_client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_readiness_healthy_before_any_queries(self, health_client):
        resp = health_client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_readiness_includes_details_from_localhost(self, health_client):
        resp = health_client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data
        assert "db_pool" in data["checks"]
        assert "sse" in data["checks"]
        assert "uptime_seconds" in data["checks"]
        assert "worker_pid" in data

    def test_readiness_pool_none_is_healthy(self, health_client):
        resp = health_client.get("/health/ready")
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["checks"]["db_pool"]["status"] == "ok"

    def test_readiness_returns_503_when_unhealthy(self, health_client):
        app = health_client.app
        unob = app.state.unob
        conns = []
        for _ in range(8):
            conns.append(unob._get_db())
        resp = health_client.get("/health/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unhealthy"
        assert data["checks"]["db_pool"]["idle"] == 0
        assert data["checks"]["db_pool"]["in_use"] == 8
        for c in conns:
            unob._release_db(c)

    def test_liveness_works_when_readiness_unhealthy(self, health_client):
        app = health_client.app
        unob = app.state.unob
        conns = [unob._get_db() for _ in range(8)]
        assert health_client.get("/health/ready").status_code == 503
        resp = health_client.get("/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        for c in conns:
            unob._release_db(c)

    def test_readiness_timeout_returns_503(self, health_client):
        import asyncio
        from unittest.mock import patch
        async def slow_checks(*args, **kwargs):
            await asyncio.sleep(5)
        with patch("teredacta.routers.health._readiness_checks", slow_checks):
            resp = health_client.get("/health/ready")
            assert resp.status_code == 503
            assert resp.json()["status"] == "unhealthy"

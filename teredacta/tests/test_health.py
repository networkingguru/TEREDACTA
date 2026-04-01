"""Tests for health endpoint and pool_status."""

import sqlite3
import threading
import time

import pytest

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

"""Stress test reproducing the production compound deadlock.

The production hang was: all default executor threads blocked on
pool.acquire() (30s timeout) while SSE poll and admin requests
also need executor threads. This test verifies:
1. The event loop stays responsive during compound contention
2. The system recovers after holds are released
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import pytest_asyncio
import httpx

from teredacta.db_pool import ConnectionPool


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestCompoundDeadlock:

    @pytest_asyncio.fixture(autouse=True)
    async def pin_executor(self):
        """Pin executor to 8 threads (same as pool size) and restore after."""
        loop = asyncio.get_running_loop()
        original_executor = loop._default_executor
        small_executor = ThreadPoolExecutor(max_workers=8)
        loop.set_default_executor(small_executor)
        yield small_executor
        if original_executor is not None:
            loop.set_default_executor(original_executor)
        small_executor.shutdown(wait=False, cancel_futures=True)

    @pytest.mark.asyncio
    async def test_event_loop_survives_compound_deadlock(self, stress_app, stress_db):
        """Event loop stays responsive even when executor + pool are both saturated."""
        loop = asyncio.get_running_loop()

        # Create a pool we can control
        pool = ConnectionPool(str(stress_db), max_size=8, read_only=True)

        # Phase 1: Hold all 8 pool connections
        held_conns = [pool.acquire(timeout=5.0) for _ in range(8)]
        assert pool.pool_status()["in_use"] == 8

        # Phase 2: Saturate executor with tasks trying to acquire pool connections
        # These will all block for up to 2 seconds waiting for a connection
        blocked_futures = []
        for _ in range(8):
            fut = loop.run_in_executor(
                None,
                lambda: pool.acquire(timeout=2.0),
            )
            blocked_futures.append(fut)

        # Give executor threads time to start blocking
        await asyncio.sleep(0.5)

        # Phase 3: Verify event loop is still alive
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=stress_app),
            base_url="http://testserver",
        ) as client:
            resp = await asyncio.wait_for(
                client.get("/health/live"),
                timeout=2.0,
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

        # Phase 4: Release all held connections
        for conn in held_conns:
            pool.release(conn)

        # Phase 5: Wait for blocked futures to resolve
        results = await asyncio.gather(*blocked_futures, return_exceptions=True)

        # Some may have acquired (after release), some may have timed out
        acquired = [r for r in results if not isinstance(r, Exception)]

        # Release any that acquired
        for conn in acquired:
            pool.release(conn)

        # Phase 6: Verify recovery
        status = pool.pool_status()
        assert status["in_use"] == 0

        # New acquire should work instantly
        conn = pool.acquire(timeout=1.0)
        pool.release(conn)

        pool.close()

    @pytest.mark.asyncio
    async def test_health_reports_degraded_during_contention(self, stress_app):
        """Health endpoint reports correct status during compound contention."""
        unob = stress_app.state.unob

        # Force pool creation by making a query
        conn = unob._get_db()
        unob._release_db(conn)

        # Hold all but 1 connection
        held = []
        for _ in range(7):
            held.append(unob._get_db())

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=stress_app),
            base_url="http://testserver",
        ) as client:
            resp = await client.get("/health/ready")
            data = resp.json()
            # With 7 held, available = capacity(8) - in_use(7 or 8) <= 1
            # Status should be degraded or unhealthy (the request itself may use a connection)
            assert data["status"] in ("degraded", "unhealthy")
            assert data["checks"]["db_pool"]["in_use"] >= 7

        for c in held:
            unob._release_db(c)

        # After release — should be healthy again
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=stress_app),
            base_url="http://testserver",
        ) as client:
            resp = await client.get("/health/ready")
            data = resp.json()
            assert data["status"] == "healthy"

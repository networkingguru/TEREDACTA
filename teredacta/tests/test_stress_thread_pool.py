"""Stress tests for thread pool exhaustion scenarios."""

import asyncio
import threading

import anyio
import anyio.to_thread
import pytest
import pytest_asyncio
import httpx


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestThreadPoolExhaustion:

    @pytest_asyncio.fixture(autouse=True)
    async def pin_executor(self):
        """Shrink anyio's default thread limiter to 4 tokens and restore after test.

        Starlette runs sync endpoints via anyio.to_thread.run_sync which uses
        the default CapacityLimiter, NOT the event-loop's default executor.
        """
        limiter = anyio.to_thread.current_default_thread_limiter()
        original_tokens = limiter.total_tokens
        limiter.total_tokens = 4
        yield limiter
        limiter.total_tokens = original_tokens

    async def _saturate_limiter(self, barrier: threading.Event):
        """Saturate the anyio thread limiter with blocking tasks.

        Returns a list of asyncio tasks that are occupying the limiter slots.
        Caller must set barrier to release them.
        """
        tasks = []

        async def occupy_slot():
            await anyio.to_thread.run_sync(lambda: barrier.wait(timeout=10.0))

        for _ in range(4):
            tasks.append(asyncio.ensure_future(occupy_slot()))

        # Give threads time to start and acquire limiter tokens
        await asyncio.sleep(0.5)
        return tasks

    @pytest.mark.asyncio
    async def test_liveness_responds_when_executor_saturated(self, stress_app, pin_executor):
        """Liveness probe responds fast even when the thread pool is fully saturated.

        Control assertion: a sync endpoint (/documents/) that runs in the
        thread pool must time out while the pool is blocked, proving the
        pool really is saturated.  Without this control the liveness check
        is vacuous.
        """
        barrier = threading.Event()
        blocking_tasks = await self._saturate_limiter(barrier)

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=stress_app),
                base_url="http://testserver",
            ) as client:
                # Control: sync endpoint should be blocked by saturated thread pool
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        client.get("/documents/"),
                        timeout=1.0,
                    )

                # Liveness (pure async) should respond immediately
                resp = await asyncio.wait_for(
                    client.get("/health/live"),
                    timeout=3.0,
                )
                assert resp.status_code == 200
                assert resp.json()["status"] == "ok"
        finally:
            barrier.set()
            await asyncio.gather(*blocking_tasks, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_page_requests_degrade_under_executor_exhaustion(self, stress_app, pin_executor):
        """User-facing sync endpoints degrade while health probes stay responsive.

        Saturates the thread pool, then fires requests at both a sync endpoint
        (/documents/) and the async health endpoints concurrently.  Health
        endpoints must succeed; the sync endpoint must fail or time out.
        After releasing the thread pool, the sync endpoint must recover.
        """
        barrier = threading.Event()
        blocking_tasks = await self._saturate_limiter(barrier)

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=stress_app),
                base_url="http://testserver",
            ) as client:
                # Fire health + user-facing requests concurrently
                live_task = asyncio.ensure_future(
                    asyncio.wait_for(client.get("/health/live"), timeout=3.0)
                )
                ready_task = asyncio.ensure_future(
                    asyncio.wait_for(client.get("/health/ready"), timeout=3.0)
                )
                docs_task = asyncio.ensure_future(
                    asyncio.wait_for(client.get("/documents/"), timeout=1.0)
                )

                # Health probes must succeed
                live_resp = await live_task
                assert live_resp.status_code == 200
                assert live_resp.json()["status"] == "ok"

                ready_resp = await ready_task
                assert ready_resp.status_code == 200

                # Sync endpoint must time out (thread pool is saturated)
                with pytest.raises(asyncio.TimeoutError):
                    await docs_task

        finally:
            barrier.set()
            await asyncio.gather(*blocking_tasks, return_exceptions=True)

        # After releasing the thread pool, the sync endpoint should recover
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=stress_app),
            base_url="http://testserver",
        ) as client:
            resp = await asyncio.wait_for(
                client.get("/documents/"),
                timeout=5.0,
            )
            assert resp.status_code == 200

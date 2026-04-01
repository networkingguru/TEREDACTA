"""Stress tests for thread pool exhaustion scenarios."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import pytest_asyncio
import httpx


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestThreadPoolExhaustion:

    @pytest_asyncio.fixture(autouse=True)
    async def pin_executor(self):
        """Pin executor to small size and restore original after test."""
        loop = asyncio.get_running_loop()
        original_executor = loop._default_executor
        small_executor = ThreadPoolExecutor(max_workers=4)
        loop.set_default_executor(small_executor)
        yield small_executor
        # Restore original executor (may be None on fresh loops)
        if original_executor is not None:
            loop.set_default_executor(original_executor)
        small_executor.shutdown(wait=False, cancel_futures=True)

    @pytest.mark.asyncio
    async def test_liveness_responds_when_executor_saturated(self, stress_app, pin_executor):
        """Liveness probe works even when executor threads are all blocked."""
        loop = asyncio.get_running_loop()

        # Saturate the executor with short blocking tasks (2s, not 10s)
        barrier = threading.Event()
        futures = []
        for _ in range(4):
            fut = loop.run_in_executor(None, lambda: barrier.wait(timeout=2.0))
            futures.append(fut)

        try:
            await asyncio.sleep(0.3)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=stress_app),
                base_url="http://testserver",
            ) as client:
                resp = await asyncio.wait_for(
                    client.get("/health/live"),
                    timeout=3.0,
                )
                assert resp.status_code == 200
                assert resp.json()["status"] == "ok"
        finally:
            barrier.set()  # Unblock all threads
            await asyncio.gather(*futures, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_readiness_responds_when_executor_saturated(self, stress_app, pin_executor):
        """Readiness probe works even when executor threads are all blocked."""
        loop = asyncio.get_running_loop()
        barrier = threading.Event()

        futures = []
        for _ in range(4):
            fut = loop.run_in_executor(None, lambda: barrier.wait(timeout=2.0))
            futures.append(fut)

        try:
            await asyncio.sleep(0.3)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=stress_app),
                base_url="http://testserver",
            ) as client:
                resp = await asyncio.wait_for(
                    client.get("/health/ready"),
                    timeout=3.0,
                )
                assert resp.status_code == 200
                assert resp.json()["status"] == "healthy"
        finally:
            barrier.set()
            await asyncio.gather(*futures, return_exceptions=True)

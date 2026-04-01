"""Stress tests for admission control under contention."""

import asyncio
import pytest
import httpx
from fastapi import FastAPI
from teredacta.admission import AdmissionMiddleware


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestAdmissionStress:

    @pytest.fixture
    def admission_app(self):
        app = FastAPI()
        hold = asyncio.Event()

        @app.get("/slow")
        async def slow():
            await hold.wait()
            return {"status": "done"}

        @app.get("/fast")
        async def fast():
            return {"status": "done"}

        @app.get("/health/live")
        async def health():
            return {"status": "ok"}

        wrapped = AdmissionMiddleware(app, max_concurrent=3, max_queue=10)
        return wrapped, hold

    @pytest.mark.asyncio
    async def test_health_responds_while_queue_full(self, admission_app):
        """Health probes are never queued."""
        app, hold = admission_app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Fill all 3 slots
            tasks = [asyncio.ensure_future(client.get("/slow")) for _ in range(3)]
            await asyncio.sleep(0.2)

            # Fill the queue (10 slots)
            for _ in range(10):
                resp = await client.get("/fast")
                assert resp.status_code == 202  # queued

            # Health should still respond immediately (exempt from admission)
            resp = await asyncio.wait_for(client.get("/health/live"), timeout=2.0)
            assert resp.status_code == 200

            hold.set()
            for t in tasks:
                await t

    @pytest.mark.asyncio
    async def test_overflow_returns_503(self, admission_app):
        """Queue overflow gives 503."""
        app, hold = admission_app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Fill all 3 slots
            tasks = [asyncio.ensure_future(client.get("/slow")) for _ in range(3)]
            await asyncio.sleep(0.2)

            # Fill the queue (10 slots)
            for _ in range(10):
                await client.get("/fast")

            # Overflow — queue is full
            resp = await client.get("/fast")
            assert resp.status_code == 503
            assert "retry-after" in resp.headers

            hold.set()
            for t in tasks:
                await t

    @pytest.mark.asyncio
    async def test_timeout_releases_admission_slot(self):
        """Request that times out properly releases its admission slot."""
        from teredacta.timeout_middleware import RequestTimeoutMiddleware

        app = FastAPI()

        @app.get("/hang")
        async def hang():
            await asyncio.sleep(100)

        @app.get("/fast")
        async def fast():
            return {"status": "ok"}

        # Stack: AdmissionMiddleware → RequestTimeoutMiddleware → FastAPI
        # Admission wraps the timeout-wrapped app so that when the inner request
        # times out (504), the admission finally block still fires and frees the slot.
        inner = RequestTimeoutMiddleware(app, timeout_seconds=0.5)
        wrapped = AdmissionMiddleware(inner, max_concurrent=1, max_queue=5)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=wrapped), base_url="http://test"
        ) as client:
            # This will timeout — slot must be freed by the finally block
            resp = await client.get("/hang")
            assert resp.status_code == 504

            # Slot should be freed — next request should pass through
            resp = await client.get("/fast")
            assert resp.status_code == 200

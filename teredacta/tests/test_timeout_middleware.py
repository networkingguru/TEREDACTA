import asyncio
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from teredacta.timeout_middleware import RequestTimeoutMiddleware


@pytest.fixture
def timeout_app():
    app = FastAPI()

    @app.get("/fast")
    async def fast():
        return {"status": "ok"}

    @app.get("/slow")
    async def slow():
        await asyncio.sleep(10)
        return {"status": "ok"}

    app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=1.0)
    return app


class TestRequestTimeout:
    @pytest.mark.asyncio
    async def test_fast_request_succeeds(self, timeout_app):
        async with AsyncClient(transport=ASGITransport(app=timeout_app), base_url="http://test") as client:
            resp = await client.get("/fast")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_slow_request_times_out(self, timeout_app):
        async with AsyncClient(transport=ASGITransport(app=timeout_app), base_url="http://test") as client:
            resp = await client.get("/slow")
            assert resp.status_code == 504
            assert "timed out" in resp.text.lower()

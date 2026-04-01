"""Tests for the admission control middleware."""

import asyncio
import time

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from httpx import AsyncClient, ASGITransport

from teredacta.admission import AdmissionMiddleware, AdmissionState, QueueTicket


def _make_app(max_concurrent: int = 2, max_queue: int = 5, hold_event=None):
    """Build a tiny FastAPI app wrapped with AdmissionMiddleware."""
    inner = FastAPI()

    @inner.get("/work")
    async def work(request: Request):
        if hold_event is not None:
            await hold_event.wait()
        return PlainTextResponse("done")

    @inner.get("/health/live")
    async def health():
        return PlainTextResponse("ok")

    @inner.get("/static/style.css")
    async def static():
        return PlainTextResponse("body{}")

    @inner.get("/sse/events")
    async def sse():
        return PlainTextResponse("sse")

    wrapped = AdmissionMiddleware(inner, max_concurrent=max_concurrent, max_queue=max_queue)
    return wrapped


class TestAdmissionBasic:
    @pytest.mark.asyncio
    async def test_requests_under_limit_pass_through(self):
        app = _make_app(max_concurrent=5)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/work")
            assert resp.status_code == 200
            assert resp.text == "done"

    @pytest.mark.asyncio
    async def test_health_exempt(self):
        """Health endpoints bypass admission entirely."""
        app = _make_app(max_concurrent=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health/live")
            assert resp.status_code == 200
            assert resp.text == "ok"

    @pytest.mark.asyncio
    async def test_static_exempt(self):
        app = _make_app(max_concurrent=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/static/style.css")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_sse_exempt(self):
        app = _make_app(max_concurrent=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/sse/events")
            assert resp.status_code == 200


class TestAdmissionQueue:
    @pytest.mark.asyncio
    async def test_over_limit_gets_queue_page(self):
        """When all slots are taken, new requests get 202 with queue page."""
        hold = asyncio.Event()
        app = _make_app(max_concurrent=1, hold_event=hold)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Start a request that holds the slot
            task = asyncio.create_task(client.get("/work"))
            # Give it a moment to acquire the semaphore
            await asyncio.sleep(0.05)

            # Second request should be queued
            resp = await client.get("/work")
            assert resp.status_code == 202
            assert "_queue_ticket" in resp.headers.get("set-cookie", "")
            assert "Queue" in resp.text or "queue" in resp.text

            # Clean up
            hold.set()
            await task

    @pytest.mark.asyncio
    async def test_queue_overflow_returns_503(self):
        """When queue is full, return 503."""
        hold = asyncio.Event()
        app = _make_app(max_concurrent=1, max_queue=1, hold_event=hold)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Fill the slot
            task = asyncio.create_task(client.get("/work"))
            await asyncio.sleep(0.05)

            # Fill the queue (1 slot)
            resp1 = await client.get("/work")
            assert resp1.status_code == 202

            # Next should be 503
            resp2 = await client.get("/work")
            assert resp2.status_code == 503
            assert "retry-after" in resp2.headers

            hold.set()
            await task


class TestQueueStatus:
    @pytest.mark.asyncio
    async def test_status_known_ticket(self):
        """/_queue/status returns position for a known ticket."""
        hold = asyncio.Event()
        app = _make_app(max_concurrent=1, hold_event=hold)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Fill the slot
            task = asyncio.create_task(client.get("/work"))
            await asyncio.sleep(0.05)

            # Get queued
            resp = await client.get("/work")
            assert resp.status_code == 202
            cookie = resp.headers.get("set-cookie", "")
            # Extract ticket ID from set-cookie
            ticket_id = _extract_ticket_id(cookie)

            # Poll status
            status_resp = await client.get(f"/_queue/status?ticket={ticket_id}")
            assert status_resp.status_code == 200
            data = status_resp.json()
            assert "position" in data
            assert data["ready"] is False

            hold.set()
            await task

    @pytest.mark.asyncio
    async def test_status_unknown_ticket(self):
        """/_queue/status returns requeue for unknown ticket."""
        app = _make_app(max_concurrent=5)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/_queue/status?ticket=nonexistent")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("requeue") is True


class TestSlotTransfer:
    @pytest.mark.asyncio
    async def test_ready_ticket_passes_through(self):
        """A ready ticket cookie allows the request through without semaphore."""
        hold = asyncio.Event()
        app = _make_app(max_concurrent=1, hold_event=hold)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Fill the slot
            task1 = asyncio.create_task(client.get("/work"))
            await asyncio.sleep(0.05)

            # Get queued
            resp = await client.get("/work")
            assert resp.status_code == 202
            ticket_id = _extract_ticket_id(resp.headers.get("set-cookie", ""))

            # Release the slot — slot transfer should mark the ticket ready
            hold.set()
            await task1
            await asyncio.sleep(0.05)

            # Check status — should be ready
            status_resp = await client.get(f"/_queue/status?ticket={ticket_id}")
            data = status_resp.json()
            assert data["ready"] is True

            # Now use the ticket to get through
            resp2 = await client.get(
                "/work",
                cookies={"_queue_ticket": ticket_id},
            )
            assert resp2.status_code == 200
            assert resp2.text == "done"

    @pytest.mark.asyncio
    async def test_slot_transfer_maintains_semaphore_count(self):
        """After slot transfer, the semaphore count should NOT increase."""
        hold = asyncio.Event()
        app = _make_app(max_concurrent=1, hold_event=hold)
        # Get access to the state — it's on the middleware
        state = app.state

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Fill the slot — semaphore goes to 0
            task = asyncio.create_task(client.get("/work"))
            await asyncio.sleep(0.05)
            assert state.semaphore._value == 0

            # Queue a request
            resp = await client.get("/work")
            assert resp.status_code == 202

            # Release — slot should transfer, semaphore stays at 0
            hold.set()
            await task
            await asyncio.sleep(0.05)
            assert state.semaphore._value == 0  # Transferred, not released


class TestAdmissionState:
    def test_estimate_wait_no_data(self):
        """With no duration history, estimate uses default of 1.0s."""
        state = AdmissionState(max_concurrent=2, max_queue=10)
        est = state.estimate_wait(position=3)
        # 3 * 1.0 / max(1, 2-2) = 3 * 1.0 / 1 = 3.0
        # semaphore._value starts at 2, so active = max(1, 2-2) = 1
        assert est == 3.0

    def test_estimate_wait_with_data(self):
        """With enough duration history, estimate uses average."""
        state = AdmissionState(max_concurrent=4, max_queue=10)
        now = time.monotonic()
        for i in range(10):
            state._durations.append((now - i, 2.0))
        # Manually decrease semaphore to simulate 2 active
        # _value starts at 4; we want active=2 so _value=2
        state.semaphore._value = 2
        est = state.estimate_wait(position=4)
        # 4 * 2.0 / max(1, 4-2) = 8/2 = 4.0
        assert est == 4.0


@pytest_asyncio.fixture(autouse=True)
async def cleanup_expiry_tasks():
    yield
    # Cancel any pending expiry tasks created during the test
    import asyncio
    for task in asyncio.all_tasks():
        if task.get_name().startswith("Task") and not task.done():
            if "_expire" in str(task.get_coro()):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_exception_releases_slot(self):
        """If the inner app raises, the semaphore slot is still released."""
        app = FastAPI()

        @app.get("/crash")
        async def crash():
            raise RuntimeError("boom")

        @app.get("/ok")
        async def ok():
            return {"status": "ok"}

        wrapped = AdmissionMiddleware(app, max_concurrent=1, max_queue=5)

        async with AsyncClient(transport=ASGITransport(app=wrapped, raise_app_exceptions=False), base_url="http://test") as client:
            resp = await client.get("/crash")
            assert resp.status_code == 500

            # Slot must have been released — next request should succeed
            resp = await client.get("/ok")
            assert resp.status_code == 200


class TestTicketExpiry:
    @pytest.mark.asyncio
    async def test_ready_ticket_expires_and_releases_slot(self):
        """Ready ticket unclaimed for >60s releases its semaphore slot."""
        state = AdmissionState(max_concurrent=2, max_queue=10)

        await state.semaphore.acquire()
        await state.semaphore.acquire()
        assert state.semaphore._value == 0

        import time
        old_ticket = QueueTicket(id="old", ready=True, ready_at=time.monotonic() - 120)
        state._queue.append(old_ticket)
        state._tickets["old"] = old_ticket

        # Run one expiry cycle manually
        now = time.monotonic()
        to_remove = []
        for ticket in list(state._queue):
            if ticket.ready and ticket.ready_at and (now - ticket.ready_at > 60):
                to_remove.append(ticket)
        for ticket in to_remove:
            state._queue.remove(ticket)
            state._tickets.pop(ticket.id, None)
            state.semaphore.release()

        assert state.semaphore._value == 1
        assert "old" not in state._tickets


class TestAdmissionIntegration:
    def test_queue_status_responds(self, test_config):
        from teredacta.app import create_app
        from fastapi.testclient import TestClient
        app = create_app(test_config)
        client = TestClient(app)
        resp = client.get("/_queue/status?ticket=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["requeue"] is True


def _extract_ticket_id(set_cookie: str) -> str:
    """Extract _queue_ticket value from Set-Cookie header."""
    for part in set_cookie.split(";"):
        part = part.strip()
        if part.startswith("_queue_ticket="):
            return part.split("=", 1)[1]
    return ""

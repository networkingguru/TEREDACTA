"""Adversarial + user-focused tests for SSE non-blocking fix.

The bug: SSEManager._poll_loop() called synchronous DB queries directly
in the async event loop, blocking ALL request handling every poll cycle.

Fix: run_in_executor() offloads blocking calls to a thread pool.
"""
import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from teredacta.sse import SSEManager


# --- Adversarial: prove the event loop isn't blocked ---


@pytest.mark.asyncio
async def test_slow_unob_does_not_block_event_loop():
    """If get_stats() takes 500ms, other coroutines must still run freely."""
    unob = MagicMock()

    def slow_stats():
        time.sleep(0.5)  # Simulate slow DB
        return {"total_documents": 1}

    unob.get_stats.side_effect = slow_stats
    unob.get_daemon_status.return_value = "running"

    manager = SSEManager(poll_interval=0.1, unob=unob)
    queue = manager.subscribe()

    # While the poll loop is running (with its slow call), a simple
    # coroutine should complete in <100ms, not be blocked for 500ms.
    t0 = time.monotonic()
    await asyncio.sleep(0.05)
    elapsed = time.monotonic() - t0

    # If the event loop were blocked, this sleep would take ~500ms+
    assert elapsed < 0.3, f"Event loop was blocked for {elapsed:.2f}s"

    manager.unsubscribe(queue)
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_poll_loop_still_delivers_events_via_executor():
    """Despite running in executor, events still reach subscribers."""
    unob = MagicMock()
    unob.get_stats.return_value = {"docs": 42}
    unob.get_daemon_status.return_value = "stopped"

    manager = SSEManager(poll_interval=0.1, unob=unob)
    queue = manager.subscribe()

    # Wait for at least one poll cycle to deliver data
    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert "42" in event
    assert "stopped" in event

    manager.unsubscribe(queue)
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_executor_exception_does_not_crash_poll_loop():
    """If the DB throws, the poll loop keeps going (no crash, no hang)."""
    unob = MagicMock()
    call_count = 0

    def flaky_stats():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise sqlite3_OperationalError("database is locked")
        return {"docs": 1}

    unob.get_stats.side_effect = flaky_stats
    unob.get_daemon_status.return_value = "stopped"

    manager = SSEManager(poll_interval=0.1, unob=unob)
    queue = manager.subscribe()

    # Wait enough time for several poll cycles
    await asyncio.sleep(0.5)

    # Should have recovered and delivered at least one event
    assert not queue.empty(), "No events delivered after transient errors"

    manager.unsubscribe(queue)
    await asyncio.sleep(0.1)


# Simulate the sqlite3 error without importing it at module level
class sqlite3_OperationalError(Exception):
    pass


@pytest.mark.asyncio
async def test_concurrent_requests_not_serialized_by_polling():
    """Multiple concurrent coroutines should all complete quickly,
    even if the poll loop's blocking call is slow."""
    unob = MagicMock()

    def very_slow_stats():
        time.sleep(1.0)
        return {"docs": 0}

    unob.get_stats.side_effect = very_slow_stats
    unob.get_daemon_status.return_value = "stopped"

    manager = SSEManager(poll_interval=0.1, unob=unob)
    queue = manager.subscribe()

    # Simulate 5 concurrent "requests" (coroutines)
    async def fake_request(i):
        t0 = time.monotonic()
        await asyncio.sleep(0.05)
        return time.monotonic() - t0

    t0 = time.monotonic()
    results = await asyncio.gather(*[fake_request(i) for i in range(5)])
    total = time.monotonic() - t0

    # All 5 should complete in ~50ms, not 5*1s
    assert total < 0.5, f"Concurrent requests took {total:.2f}s (should be <0.5s)"
    for i, elapsed in enumerate(results):
        assert elapsed < 0.3, f"Request {i} took {elapsed:.2f}s"

    manager.unsubscribe(queue)
    await asyncio.sleep(0.1)


# --- User-focused: real SSE behavior with mock DB ---


@pytest.mark.asyncio
async def test_sse_event_generator_delivers_initial_state(test_config, mock_db):
    """When a user opens the dashboard, they should get current stats immediately."""
    from teredacta.unob import UnobInterface
    unob = UnobInterface(test_config)

    manager = SSEManager(poll_interval=0.1, unob=unob)
    queue = manager.subscribe()

    # Wait for first poll to populate _last_stats
    await asyncio.wait_for(queue.get(), timeout=2.0)

    # New subscriber should get cached state via event_generator
    queue2 = manager.subscribe()
    gen = manager.event_generator(queue2)
    first_event = await gen.__anext__()
    assert "total_documents" in first_event

    manager.unsubscribe(queue)
    manager.unsubscribe(queue2)
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_sse_stats_update_when_data_changes(test_config, mock_db):
    """When documents are added, SSE should push updated stats."""
    import sqlite3
    from teredacta.unob import UnobInterface

    unob = UnobInterface(test_config)
    manager = SSEManager(poll_interval=0.1, unob=unob)
    queue = manager.subscribe()

    # Get initial stats (0 documents)
    event1 = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert '"total_documents": 0' in event1

    # Add a document to the DB
    conn = sqlite3.connect(str(mock_db))
    conn.execute(
        "INSERT INTO documents (id, source) VALUES ('doc1', 'test')"
    )
    conn.commit()
    conn.close()

    # Clear stats cache so SSE picks up the change immediately
    unob._stats_cache = None

    # Next event should show 1 document
    event2 = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert '"total_documents": 1' in event2

    manager.unsubscribe(queue)
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_no_duplicate_events_when_data_unchanged(test_config, mock_db):
    """If nothing changes, SSE should NOT push duplicate events."""
    from teredacta.unob import UnobInterface

    unob = UnobInterface(test_config)
    manager = SSEManager(poll_interval=0.1, unob=unob)
    queue = manager.subscribe()

    # Get the first event
    await asyncio.wait_for(queue.get(), timeout=2.0)

    # Wait several poll cycles
    await asyncio.sleep(0.5)

    # Queue should be empty — no duplicate pushes
    assert queue.empty(), "Duplicate events sent when data didn't change"

    manager.unsubscribe(queue)
    await asyncio.sleep(0.1)

"""Stress tests for SSE connection saturation and cleanup."""

import asyncio

import pytest

from teredacta.sse import SSEManager


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestSSESaturation:
    """All tests are async because SSEManager.subscribe() calls asyncio.create_task()."""

    @pytest.mark.asyncio
    async def test_200_subscribers_no_leak(self):
        """Open 200 subscribers, unsubscribe all, verify cleanup."""
        sse = SSEManager(poll_interval=1.0, unob=None)
        queues = [sse.subscribe() for _ in range(200)]
        assert sse.subscriber_count == 200

        for q in queues:
            sse.unsubscribe(q)
        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_ungraceful_disconnect_cleanup_via_poll_loop(self):
        """Abandoned queues are cleaned up by the real _poll_loop broadcast."""
        from unittest.mock import MagicMock

        # Create a mock unob that returns changing stats each call
        mock_unob = MagicMock()
        call_count = 0
        def changing_stats():
            nonlocal call_count
            call_count += 1
            return {"total_documents": call_count}
        def changing_daemon():
            return "running"
        mock_unob.get_stats = changing_stats
        mock_unob.get_daemon_status = changing_daemon

        sse = SSEManager(poll_interval=0.01, unob=mock_unob)

        # Subscribe 10 queues — 5 active (we drain), 5 abandoned
        active_queues = []
        abandoned_queues = []
        for i in range(10):
            q = sse.subscribe()
            if i < 5:
                active_queues.append(q)
            else:
                abandoned_queues.append(q)

        assert sse.subscriber_count == 10

        # Let the real poll loop run and broadcast events.
        # Drain active queues aggressively so they don't fill up.
        # Abandoned queues will fill (maxsize=100) and get evicted.
        for _ in range(150):
            await asyncio.sleep(0.02)
            # Drain ALL pending items from active queues
            for q in active_queues:
                while not q.empty():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        break

        # Abandoned queues should have been evicted by _poll_loop
        assert sse.subscriber_count == 5

        for q in active_queues:
            sse.unsubscribe(q)
        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_rapid_connect_disconnect_cycle(self):
        """1000 rapid subscribe/unsubscribe cycles with no resource leak."""
        sse = SSEManager(poll_interval=1.0, unob=None)

        for _ in range(1000):
            q = sse.subscribe()
            sse.unsubscribe(q)

        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_subscribe_without_iterating_persists(self):
        """A queue subscribed but never iterated persists until QueueFull.

        This documents the known behavior: if subscribe() is called
        but the StreamingResponse generator never starts, the queue
        stays in _subscribers until broadcasts fill it to capacity (100).
        """
        sse = SSEManager(poll_interval=1.0, unob=None)
        orphan = sse.subscribe()

        # The orphan queue exists
        assert sse.subscriber_count == 1

        # Fill to capacity (maxsize=100). subscribe() doesn't put
        # anything in the queue, so we need 100 puts to fill it.
        for i in range(100):
            orphan.put_nowait(f"data: {i}\n\n")

        # Still there (full but not yet evicted — eviction happens on next broadcast)
        assert sse.subscriber_count == 1

        # One more triggers QueueFull — simulating what _poll_loop does
        dead = []
        try:
            orphan.put_nowait("data: overflow\n\n")
        except asyncio.QueueFull:
            dead.append(orphan)
        for q in dead:
            sse._subscribers.discard(q)

        assert sse.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_subscribe_unsubscribe(self):
        """Concurrent async subscribe/unsubscribe is safe."""
        sse = SSEManager(poll_interval=1.0, unob=None)

        async def churn(n):
            for _ in range(n):
                q = sse.subscribe()
                await asyncio.sleep(0)  # yield to other tasks
                sse.unsubscribe(q)

        await asyncio.gather(*[churn(100) for _ in range(10)])
        assert sse.subscriber_count == 0

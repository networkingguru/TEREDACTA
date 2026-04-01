import asyncio
import json
import logging
from functools import partial
from typing import AsyncGenerator, Optional, Set
from teredacta.unob import UnobInterface

logger = logging.getLogger(__name__)


class SSEManager:
    def __init__(self, poll_interval: float = 2.0, unob: Optional[UnobInterface] = None):
        self.poll_interval = poll_interval
        self.unob = unob
        self._subscribers: Set[asyncio.Queue] = set()
        self._task: Optional[asyncio.Task] = None
        self._last_stats: Optional[dict] = None

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll_loop())
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        self._subscribers.discard(queue)
        if not self._subscribers and self._task and not self._task.done():
            self._task.cancel()

    @staticmethod
    def _fetch_sync(unob: UnobInterface) -> dict:
        """Run blocking DB/process calls in a thread."""
        return {
            "stats": unob.get_stats(),
            "daemon": unob.get_daemon_status(),
        }

    async def _poll_loop(self):
        loop = asyncio.get_running_loop()
        try:
            while self._subscribers:
                if self.unob:
                    try:
                        data = await loop.run_in_executor(
                            None, partial(self._fetch_sync, self.unob)
                        )
                        if data != self._last_stats:
                            self._last_stats = data
                            event = f"data: {json.dumps(data)}\n\n"
                            dead_queues = []
                            for q in list(self._subscribers):
                                try:
                                    q.put_nowait(event)
                                except asyncio.QueueFull:
                                    dead_queues.append(q)
                            for q in dead_queues:
                                self._subscribers.discard(q)
                    except Exception:
                        logger.exception("SSE poll error")
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            pass

    async def event_generator(self, queue: asyncio.Queue) -> AsyncGenerator[str, None]:
        try:
            if self._last_stats:
                yield f"data: {json.dumps(self._last_stats)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield event
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            self.unsubscribe(queue)

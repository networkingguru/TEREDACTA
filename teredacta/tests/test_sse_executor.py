"""Tests for SSE dedicated thread pool executor."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
from teredacta.sse import SSEManager


@pytest.mark.asyncio
async def test_sse_manager_has_own_executor():
    manager = SSEManager(poll_interval=1.0)
    assert hasattr(manager, "executor")
    assert isinstance(manager.executor, ThreadPoolExecutor)
    manager.close()


@pytest.mark.asyncio
async def test_sse_close_shuts_down_executor():
    from concurrent.futures import BrokenExecutor
    manager = SSEManager(poll_interval=1.0)
    executor = manager.executor
    manager.close()
    with pytest.raises((RuntimeError, BrokenExecutor)):
        executor.submit(lambda: None)

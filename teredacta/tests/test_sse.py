import asyncio
import pytest
from teredacta.sse import SSEManager


@pytest.mark.asyncio
async def test_sse_subscribe_unsubscribe():
    manager = SSEManager(poll_interval=0.1)
    gen = manager.subscribe()
    assert gen is not None
    manager.unsubscribe(gen)


@pytest.mark.asyncio
async def test_sse_polling_starts_on_subscribe(test_config, mock_db):
    from teredacta.unob import UnobInterface
    unob = UnobInterface(test_config)
    manager = SSEManager(poll_interval=0.1, unob=unob)
    gen = manager.subscribe()
    assert manager._task is not None
    manager.unsubscribe(gen)
    await asyncio.sleep(0.2)

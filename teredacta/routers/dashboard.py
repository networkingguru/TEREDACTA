import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.responses import StreamingResponse

sse_router = APIRouter()


@sse_router.get("/sse/stats")
async def sse_stats(request: Request):
    sse = getattr(request.app.state, "sse", None)
    if sse is None:
        return HTMLResponse("SSE not configured", status_code=503)
    queue = sse.subscribe()
    return StreamingResponse(
        sse.event_generator(queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@sse_router.get("/sse/daemon-status", response_class=HTMLResponse)
async def daemon_status_fragment(request: Request):
    unob = request.app.state.unob
    loop = asyncio.get_running_loop()
    try:
        status = await loop.run_in_executor(None, unob.get_daemon_status)
    except Exception:
        status = "unknown"
    dot_class = "running" if status == "running" else "stopped"
    return HTMLResponse(
        f'<span class="status-dot {dot_class}"></span> {status.upper()}'
    )

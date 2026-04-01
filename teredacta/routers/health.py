"""Health check endpoints for liveness and readiness probes."""

import asyncio
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/live")
async def liveness():
    return {"status": "ok"}


@router.get("/ready")
async def readiness(request: Request):
    try:
        result = await asyncio.wait_for(_readiness_checks(request), timeout=1.0)
        return result
    except asyncio.TimeoutError:
        return JSONResponse({"status": "unhealthy"}, status_code=503)


async def _readiness_checks(request: Request) -> JSONResponse:
    config = request.app.state.config
    unob = request.app.state.unob
    sse = getattr(request.app.state, "sse", None)
    client_host = getattr(request.client, "host", None) if request.client else None
    is_local = client_host in ("127.0.0.1", "localhost", "::1", "testclient")
    is_admin = getattr(request.state, "is_admin", False)
    show_details = is_local or is_admin

    pool_data = unob.pool_status()
    if pool_data is None:
        pool_check = {"status": "ok", "idle": 0, "in_use": 0, "capacity": 0}
    else:
        available = pool_data["capacity"] - pool_data["in_use"]
        if available >= config.health_pool_degraded_threshold:
            pool_status = "ok"
        elif available >= 1:
            pool_status = "degraded"
        else:
            pool_status = "error"
        pool_check = {"status": pool_status, **pool_data}

    sub_count = sse.subscriber_count if sse else 0
    sse_degraded = config.health_sse_degraded_threshold
    sse_unhealthy = sse_degraded * 5
    if sub_count >= sse_unhealthy:
        sse_status = "error"
    elif sub_count >= sse_degraded:
        sse_status = "degraded"
    else:
        sse_status = "ok"
    sse_check = {"status": sse_status, "subscribers": sub_count}

    statuses = [pool_check["status"], sse_check["status"]]
    if "error" in statuses:
        overall = "unhealthy"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    status_code = 503 if overall == "unhealthy" else 200

    if show_details:
        body = {
            "status": overall,
            "worker_pid": os.getpid(),
            "checks": {
                "db_pool": pool_check,
                "sse": sse_check,
                "uptime_seconds": round(time.monotonic() - request.app.state.startup_time, 1),
            },
        }
    else:
        body = {"status": overall}

    return JSONResponse(body, status_code=status_code)

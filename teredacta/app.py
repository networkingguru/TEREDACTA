from contextlib import asynccontextmanager
from pathlib import Path
import logging
import time
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

logger = logging.getLogger(__name__)


class _HealthLogFilter(logging.Filter):
    """Suppress access log entries for /health/* requests."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if " /health/" in msg:
            return False
        return True


from teredacta.auth import AuthManager
from teredacta.config import TeredactaConfig
from teredacta.entity_index import EntityIndex
from teredacta.unob import UnobInterface


class _TemplateContextMiddleware:
    """Pure ASGI middleware — sets request state without wrapping response.

    Unlike BaseHTTPMiddleware (used by @app.middleware("http")), this is
    safe with streaming responses (SSE) because it passes through without
    intercepting the response stream.
    """

    def __init__(self, app, config=None, auth=None):
        self.app = app
        self.config = config
        self.auth = auth

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope)
            request.state.is_admin = self.auth.is_admin(request)
            request.state.csrf_token = self.auth.get_csrf_token(request)
            request.state.config = self.config
        await self.app(scope, receive, send)


def create_app(config: TeredactaConfig) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        application.state.unob.close()
        if hasattr(application.state, "sse"):
            application.state.sse.close()

    _access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _HealthLogFilter) for f in _access_logger.filters):
        _access_logger.addFilter(_HealthLogFilter())

    fastapi_app = FastAPI(title="TEREDACTA", docs_url=None, redoc_url=None, lifespan=lifespan)
    fastapi_app.state.config = config
    fastapi_app.state.unob = UnobInterface(config)
    fastapi_app.state.unob.ensure_indexes()
    fastapi_app.state.auth = AuthManager(config)
    fastapi_app.state.entity_index = EntityIndex(config.entity_db_path)

    from teredacta.sse import SSEManager
    fastapi_app.state.sse = SSEManager(poll_interval=config.sse_poll_interval_seconds, unob=fastapi_app.state.unob, max_subscribers=config.max_sse_subscribers)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        fastapi_app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    template_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(template_dir))
    fastapi_app.state.templates = templates

    fastapi_app.add_middleware(_TemplateContextMiddleware, config=config, auth=fastapi_app.state.auth)

    from teredacta.routers import dashboard, documents, groups, recoveries, pdf, queue, summary, admin, explore, highlights, api, health

    # SSE at root (admin-only, guarded in dashboard.py)
    fastapi_app.include_router(dashboard.sse_router)
    fastapi_app.include_router(health.router, prefix="/health")
    fastapi_app.state.startup_time = time.monotonic()

    # API endpoints (HTML fragments)
    fastapi_app.include_router(api.router, prefix="/api")

    # Public pages
    fastapi_app.include_router(explore.router)
    fastapi_app.include_router(highlights.router, prefix="/highlights")
    fastapi_app.include_router(documents.router, prefix="/documents")
    fastapi_app.include_router(recoveries.router, prefix="/recoveries")
    fastapi_app.include_router(pdf.router, prefix="/pdf")
    fastapi_app.include_router(summary.router, prefix="/summary")

    # Admin pages
    fastapi_app.include_router(admin.router, prefix="/admin")
    fastapi_app.include_router(groups.router, prefix="/admin/groups")
    fastapi_app.include_router(queue.router, prefix="/admin/queue")

    # Redirects for old URLs
    @fastapi_app.get("/groups/{path:path}")
    def redirect_groups(path: str):
        return RedirectResponse(f"/admin/groups/{path}", status_code=301)

    @fastapi_app.get("/queue/{path:path}")
    def redirect_queue(path: str):
        return RedirectResponse(f"/admin/queue/{path}", status_code=301)

    @fastapi_app.exception_handler(FileNotFoundError)
    async def db_not_found_handler(request: Request, exc: FileNotFoundError):
        logger.error("FileNotFoundError: %s", exc)
        return templates.TemplateResponse(
            request,
            "error.html",
            {"error": "Database not found. Check your configuration.", "is_admin": False, "csrf_token": ""},
            status_code=503,
        )

    from teredacta.timeout_middleware import RequestTimeoutMiddleware
    fastapi_app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=120.0)

    from teredacta.admission import AdmissionMiddleware
    app = AdmissionMiddleware(
        fastapi_app,
        max_concurrent=config.max_concurrent_requests,
        max_queue=config.max_queue_size,
    )

    return app

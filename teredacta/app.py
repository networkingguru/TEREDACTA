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

def create_app(config: TeredactaConfig) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        yield
        application.state.unob.close()

    _access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _HealthLogFilter) for f in _access_logger.filters):
        _access_logger.addFilter(_HealthLogFilter())

    app = FastAPI(title="TEREDACTA", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.config = config
    app.state.unob = UnobInterface(config)
    app.state.unob.ensure_indexes()
    app.state.auth = AuthManager(config)
    app.state.entity_index = EntityIndex(config.entity_db_path)

    from teredacta.sse import SSEManager
    app.state.sse = SSEManager(poll_interval=config.sse_poll_interval_seconds, unob=app.state.unob, max_subscribers=config.max_sse_subscribers)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    template_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(template_dir))
    app.state.templates = templates

    @app.middleware("http")
    async def add_template_context(request: Request, call_next):
        request.state.is_admin = app.state.auth.is_admin(request)
        request.state.csrf_token = app.state.auth.get_csrf_token(request)
        request.state.config = config
        response = await call_next(request)
        return response

    from teredacta.routers import dashboard, documents, groups, recoveries, pdf, queue, summary, admin, explore, highlights, api, health

    # SSE at root (admin-only, guarded in dashboard.py)
    app.include_router(dashboard.sse_router)
    app.include_router(health.router, prefix="/health")
    app.state.startup_time = time.monotonic()

    # API endpoints (HTML fragments)
    app.include_router(api.router, prefix="/api")

    # Public pages
    app.include_router(explore.router)
    app.include_router(highlights.router, prefix="/highlights")
    app.include_router(documents.router, prefix="/documents")
    app.include_router(recoveries.router, prefix="/recoveries")
    app.include_router(pdf.router, prefix="/pdf")
    app.include_router(summary.router, prefix="/summary")

    # Admin pages
    app.include_router(admin.router, prefix="/admin")
    app.include_router(groups.router, prefix="/admin/groups")
    app.include_router(queue.router, prefix="/admin/queue")

    # Redirects for old URLs
    @app.get("/groups/{path:path}")
    def redirect_groups(path: str):
        return RedirectResponse(f"/admin/groups/{path}", status_code=301)

    @app.get("/queue/{path:path}")
    def redirect_queue(path: str):
        return RedirectResponse(f"/admin/queue/{path}", status_code=301)

    @app.exception_handler(FileNotFoundError)
    async def db_not_found_handler(request: Request, exc: FileNotFoundError):
        logger.error("FileNotFoundError: %s", exc)
        return templates.TemplateResponse(
            request,
            "error.html",
            {"error": "Database not found. Check your configuration.", "is_admin": False, "csrf_token": ""},
            status_code=503,
        )

    from teredacta.timeout_middleware import RequestTimeoutMiddleware
    app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=120.0)

    return app

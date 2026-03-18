from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse
from teredacta.auth import AuthManager
from teredacta.config import TeredactaConfig
from teredacta.unob import UnobInterface

def create_app(config: TeredactaConfig) -> FastAPI:
    app = FastAPI(title="TEREDACTA", docs_url=None, redoc_url=None)
    app.state.config = config
    app.state.unob = UnobInterface(config)
    app.state.unob.ensure_indexes()
    app.state.auth = AuthManager(config)

    from teredacta.sse import SSEManager
    app.state.sse = SSEManager(poll_interval=config.sse_poll_interval_seconds, unob=app.state.unob)

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

    from teredacta.routers import dashboard, documents, groups, recoveries, pdf, queue, summary, admin
    app.include_router(dashboard.router)
    app.include_router(documents.router, prefix="/documents")
    app.include_router(groups.router, prefix="/groups")
    app.include_router(recoveries.router, prefix="/recoveries")
    app.include_router(pdf.router, prefix="/pdf")
    app.include_router(queue.router, prefix="/queue")
    app.include_router(summary.router, prefix="/summary")
    app.include_router(admin.router, prefix="/admin")

    @app.exception_handler(FileNotFoundError)
    async def db_not_found_handler(request: Request, exc: FileNotFoundError):
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": str(exc), "is_admin": False, "csrf_token": ""},
            status_code=503,
        )

    return app

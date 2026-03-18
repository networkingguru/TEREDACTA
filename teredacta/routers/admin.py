import shutil
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response, StreamingResponse

router = APIRouter()

def _require_admin(request: Request):
    if not getattr(request.state, "is_admin", False):
        return False
    return True

def _ctx(request: Request, **extra):
    return {
        "request": request,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        **extra,
    }

@router.get("/", response_class=HTMLResponse)
async def admin_page(request: Request):
    templates = request.app.state.templates
    config = request.app.state.config
    is_admin = getattr(request.state, "is_admin", False)
    if config.admin_requires_login and not is_admin:
        return templates.TemplateResponse("admin/login.html", _ctx(request, error=None))
    if not config.admin_enabled:
        return templates.TemplateResponse("error.html", _ctx(request, error="Admin features are disabled. Set an admin password to enable."), status_code=403)
    return templates.TemplateResponse("admin/dashboard.html", _ctx(request))

@router.post("/login")
async def login(request: Request):
    form = await request.form()
    password = form.get("password", "")
    config = request.app.state.config
    auth = request.app.state.auth
    if config.check_password(password):
        response = RedirectResponse("/admin", status_code=303)
        auth.create_session(response)
        return response
    templates = request.app.state.templates
    return templates.TemplateResponse("admin/login.html", _ctx(request, error="Invalid password"), status_code=401)

@router.post("/logout")
async def logout(request: Request):
    auth = request.app.state.auth
    response = RedirectResponse("/", status_code=303)
    auth.clear_session(response)
    return response

# --- Daemon Control ---

@router.post("/daemon/start")
async def daemon_start(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    unob = request.app.state.unob
    result = unob.start_daemon()
    msg = result.get("stdout", "") or result.get("error", "Unknown")
    return HTMLResponse(f"<span>{ msg }</span>")

@router.post("/daemon/stop")
async def daemon_stop(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    unob = request.app.state.unob
    result = unob.stop_daemon()
    msg = result.get("stdout", "") or result.get("error", "Unknown")
    return HTMLResponse(f"<span>{ msg }</span>")

@router.post("/daemon/restart")
async def daemon_restart(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    unob = request.app.state.unob
    result = unob.restart_daemon()
    msg = result.get("stdout", "") or result.get("error", "Unknown")
    return HTMLResponse(f"<span>{ msg }</span>")

@router.get("/daemon/status")
async def daemon_status(request: Request):
    unob = request.app.state.unob
    status = unob.get_daemon_status()
    return HTMLResponse(f"<span>{status}</span>")

# --- Config ---

@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    templates = request.app.state.templates
    config = request.app.state.config
    return templates.TemplateResponse("admin/config.html", _ctx(request, config=config))

@router.post("/config")
async def save_config(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    # Config editing via subprocess
    form = await request.form()
    unob = request.app.state.unob
    results = []
    for key in ("workers", "similarity_threshold", "poll_interval", "redaction_markers"):
        value = form.get(key)
        if value:
            result = unob.run_command(["config", "set", key, value])
            results.append(f"{key}: {'OK' if result['success'] else result.get('error', 'Failed')}")
    return HTMLResponse("<br>".join(results) if results else "No changes")

# --- Logs ---

@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    templates = request.app.state.templates
    unob = request.app.state.unob
    lines = unob.read_log_lines(n=100)
    return templates.TemplateResponse("admin/logs.html", _ctx(request, lines=lines))

@router.get("/logs/tail", response_class=HTMLResponse)
async def logs_tail(request: Request, level: str = Query(None), n: int = Query(100)):
    if not _require_admin(request):
        return Response(status_code=403)
    unob = request.app.state.unob
    lines = unob.read_log_lines(n=n, level=level)
    return HTMLResponse("\n".join(lines))

# --- Search ---

@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    templates = request.app.state.templates
    return templates.TemplateResponse("admin/search.html", _ctx(request, result=None))

@router.post("/search")
async def search_submit(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    form = await request.form()
    unob = request.app.state.unob
    result = unob.search(
        person=form.get("person", ""),
        batch=form.get("batch", ""),
        doc_id=form.get("doc_id", ""),
        query=form.get("query", ""),
    )
    templates = request.app.state.templates
    if request.headers.get("HX-Request"):
        status = "Success" if result["success"] else "Failed"
        output = result.get("stdout", "") or result.get("error", "")
        return HTMLResponse(f"<div><strong>{status}</strong><pre>{output}</pre></div>")
    return templates.TemplateResponse("admin/search.html", _ctx(request, result=result))

# --- Downloads ---

@router.get("/downloads", response_class=HTMLResponse)
async def downloads_page(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    templates = request.app.state.templates
    unob = request.app.state.unob
    disk = _get_disk_space(unob)
    return templates.TemplateResponse("admin/downloads.html", _ctx(request, disk=disk))

@router.post("/downloads/start")
async def start_download(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    form = await request.form()
    batch = form.get("batch_id", "")
    unob = request.app.state.unob
    result = unob.run_command(["download", "--batch", batch])
    msg = "Download started" if result["success"] else result.get("error", "Failed")
    return HTMLResponse(f"<span>{msg}</span>")

def _get_disk_space(unob):
    try:
        usage = shutil.disk_usage(unob.config.output_dir)
        return {
            "total_gb": round(usage.total / (1024**3), 1),
            "used_gb": round(usage.used / (1024**3), 1),
            "free_gb": round(usage.free / (1024**3), 1),
            "percent_used": round(usage.used / usage.total * 100, 1),
        }
    except Exception:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent_used": 0}

import asyncio
import re
import shutil
from html import escape
from functools import partial
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

router = APIRouter()

def _require_admin(request: Request):
    if not getattr(request.state, "is_admin", False):
        return False
    return True

def _validate_csrf(request: Request) -> bool:
    """Validate CSRF token for state-mutating requests. Returns True if valid.
    Skips validation in local mode without login (no session exists)."""
    config = request.app.state.config
    if not config.admin_requires_login:
        return True
    auth = request.app.state.auth
    session = auth.validate_session(request)
    if not session:
        return False
    return auth.validate_csrf(request, session)

def _ctx(request: Request, **extra):
    return {
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        **extra,
    }

# Max length for config values to prevent abuse
_MAX_CONFIG_VALUE_LEN = 256

# Pattern for search form fields: alphanumeric, spaces, hyphens, underscores, dots
_SAFE_SEARCH_RE = re.compile(r'^[\w\s.\-]*$', re.UNICODE)

# Pattern for batch IDs: alphanumeric, hyphens, underscores
_BATCH_ID_RE = re.compile(r'^[A-Za-z0-9_\-]+$')

@router.get("/", response_class=HTMLResponse)
def admin_page(request: Request):
    templates = request.app.state.templates
    config = request.app.state.config
    is_admin = getattr(request.state, "is_admin", False)
    if config.admin_requires_login and not is_admin:
        return templates.TemplateResponse(request, "admin/login.html", _ctx(request, error=None))
    if not config.admin_enabled:
        return templates.TemplateResponse(request, "error.html", _ctx(request, error="Admin features are disabled. Set an admin password to enable."), status_code=403)
    return templates.TemplateResponse(request, "admin/dashboard.html", _ctx(request))

@router.get("/stats-fragment", response_class=HTMLResponse)
async def stats_fragment(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    templates = request.app.state.templates
    unob = request.app.state.unob
    loop = asyncio.get_running_loop()
    try:
        stats = await loop.run_in_executor(None, unob.get_stats)
    except FileNotFoundError:
        stats = {}
    return templates.TemplateResponse(request, "dashboard_stats.html", {
        "stats": stats,
    })

@router.post("/login")
async def login(request: Request):
    form = await request.form()
    password = form.get("password", "")
    config = request.app.state.config
    auth = request.app.state.auth
    loop = asyncio.get_running_loop()
    valid = await loop.run_in_executor(None, config.check_password, password)
    if valid:
        response = RedirectResponse("/admin", status_code=303)
        auth.create_session(response)
        return response
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "admin/login.html", _ctx(request, error="Invalid password"), status_code=401)

@router.post("/logout")
async def logout(request: Request):
    config = request.app.state.config
    if config.admin_requires_login and not _validate_csrf(request):
        return Response(status_code=403)
    auth = request.app.state.auth
    response = RedirectResponse("/", status_code=303)
    auth.clear_session(response)
    return response

# --- Daemon Control ---

@router.post("/daemon/start")
def daemon_start(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    if not _validate_csrf(request):
        return Response(status_code=403)
    unob = request.app.state.unob
    result = unob.start_daemon()
    msg = result.get("stdout", "") or result.get("error", "Unknown")
    return HTMLResponse(f"<span>{escape(msg)}</span>")

@router.post("/daemon/stop")
def daemon_stop(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    if not _validate_csrf(request):
        return Response(status_code=403)
    unob = request.app.state.unob
    result = unob.stop_daemon()
    msg = result.get("stdout", "") or result.get("error", "Unknown")
    return HTMLResponse(f"<span>{escape(msg)}</span>")

@router.post("/daemon/restart")
def daemon_restart(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    if not _validate_csrf(request):
        return Response(status_code=403)
    unob = request.app.state.unob
    result = unob.restart_daemon()
    msg = result.get("stdout", "") or result.get("error", "Unknown")
    return HTMLResponse(f"<span>{escape(msg)}</span>")

@router.get("/daemon/status")
def daemon_status(request: Request):
    unob = request.app.state.unob
    status = unob.get_daemon_status()
    return HTMLResponse(f"<span>{escape(status)}</span>")

# --- Config ---

@router.get("/config", response_class=HTMLResponse)
def config_page(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    templates = request.app.state.templates
    config = request.app.state.config
    return templates.TemplateResponse(request, "admin/config.html", _ctx(request, config=config))

@router.post("/config")
async def save_config(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    if not _validate_csrf(request):
        return Response(status_code=403)
    # Config editing via subprocess
    form = await request.form()
    unob = request.app.state.unob
    loop = asyncio.get_running_loop()
    results = []
    for key in ("workers", "similarity_threshold", "poll_interval", "redaction_markers"):
        value = form.get(key)
        if value:
            if len(value) > _MAX_CONFIG_VALUE_LEN:
                results.append(f"{escape(key)}: Value too long (max {_MAX_CONFIG_VALUE_LEN} chars)")
                continue
            result = await loop.run_in_executor(None, partial(unob.run_command, ["config", "set", key, value]))
            results.append(f"{escape(key)}: {'OK' if result['success'] else escape(result.get('error', 'Failed'))}")
    return HTMLResponse("<br>".join(results) if results else "No changes")

# --- Logs ---

@router.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    templates = request.app.state.templates
    unob = request.app.state.unob
    lines = unob.read_log_lines(n=100)
    return templates.TemplateResponse(request, "admin/logs.html", _ctx(request, lines=lines))

@router.get("/logs/tail", response_class=HTMLResponse)
def logs_tail(request: Request, level: str = Query(None), n: int = Query(100, ge=1, le=10000)):
    if not _require_admin(request):
        return Response(status_code=403)
    if level and level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = None
    unob = request.app.state.unob
    lines = unob.read_log_lines(n=n, level=level)
    return HTMLResponse("\n".join(escape(line) for line in lines))

# --- Search ---

@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "admin/search.html", _ctx(request, result=None))

@router.post("/search")
async def search_submit(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    if not _validate_csrf(request):
        return Response(status_code=403)
    form = await request.form()
    # Validate/sanitize search form values
    search_fields = {}
    for field in ("person", "batch", "doc_id", "query"):
        val = form.get(field, "")
        if val and not _SAFE_SEARCH_RE.match(val):
            return HTMLResponse(f"<div><strong>Error</strong><pre>Invalid characters in {escape(field)}</pre></div>", status_code=400)
        search_fields[field] = val
    unob = request.app.state.unob
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, partial(unob.search,
        person=search_fields["person"],
        batch=search_fields["batch"],
        doc_id=search_fields["doc_id"],
        query=search_fields["query"],
    ))
    templates = request.app.state.templates
    if request.headers.get("HX-Request"):
        status = "Success" if result["success"] else "Failed"
        output = result.get("stdout", "") or result.get("error", "")
        return HTMLResponse(f"<div><strong>{status}</strong><pre>{escape(output)}</pre></div>")
    return templates.TemplateResponse(request, "admin/search.html", _ctx(request, result=result))

# --- Downloads ---

@router.get("/downloads", response_class=HTMLResponse)
def downloads_page(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    templates = request.app.state.templates
    unob = request.app.state.unob
    disk = _get_disk_space(unob)
    return templates.TemplateResponse(request, "admin/downloads.html", _ctx(request, disk=disk))

@router.post("/downloads/start")
async def start_download(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    if not _validate_csrf(request):
        return Response(status_code=403)
    form = await request.form()
    batch = form.get("batch_id", "")
    # Validate batch_id is alphanumeric (with hyphens/underscores)
    if not batch or not _BATCH_ID_RE.match(batch):
        return HTMLResponse("<span>Invalid batch ID (must be alphanumeric, hyphens, underscores only)</span>", status_code=400)
    unob = request.app.state.unob
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, partial(unob.run_command, ["download", "--batch", batch]))
    msg = "Download started" if result["success"] else result.get("error", "Failed")
    return HTMLResponse(f"<span>{escape(msg)}</span>")

def _get_disk_space(unob):
    try:
        output_dir = unob.config.output_dir
        if not output_dir:
            return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent_used": 0}
        usage = shutil.disk_usage(output_dir)
        return {
            "total_gb": round(usage.total / (1024**3), 1),
            "used_gb": round(usage.used / (1024**3), 1),
            "free_gb": round(usage.free / (1024**3), 1),
            "percent_used": round(usage.used / usage.total * 100, 1),
        }
    except Exception:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent_used": 0}

# --- Entity Index ---

@router.post("/entity-index/build")
async def entity_index_build(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    if not _validate_csrf(request):
        return Response(status_code=403)
    entity_idx = request.app.state.entity_index
    unob = request.app.state.unob
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, partial(entity_idx.build, unob.config.db_path))
        return HTMLResponse(
            f'<span>Built: {escape(str(result["entities"]))} entities, '
            f'{escape(str(result["mentions"]))} mentions</span>'
        )
    except Exception as e:
        return HTMLResponse(f"<span>Error: {escape(str(e))}</span>", status_code=500)

@router.get("/entity-index/status", response_class=HTMLResponse)
def entity_index_status(request: Request):
    if not _require_admin(request):
        return Response(status_code=403)
    entity_idx = request.app.state.entity_index
    unob = request.app.state.unob
    status = entity_idx.get_status(unob.config.db_path)
    state = status["state"]
    if state == "not_built":
        return HTMLResponse('<span class="text-muted">Not built</span>')
    label = "Ready" if state == "ready" else "Stale — rebuild recommended"
    return HTMLResponse(
        f'<span>{escape(label)}: {status["entities"]} entities, '
        f'{status["mentions"]} mentions<br>'
        f'<small>Built: {escape(status["built_at"] or "never")}</small></span>'
    )

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def list_queue(
    request: Request,
    status: str = Query(None),
    page: int = Query(1, ge=1),
):
    if status and status not in ("pending", "running", "done", "failed"):
        status = None
    templates = request.app.state.templates
    unob = request.app.state.unob
    try:
        jobs = unob.get_jobs(status=status, page=page)
    except FileNotFoundError:
        jobs = []
    return templates.TemplateResponse(request, "queue/list.html", {
        "jobs": jobs, "status_filter": status or "",
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from starlette.responses import Response

from teredacta.unob import calc_total_pages

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def list_groups(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
):
    templates = request.app.state.templates
    unob = request.app.state.unob
    try:
        groups, total = unob.get_match_groups(page=page, per_page=per_page)
    except FileNotFoundError:
        groups, total = [], 0
    total_pages = calc_total_pages(total, per_page)
    return templates.TemplateResponse("groups/list.html", {
        "request": request, "groups": groups,
        "total": total, "page": page, "per_page": per_page,
        "total_pages": total_pages,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })

@router.get("/{group_id:int}", response_class=HTMLResponse)
async def group_detail(request: Request, group_id: int):
    templates = request.app.state.templates
    unob = request.app.state.unob
    detail = unob.get_match_group_detail(group_id)
    if detail is None:
        return Response(status_code=404)
    return templates.TemplateResponse("groups/detail.html", {
        "request": request, "group": detail,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })

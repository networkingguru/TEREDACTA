from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from starlette.responses import Response

from teredacta.unob import calc_total_pages

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def list_recoveries(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
):
    templates = request.app.state.templates
    unob = request.app.state.unob
    try:
        recoveries, total = unob.get_recoveries(search=search, page=page, per_page=per_page)
    except FileNotFoundError:
        recoveries, total = [], 0
    total_pages = calc_total_pages(total, per_page)
    ctx = {
        "request": request, "recoveries": recoveries,
        "search": search or "",
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("recoveries/table.html", ctx)
    return templates.TemplateResponse("recoveries/list.html", ctx)

@router.get("/common", response_class=HTMLResponse)
def common_unredactions(request: Request):
    """Lazy-loaded endpoint for the common unredactions panel."""
    templates = request.app.state.templates
    unob = request.app.state.unob
    try:
        common = unob.get_common_unredactions(min_occurrences=2, min_words=3, limit=20)
    except FileNotFoundError:
        common = []
    if not common:
        return HTMLResponse("")
    return templates.TemplateResponse("recoveries/common_panel.html", {
        "request": request, "common": common,
    })

@router.get("/{group_id:int}", response_class=HTMLResponse)
def recovery_detail(request: Request, group_id: int):
    templates = request.app.state.templates
    unob = request.app.state.unob
    detail = unob.get_recovery_detail(group_id)
    if detail is None:
        return Response(status_code=404)
    return templates.TemplateResponse("recoveries/detail.html", {
        "request": request, "recovery": detail, "group_id": group_id,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })

@router.get("/{group_id:int}/source", response_class=HTMLResponse)
def source_panel(request: Request, group_id: int, segment_index: int = Query(..., ge=0)):
    templates = request.app.state.templates
    unob = request.app.state.unob
    ctx = unob.get_source_context(group_id, segment_index)
    if ctx is None:
        return Response(status_code=404)
    return templates.TemplateResponse("recoveries/source_panel.html", {
        "request": request,
        "group_id": group_id,
        "segment_index": segment_index,
        **ctx,
    })

@router.get("/{group_id:int}/tab/{tab_name}", response_class=HTMLResponse)
def recovery_tab(request: Request, group_id: int, tab_name: str):
    templates = request.app.state.templates
    unob = request.app.state.unob
    detail = unob.get_recovery_detail(group_id)
    if detail is None:
        return Response(status_code=404)
    tab_map = {
        "merged-text": "recoveries/tabs/merged_text.html",
        "output-pdf": "recoveries/tabs/output_pdf.html",
        "original-pdfs": "recoveries/tabs/original_pdfs.html",
        "metadata": "recoveries/tabs/metadata.html",
    }
    template = tab_map.get(tab_name)
    if not template:
        return Response(status_code=404)
    return templates.TemplateResponse(template, {
        "request": request, "recovery": detail, "group_id": group_id,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })

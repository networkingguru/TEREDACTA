from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

from teredacta.unob import calc_total_pages

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def list_recoveries(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    sort: str = Query(None),
):
    templates = request.app.state.templates
    unob = request.app.state.unob
    try:
        recoveries, total = unob.get_recoveries(search=search, page=page, per_page=per_page, sort=sort)
    except FileNotFoundError:
        recoveries, total = [], 0
    total_pages = calc_total_pages(total, per_page)
    ctx = {
        "recoveries": recoveries,
        "search": search or "",
        "sort": sort or "",
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "recoveries/table.html", ctx)
    return templates.TemplateResponse(request, "recoveries/list.html", ctx)

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
    return templates.TemplateResponse(request, "recoveries/common_panel.html", {
        "common": common,
    })

@router.get("/{group_id:int}", response_class=HTMLResponse)
def recovery_detail(request: Request, group_id: int):
    templates = request.app.state.templates
    unob = request.app.state.unob
    detail = unob.get_recovery_detail(group_id)
    if detail is None:
        # Stale deeplink (README, social cards, external posts) — group_ids
        # shift when the matcher/merger algorithm regenerates. Redirect to
        # the current featured recovery so external links keep landing on
        # meaningful content instead of a 404.
        featured = unob.get_featured_recovery(None)
        if featured and featured["group_id"] != group_id:
            return RedirectResponse(
                url=f"/recoveries/{featured['group_id']}",
                status_code=302,
            )
        return Response(status_code=404)
    return templates.TemplateResponse(request, "recoveries/detail.html", {
        "recovery": detail, "group_id": group_id,
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
    return templates.TemplateResponse(request, "recoveries/source_panel.html", {
        "group_id": group_id,
        "segment_index": segment_index,
        **ctx,
    })

@router.get("/{group_id:int}/member-text", response_class=HTMLResponse)
def member_text(request: Request, group_id: int, doc_id: str = Query(...)):
    unob = request.app.state.unob
    result = unob.get_member_text(group_id, doc_id)
    if result is None:
        return Response(status_code=404)
    # Return raw HTML fragment — the calling template already provides
    # the wrapping log-viewer div, so we don't add another one here.
    return HTMLResponse(result["text_html"])

@router.get("/{group_id:int}/tab/{tab_name}", response_class=HTMLResponse)
def recovery_tab(request: Request, group_id: int, tab_name: str):
    tab_map = {
        "merged-text": "recoveries/tabs/merged_text.html",
        "output-pdf": "recoveries/tabs/output_pdf.html",
        "original-pdfs": "recoveries/tabs/original_pdfs.html",
        "metadata": "recoveries/tabs/metadata.html",
    }
    template = tab_map.get(tab_name)
    if not template:
        return Response(status_code=404)
    templates = request.app.state.templates
    unob = request.app.state.unob
    detail = unob.get_recovery_detail(group_id)
    if detail is None:
        return Response(status_code=404)
    return templates.TemplateResponse(request, template, {
        "recovery": detail, "group_id": group_id,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })

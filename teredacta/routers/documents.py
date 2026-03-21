from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from starlette.responses import Response

from teredacta.unob import calc_total_pages

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def list_documents(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    search: str = Query(None),
    source: str = Query(None),
    batch: str = Query(None),
    has_redactions: bool = Query(None),
    stage: str = Query(None),
):
    templates = request.app.state.templates
    unob = request.app.state.unob
    try:
        docs, total = unob.get_documents(
            page=page, per_page=per_page, search=search,
            source=source, batch=batch, has_redactions=has_redactions, stage=stage,
        )
    except FileNotFoundError:
        docs, total = [], 0

    total_pages = calc_total_pages(total, per_page)
    ctx = {
        "request": request, "docs": docs, "total": total,
        "page": page, "per_page": per_page, "total_pages": total_pages,
        "search": search or "", "source": source or "", "batch": batch or "",
        "has_redactions": has_redactions, "stage": stage or "",
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    }

    # HTMX partial response
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("documents/table.html", ctx)
    return templates.TemplateResponse("documents/list.html", ctx)

@router.get("/{doc_id}", response_class=HTMLResponse)
def document_detail(request: Request, doc_id: str):
    templates = request.app.state.templates
    unob = request.app.state.unob
    doc = unob.get_document(doc_id)
    if doc is None:
        return Response(status_code=404)
    return templates.TemplateResponse("documents/detail.html", {
        "request": request, "doc": doc,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })

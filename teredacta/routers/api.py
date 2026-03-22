from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from starlette.responses import Response

router = APIRouter()


def _ctx(request: Request, **kwargs) -> dict:
    """Build standard template context."""
    ctx = {
        "request": request,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    }
    ctx.update(kwargs)
    return ctx


@router.get("/entities", response_class=HTMLResponse)
def entity_list(
    request: Request,
    entity_type: str = Query("", alias="type"),
    name_filter: str = Query("", alias="filter"),
    page: int = Query(1, ge=1),
):
    templates = request.app.state.templates
    entity_index = request.app.state.entity_index
    etype = entity_type if entity_type else None
    nfilter = name_filter if name_filter else None
    entities, total = entity_index.list_entities(
        entity_type=etype,
        name_filter=nfilter,
        page=page,
        per_page=50,
    )
    total_pages = max(1, (total + 49) // 50)
    return templates.TemplateResponse(
        "explore/entity_list.html",
        _ctx(request, entities=entities, total=total, page=page, total_pages=total_pages,
             current_type=entity_type, current_filter=name_filter),
    )


@router.get("/entities/{entity_id:int}/connections", response_class=HTMLResponse)
def entity_connections(request: Request, entity_id: int):
    templates = request.app.state.templates
    entity_index = request.app.state.entity_index
    connections = entity_index.get_connections(entity_id)
    if connections is None:
        return Response(status_code=404)
    return templates.TemplateResponse(
        "explore/connections.html",
        _ctx(request, **connections),
    )


@router.get("/preview/recovery/{group_id:int}", response_class=HTMLResponse)
def preview_recovery(request: Request, group_id: int):
    templates = request.app.state.templates
    unob = request.app.state.unob
    try:
        detail = unob.get_recovery_detail(group_id)
    except FileNotFoundError:
        detail = None
    if detail is None:
        return Response(status_code=404)
    # Extract a snippet from recovered segments
    snippet = ""
    if detail.get("recovered_segments"):
        for seg in detail["recovered_segments"]:
            text = seg.get("text", "") if isinstance(seg, dict) else str(seg)
            if text and len(text.strip()) > 10:
                snippet = text.strip()[:300]
                break
    return templates.TemplateResponse(
        "explore/preview.html",
        _ctx(request, recovery=detail, group_id=group_id, snippet=snippet),
    )


@router.get("/preview/document/{doc_id}", response_class=HTMLResponse)
def preview_document(request: Request, doc_id: str):
    templates = request.app.state.templates
    unob = request.app.state.unob
    try:
        doc = unob.get_document(doc_id)
    except FileNotFoundError:
        doc = None
    if doc is None:
        return Response(status_code=404)
    excerpt = ""
    if doc.get("extracted_text"):
        excerpt = doc["extracted_text"][:500]
    return templates.TemplateResponse(
        "explore/preview.html",
        _ctx(request, document=doc, doc_id=doc_id, excerpt=excerpt),
    )


@router.get("/preview/entity/{entity_id:int}", response_class=HTMLResponse)
def preview_entity(request: Request, entity_id: int):
    templates = request.app.state.templates
    entity_index = request.app.state.entity_index
    connections = entity_index.get_connections(entity_id)
    if connections is None:
        return Response(status_code=404)
    entity = connections["entity"]
    return templates.TemplateResponse(
        "explore/preview.html",
        _ctx(
            request,
            entity=entity,
            recovery_count=len(connections["recoveries"]),
            linked_count=len(connections["linked_entities"]),
            sample_context=connections["recoveries"][0]["context"][:200] if connections["recoveries"] else "",
        ),
    )

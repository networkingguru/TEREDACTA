import sqlite3

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from starlette.responses import Response

from teredacta.unob import calc_total_pages

router = APIRouter()


def _entity_doc_ids(entity_index, unob, search: str) -> set[str]:
    """Find doc_ids linked to entities matching *search*."""
    try:
        entities, _total = entity_index.list_entities(name_filter=search, per_page=50)
    except Exception:
        return set()
    if not entities:
        return set()

    # Collect group_ids from entity mentions
    from pathlib import Path
    db_path = Path(entity_index.db_path)
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        entity_ids = [e["id"] for e in entities]
        placeholders = ",".join("?" for _ in entity_ids)
        rows = conn.execute(
            f"SELECT DISTINCT group_id FROM entity_mentions WHERE entity_id IN ({placeholders})",
            entity_ids,
        ).fetchall()
        group_ids = [r["group_id"] for r in rows]
    finally:
        conn.close()

    if not group_ids:
        return set()

    # Get doc_ids from match_group_members in the Unobfuscator DB
    unob_conn = unob._get_db()
    try:
        placeholders = ",".join("?" for _ in group_ids)
        rows = unob_conn.execute(
            f"SELECT DISTINCT doc_id FROM match_group_members WHERE group_id IN ({placeholders})",
            group_ids,
        ).fetchall()
        return {r["doc_id"] for r in rows}
    finally:
        unob_conn.close()


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

    # Entity-aware search: find additional docs via entity index
    entity_docs_added = 0
    if search:
        entity_index = request.app.state.entity_index
        try:
            extra_ids = _entity_doc_ids(entity_index, unob, search)
            existing_ids = {d["id"] for d in docs}
            new_ids = extra_ids - existing_ids
            if new_ids:
                # Fetch the additional documents
                for doc_id in sorted(new_ids):
                    doc = unob.get_document(doc_id)
                    if doc:
                        docs.append(doc)
                        entity_docs_added += 1
                total += entity_docs_added
        except Exception:
            pass  # Entity search is best-effort

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

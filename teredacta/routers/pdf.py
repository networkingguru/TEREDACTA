from pathlib import Path
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, FileResponse
from starlette.responses import Response

router = APIRouter()

@router.get("/view", response_class=HTMLResponse)
def pdf_viewer(request: Request, type: str = Query(...), path: str = Query(...)):
    if type not in ("cache", "output", "summary"):
        return Response(status_code=400)
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "pdf/viewer.html", {
        "pdf_type": type, "pdf_path": path,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })

@router.get("/embed", response_class=HTMLResponse)
def pdf_embed(request: Request, type: str = Query(...), path: str = Query(...)):
    if type not in ("cache", "output", "summary"):
        return Response(status_code=400)
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "pdf/embed.html", {
        "pdf_url": f"/pdf/{type}/{path}",
    })

@router.get("/{pdf_type}/{path:path}")
def serve_pdf(request: Request, pdf_type: str, path: str):
    unob = request.app.state.unob
    pdf_path = unob.get_pdf_path(pdf_type, path)
    if pdf_path is None:
        return Response(status_code=404)
    return FileResponse(str(pdf_path), media_type="application/pdf")

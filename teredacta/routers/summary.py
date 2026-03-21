from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def view_summary(request: Request):
    templates = request.app.state.templates
    unob = request.app.state.unob
    summary_path = unob.get_pdf_path("summary", "summary_report.pdf")
    return templates.TemplateResponse("summary/view.html", {
        "request": request, "has_summary": summary_path is not None,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })

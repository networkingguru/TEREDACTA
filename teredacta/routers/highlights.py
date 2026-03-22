from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def highlights_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse("highlights.html", {
        "request": request,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
    })

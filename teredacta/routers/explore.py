from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def explore_page(request: Request):
    templates = request.app.state.templates
    entity_index = request.app.state.entity_index
    config = request.app.state.config

    status = entity_index.get_status(unob_db_path=config.db_path)
    entity_index_ready = status["state"] in ("ready", "stale")
    entity_index_stale = status["state"] == "stale"
    entity_index_built_at = status.get("built_at", "")

    return templates.TemplateResponse("explore.html", {
        "request": request,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "entity_index_ready": entity_index_ready,
        "entity_index_stale": entity_index_stale,
        "entity_index_built_at": entity_index_built_at,
    })

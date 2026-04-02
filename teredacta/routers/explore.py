from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def explore_page(request: Request):
    templates = request.app.state.templates
    entity_index = request.app.state.entity_index
    unob = request.app.state.unob

    # Fetch staleness timestamp via the warm connection pool instead of
    # letting get_status() open a cold separate connection to the 6 GB DB.
    max_merge_ts = unob.get_max_merge_ts()
    status = entity_index.get_status(max_merge_ts=max_merge_ts)
    entity_index_ready = status["state"] in ("ready", "stale")
    entity_index_stale = status["state"] == "stale"
    entity_index_built_at = status.get("built_at", "")

    return templates.TemplateResponse(request, "explore.html", {
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "entity_index_ready": entity_index_ready,
        "entity_index_stale": entity_index_stale,
        "entity_index_built_at": entity_index_built_at,
    })

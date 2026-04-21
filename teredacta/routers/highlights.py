import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

# Content anchors for the featured recovery card. The group_id that holds this
# content changes when unob's matcher/merger algorithm is rerun; resolving by
# substring survives those regens. The MCC duty-officer / staff psychologist
# memo thread is the narrative anchor for the highlights page.
_FEATURED_ANCHORS = ("Tova Noel", "psychologist")


def _get_headline(segments_json: str) -> str:
    """Extract the first substantive segment text (~100 chars for headline."""
    try:
        segments = json.loads(segments_json) if isinstance(segments_json, str) else segments_json
    except (json.JSONDecodeError, TypeError):
        return ""
    skip_prefixes = ("The image", "This image", "This page")
    for seg in segments:
        text = seg.get("text", "") if isinstance(seg, dict) else str(seg)
        text = text.strip()
        if not text or len(text) < 10:
            continue
        if any(text.startswith(p) for p in skip_prefixes):
            continue
        return text[:100] + ("..." if len(text) > 100 else "")
    return ""


@router.get("/", response_class=HTMLResponse)
def highlights_page(request: Request):
    templates = request.app.state.templates
    unob = request.app.state.unob
    entity_index = request.app.state.entity_index

    # Top recoveries by recovered_count
    top_recoveries = []
    try:
        for row in unob.get_top_recoveries(limit=20):
            top_recoveries.append({
                "group_id": row["group_id"],
                "recovered_count": row["recovered_count"],
                "headline": _get_headline(row["recovered_segments"]),
            })
    except FileNotFoundError:
        pass

    # Featured recovery (pinned at top of highlights)
    featured = None
    try:
        featured_detail = unob.get_featured_recovery(list(_FEATURED_ANCHORS))
        if featured_detail:
            featured = {
                "group_id": featured_detail["group_id"],
                "recovered_count": featured_detail["recovered_count"],
                "headline": _get_headline(featured_detail.get("recovered_segments", [])),
            }
    except FileNotFoundError:
        pass

    # Top entities from entity index (single query with samples)
    top_entities = []
    try:
        top_entities = entity_index.get_entities_with_samples(limit=20)
    except Exception:
        pass

    # Common unredactions
    common = []
    try:
        common = unob.get_common_unredactions(min_occurrences=2, min_words=3, limit=20)
    except FileNotFoundError:
        pass

    return templates.TemplateResponse(request, "highlights.html", {
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "top_recoveries": top_recoveries,
        "top_entities": top_entities,
        "common": common,
        "featured": featured,
    })

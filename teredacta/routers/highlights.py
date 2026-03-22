import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


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
        conn = unob._get_db()
        try:
            rows = conn.execute(
                "SELECT group_id, recovered_count, recovered_segments "
                "FROM merge_results WHERE recovered_count > 0 "
                "ORDER BY recovered_count DESC LIMIT 20"
            ).fetchall()
            for row in rows:
                headline = _get_headline(row["recovered_segments"])
                top_recoveries.append({
                    "group_id": row["group_id"],
                    "recovered_count": row["recovered_count"],
                    "headline": headline,
                })
        finally:
            conn.close()
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

    return templates.TemplateResponse("highlights.html", {
        "request": request,
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "top_recoveries": top_recoveries,
        "top_entities": top_entities,
        "common": common,
    })

"""Entity extraction and indexing for TEREDACTA.

Extracts people, organizations, locations, emails, and phone numbers
from recovered text segments. Stores results in a separate SQLite
database (not the read-only Unobfuscator DB).
"""

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Stop lists and known-entity sets
# ---------------------------------------------------------------------------

_PERSON_STOP = frozenset({
    # Courts and legal
    "united states", "southern district", "northern district",
    "eastern district", "western district", "circuit court",
    "district court", "supreme court", "states attorney",
    "assistant united", "special agent", "attorney general",
    "inspector general", "protective order", "certificate of",
    "sex offender", "human trafficking", "task force",
    "discovery issues", "child exploitation",
    # Locations
    "palm beach", "west palm", "new york", "new mexico",
    "virgin islands", "mar lago", "san diego", "los angeles",
    "las vegas", "fort lauderdale", "park avenue", "lexington avenue",
    "arizona state", "el brillo", "little st", "one saint",
    "australian ave", "of florida", "fl new",
    # Document/email artifacts
    "page break", "case number", "case summary", "search warrant",
    "release batch", "data set", "match group", "original notes",
    "original message", "key information", "external email",
    "email details", "flight information", "travel details",
    "date sent", "subject re", "reply to", "thanks from",
    "from sent", "message from", "sent tue", "sent wed",
    "sent mon", "sent fri", "sent thu", "sent sat", "sent sun",
    "confidentiality notice", "normal attachments",
    # Greetings/closings
    "good morning", "hi lesley", "hi jeffrey", "hi thanks",
    "hi we", "dear lesley", "best regards", "kind regards",
    "thank you",
    # Date/time fragments
    "on jul", "on jun", "on jan", "on feb", "on mar", "on apr",
    "on may", "on aug", "on sep", "on oct", "on nov", "on dec",
    "on mon", "on tue", "on wed", "on thu", "on fri", "on sat", "on sun",
    "on behalf", "pm edt", "am edt", "pm est", "am est",
    "eastern time", "estimated time",
    # Business titles/terms
    "wealth management", "private wealth", "private bank",
    "managing director", "relationship manager", "executive assistant",
    "vice president", "assistant vice", "project controller",
    "global services", "southern financial", "southern trust",
    "bank trust", "trust company", "company americas",
    "securities inc", "associates inc", "field office",
    "economy class", "departure terminal", "centurion travel",
    "space exploration", "inquiry regarding",
    # Misc false positives
    "blacked out", "do not", "in the", "of the", "operated by",
    "samsung galaxy", "last name", "epstein date", "epstein victim",
    "epstein victims", "airline record", "ticket number",
    "incl ticketno", "mr epstein", "fbi ny",
    # Organizations (avoid double-counting as person)
    "american express", "deutsche bank", "deutsche asset",
    "goldman sachs", "boies schiller", "quinney college",
    "freedom air", "hyperion air",
    # Senior/forensic (partial matches from documents)
    "senior forensic", "federal bureau", "coordinator senior",
    "forensic examiner", "ny cart",
    # Address/building fragments
    "floor new", "plaza new", "avenue new",
    # Misc institutions
    "law offices", "metropolitan correctional",
    # Repeated/reversed names
    "lesley lesley", "epstein jeffrey", "jefffrey epstein",
    # Company+name merges
    "molotkova centurion",
})

# First words that are never the start of a person's name
_PERSON_BAD_FIRST = frozenset({
    "on", "in", "of", "hi", "do", "fl", "re", "to", "pm", "am",
    "no", "if", "at", "by", "or", "an", "us", "my", "so", "up",
    "mr", "ms", "dr",  # titles — could be valid but too noisy
})

_KNOWN_ORGS = [
    "FBI", "SDNY", "DOJ", "USAO", "CIA", "NSA", "DEA", "IRS", "SEC",
    "BOP", "CART", "BRG", "ICE", "NYPD", "USMS",
    "JPMorgan", "Goldman Sachs", "Deutsche Bank", "Apollo Global",
    "Victoria's Secret",
]

_KNOWN_LOCATIONS = [
    "Palm Beach", "Mar-a-Lago", "Virgin Islands", "Manhattan",
    "New York", "New Mexico", "Little St. James", "Great St. James",
    "Zorro Ranch", "Saint Andrews", "Tallahassee",
]

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# People: Title Case names (2-4 words, optional suffix)
_RE_PERSON_TITLE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+(?:\s+(?:Jr|Sr|III?|IV)\.?)?)\b"
)

# People: ALL CAPS names (2+ words of 2+ uppercase letters each)
_RE_PERSON_CAPS = re.compile(
    r"\b([A-Z]{2,}(?:\s+[A-Z]\.?)?\s+[A-Z]{2,}(?:\s+(?:JR|SR|III?|IV)\.?)?)\b"
)

# Orgs: parenthetical abbreviations like (FBI), (USANYS), (CRM), (NY)
_RE_ORG_PAREN = re.compile(r"\(([A-Z]{2,})\)")

# Emails
_RE_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# US phone numbers — require separators to avoid false positives on long numbers
_RE_PHONE = re.compile(
    r"(?:\+?1[\s.-])?\(\d{3}\)[\s.-]\d{3}[\s.-]\d{4}\b"
    r"|\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b"
)


def _normalize_caps_name(name: str) -> str:
    """Convert ALL-CAPS name to Title Case."""
    return name.title()


def extract_entities(text: str) -> list[dict]:
    """Extract named entities from *text*.

    Returns a list of dicts with ``name`` and ``type`` keys.
    Types: person, org, location, email, phone.
    """
    if not text:
        return []

    seen: set[tuple[str, str]] = set()
    results: list[dict] = []

    def _add(name: str, etype: str) -> None:
        name = name.strip()
        if not name:
            return
        key = (name.lower(), etype)
        if key not in seen:
            seen.add(key)
            results.append({"name": name, "type": etype})

    # --- Locations (before people, so stop-list can exclude them) ---
    for loc in _KNOWN_LOCATIONS:
        if loc in text or loc.upper() in text:
            _add(loc, "location")

    # --- People ---
    def _valid_person(name: str) -> bool:
        """Filter out common false positives from person name matches."""
        if name.lower() in _PERSON_STOP:
            return False
        words = name.split()
        if len(words) < 2:
            return False
        # Reject names with newlines or tabs (regex matched across lines)
        if "\n" in name or "\t" in name:
            return False
        # Reject if first word is a known non-name starter
        if words[0].lower() in _PERSON_BAD_FIRST:
            return False
        # Reject if any word is only 1-2 chars (except initials like "J."
        # and known suffixes like "Jr", "Sr", "IV")
        _SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
        for w in words:
            if len(w) <= 2 and not w.endswith(".") and w.lower() not in _SUFFIXES:
                return False
        return True

    for m in _RE_PERSON_TITLE.finditer(text):
        name = m.group(1).strip()
        if not _valid_person(name):
            continue
        _add(name, "person")

    for m in _RE_PERSON_CAPS.finditer(text):
        raw = m.group(1).strip()
        name = _normalize_caps_name(raw)
        if not _valid_person(name):
            continue
        _add(name, "person")

    # --- Organizations ---
    for org in _KNOWN_ORGS:
        # Match as whole word (or as-is for multi-word orgs)
        if re.search(r"\b" + re.escape(org) + r"\b", text):
            _add(org, "org")

    for m in _RE_ORG_PAREN.finditer(text):
        abbr = m.group(1)
        # Don't double-count known orgs already found above
        key = (abbr.lower(), "org")
        if key not in seen:
            _add(abbr, "org")

    # --- Emails ---
    for m in _RE_EMAIL.finditer(text):
        _add(m.group(0), "email")

    # --- Phones ---
    for m in _RE_PHONE.finditer(text):
        _add(m.group(0), "phone")

    return results


# ---------------------------------------------------------------------------
# Entity Index — SQLite-backed store
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    mention_count INTEGER DEFAULT 0,
    UNIQUE(name, type)
);

CREATE TABLE IF NOT EXISTS entity_mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    group_id INTEGER NOT NULL,
    context TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entity_id, group_id)
);

CREATE TABLE IF NOT EXISTS entity_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_a_id INTEGER NOT NULL REFERENCES entities(id),
    entity_b_id INTEGER NOT NULL REFERENCES entities(id),
    co_occurrence_count INTEGER DEFAULT 1,
    UNIQUE(entity_a_id, entity_b_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_mentions_entity ON entity_mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_mentions_group ON entity_mentions(group_id);
CREATE INDEX IF NOT EXISTS idx_links_a ON entity_links(entity_a_id);
CREATE INDEX IF NOT EXISTS idx_links_b ON entity_links(entity_b_id);
"""


class EntityIndex:
    """Builds and queries the TEREDACTA entity index."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- internal helpers --------------------------------------------------

    def _get_db(self, readonly: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA journal_mode = WAL")
        if readonly:
            conn.execute("PRAGMA query_only = ON")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(_SCHEMA)

    # -- build -------------------------------------------------------------

    def build(self, unob_db_path: str) -> dict:
        """Read recovered_segments from the Unobfuscator DB and populate
        the entity index.  Returns summary stats."""
        # Read from Unobfuscator (read-only) — use cursor iterator to avoid
        # loading all rows into memory at once (S2)
        src = sqlite3.connect(unob_db_path, timeout=10.0)
        src.row_factory = sqlite3.Row
        src.execute("PRAGMA query_only = ON")
        src_cursor = src.execute(
            "SELECT group_id, recovered_segments FROM merge_results "
            "WHERE recovered_count > 0 AND recovered_segments IS NOT NULL"
        )

        # Open/create entity DB
        conn = self._get_db()
        self._ensure_schema(conn)

        # Wrap delete+rebuild in explicit transaction
        conn.execute("BEGIN IMMEDIATE")

        # Clear previous data
        conn.execute("DELETE FROM entity_links")
        conn.execute("DELETE FROM entity_mentions")
        conn.execute("DELETE FROM entities")
        conn.execute("DELETE FROM meta")

        entity_ids: dict[tuple[str, str], int] = {}

        def _get_or_create(name: str, etype: str) -> int:
            key = (name, etype)
            if key in entity_ids:
                return entity_ids[key]
            cur = conn.execute(
                "INSERT OR IGNORE INTO entities (name, type) VALUES (?, ?)",
                (name, etype),
            )
            if cur.lastrowid and cur.lastrowid > 0:
                eid = cur.lastrowid
            else:
                eid = conn.execute(
                    "SELECT id FROM entities WHERE name = ? AND type = ?",
                    (name, etype),
                ).fetchone()["id"]
            entity_ids[key] = eid
            return eid

        total_mentions = 0

        for row in src_cursor:
            group_id = row["group_id"]
            try:
                segments = json.loads(row["recovered_segments"])
            except (json.JSONDecodeError, TypeError):
                continue

            # Combine all segment texts for this group
            full_text = " ".join(
                seg.get("text", "") if isinstance(seg, dict) else str(seg)
                for seg in segments
                if seg
            )

            entities = extract_entities(full_text)
            if not entities:
                continue

            group_entity_ids: list[int] = []
            for ent in entities:
                eid = _get_or_create(ent["name"], ent["type"])
                conn.execute(
                    "INSERT OR IGNORE INTO entity_mentions (entity_id, group_id, context) "
                    "VALUES (?, ?, ?)",
                    (eid, group_id, full_text[:500]),
                )
                group_entity_ids.append(eid)
                total_mentions += 1

            # Build co-occurrence links within this group
            unique_ids = sorted(set(group_entity_ids))
            for i, a in enumerate(unique_ids):
                for b in unique_ids[i + 1:]:
                    conn.execute(
                        "INSERT INTO entity_links (entity_a_id, entity_b_id, co_occurrence_count) "
                        "VALUES (?, ?, 1) "
                        "ON CONFLICT(entity_a_id, entity_b_id) "
                        "DO UPDATE SET co_occurrence_count = co_occurrence_count + 1",
                        (a, b),
                    )

        src.close()

        # Update mention counts
        conn.execute(
            "UPDATE entities SET mention_count = "
            "(SELECT COUNT(*) FROM entity_mentions WHERE entity_mentions.entity_id = entities.id)"
        )

        # Store metadata
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('built_at', ?)",
            (now,),
        )
        entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('entity_count', ?)",
            (str(entity_count),),
        )
        conn.commit()
        conn.close()

        return {
            "entities": entity_count,
            "mentions": total_mentions,
            "built_at": now,
        }

    # -- status ------------------------------------------------------------

    def get_status(self, unob_db_path: str | None = None) -> dict:
        """Return index state: not_built, ready, or stale."""
        db = Path(self.db_path)
        if not db.exists():
            return {"state": "not_built", "entities": 0, "mentions": 0, "built_at": None}

        conn = self._get_db(readonly=True)
        try:
            # Check if schema exists
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "meta" not in tables or "entities" not in tables:
                return {"state": "not_built", "entities": 0, "mentions": 0, "built_at": None}

            built_at_row = conn.execute(
                "SELECT value FROM meta WHERE key = 'built_at'"
            ).fetchone()
            if not built_at_row:
                return {"state": "not_built", "entities": 0, "mentions": 0, "built_at": None}

            built_at = built_at_row["value"]
            entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            mention_count = conn.execute("SELECT COUNT(*) FROM entity_mentions").fetchone()[0]

            state = "ready"

            # Staleness check: compare against Unobfuscator's merge_results
            if unob_db_path and Path(unob_db_path).exists():
                src = sqlite3.connect(unob_db_path, timeout=5.0)
                src.row_factory = sqlite3.Row
                try:
                    max_row = src.execute(
                        "SELECT MAX(created_at) as max_ts FROM merge_results"
                    ).fetchone()
                    if max_row and max_row["max_ts"] and max_row["max_ts"] > built_at:
                        state = "stale"
                finally:
                    src.close()

            return {
                "state": state,
                "entities": entity_count,
                "mentions": mention_count,
                "built_at": built_at,
            }
        except sqlite3.OperationalError:
            return {"state": "not_built", "entities": 0, "mentions": 0, "built_at": None}
        finally:
            conn.close()

    # -- query -------------------------------------------------------------

    def list_entities(
        self,
        entity_type: str | None = None,
        name_filter: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[dict], int]:
        """Filtered, paginated entity listing."""
        db = Path(self.db_path)
        if not db.exists():
            return [], 0

        conn = self._get_db(readonly=True)
        try:
            where_parts: list[str] = []
            params: list = []

            if entity_type:
                where_parts.append("type = ?")
                params.append(entity_type)
            if name_filter:
                where_parts.append("name LIKE ?")
                params.append(f"%{name_filter}%")

            where = " AND ".join(where_parts) if where_parts else "1=1"
            total = conn.execute(
                f"SELECT COUNT(*) FROM entities WHERE {where}", params
            ).fetchone()[0]

            offset = (page - 1) * per_page
            rows = conn.execute(
                f"SELECT id, name, type, mention_count FROM entities "
                f"WHERE {where} ORDER BY mention_count DESC, name "
                f"LIMIT ? OFFSET ?",
                params + [per_page, offset],
            ).fetchall()

            return [dict(r) for r in rows], total
        finally:
            conn.close()

    def get_entities_with_samples(self, limit: int = 20) -> list[dict]:
        """Fetch top entities with one sample snippet each in a single query."""
        db = Path(self.db_path)
        if not db.exists():
            return []

        conn = self._get_db(readonly=True)
        try:
            rows = conn.execute(
                "SELECT e.id, e.name, e.type, e.mention_count, "
                "(SELECT em.context FROM entity_mentions em "
                " WHERE em.entity_id = e.id LIMIT 1) AS sample "
                "FROM entities e "
                "ORDER BY e.mention_count DESC, e.name "
                "LIMIT ?",
                (limit,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                sample = d.pop("sample", None) or ""
                d["sample"] = sample[:150]
                results.append(d)
            return results
        finally:
            conn.close()

    def get_entity(self, entity_id: int) -> dict | None:
        """Get a single entity by ID."""
        db = Path(self.db_path)
        if not db.exists():
            return None

        conn = self._get_db(readonly=True)
        try:
            row = conn.execute(
                "SELECT id, name, type, mention_count FROM entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_connections(self, entity_id: int) -> dict | None:
        """Get entity with its recovery mentions and linked entities."""
        db = Path(self.db_path)
        if not db.exists():
            return None

        conn = self._get_db(readonly=True)
        try:
            entity = conn.execute(
                "SELECT id, name, type, mention_count FROM entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
            if not entity:
                return None

            recoveries = conn.execute(
                "SELECT group_id, context FROM entity_mentions "
                "WHERE entity_id = ? ORDER BY group_id",
                (entity_id,),
            ).fetchall()

            linked = conn.execute(
                "SELECT e.id, e.name, e.type, e.mention_count, el.co_occurrence_count "
                "FROM entity_links el "
                "JOIN entities e ON e.id = CASE WHEN el.entity_a_id = ? THEN el.entity_b_id ELSE el.entity_a_id END "
                "WHERE el.entity_a_id = ? OR el.entity_b_id = ? "
                "ORDER BY el.co_occurrence_count DESC",
                (entity_id, entity_id, entity_id),
            ).fetchall()

            return {
                "entity": dict(entity),
                "recoveries": [dict(r) for r in recoveries],
                "linked_entities": [dict(r) for r in linked],
            }
        finally:
            conn.close()

import html
import json
import logging
import os
import platform
import shlex
import sqlite3
import subprocess
import re
import threading
import time
from pathlib import Path
from typing import Optional

from teredacta.config import TeredactaConfig

# text_source values that indicate a downloadable PDF exists
_PDF_TEXT_SOURCES = frozenset({"pdf_text_layer", "ocr"})

# Pre-compiled regexes for format_merged_text
_RE_CHANGE_U = re.compile(
    r"&lt;change&gt;&lt;u&gt;(.*?)&lt;/u&gt;&lt;/change&gt;", re.DOTALL
)
_RE_CHANGE_BARE = re.compile(r"&lt;/?change&gt;")
_RE_U_BARE = re.compile(r"&lt;/?u&gt;")
_TABLE_OPEN = "&lt;table&gt;"
_TABLE_CLOSE = "&lt;/table&gt;"
_TABLE_TAG_RE = re.compile(r"&lt;/?(tr|th|td)&gt;")


def parse_boolean_search(query: str) -> list[tuple[str, str]]:
    """Parse a search query with AND/OR operators and quoted phrases.

    Returns list of (term, operator) tuples.  The operator indicates how
    this term connects to the *previous* term.  The first term always
    has operator "AND".

    Examples:
        "maxwell"             -> [("maxwell", "AND")]
        "maxwell AND epstein" -> [("maxwell", "AND"), ("epstein", "AND")]
        "maxwell OR epstein"  -> [("maxwell", "AND"), ("epstein", "OR")]
        '"palm beach" AND maxwell' -> [("palm beach", "AND"), ("maxwell", "AND")]
    """
    if not query or not query.strip():
        return []

    tokens: list[str] = []
    i = 0
    q = query.strip()
    while i < len(q):
        if q[i] == '"':
            # Quoted phrase
            end = q.find('"', i + 1)
            if end == -1:
                end = len(q)
            tokens.append(q[i + 1:end])
            i = end + 1
        elif q[i] == ' ':
            i += 1
        else:
            end = i
            while end < len(q) and q[end] != ' ' and q[end] != '"':
                end += 1
            tokens.append(q[i:end])
            i = end

    # Build (term, operator) pairs
    result: list[tuple[str, str]] = []
    pending_op = "AND"
    for tok in tokens:
        upper = tok.upper()
        if upper == "AND":
            pending_op = "AND"
        elif upper == "OR":
            pending_op = "OR"
        elif tok:  # skip empty tokens (e.g. from empty quotes "")
            result.append((tok, pending_op))
            pending_op = "AND"  # default between adjacent terms

    return result


def calc_total_pages(total: int, per_page: int) -> int:
    return max(1, (total + per_page - 1) // per_page)


class UnobInterface:
    """Single interface to all Unobfuscator interactions."""

    # TTL for common unredactions cache (seconds)
    _COMMON_CACHE_TTL = 300  # 5 minutes
    _MAX_MEMBER_TEXT_CHARS = 102_400  # ~100K characters
    _STATS_CACHE_TTL = 10  # seconds

    _INDEXES = [
        ("idx_docs_text_processed", "documents", "text_processed"),
        ("idx_docs_pdf_processed", "documents", "pdf_processed"),
        ("idx_docs_original_filename", "documents", "original_filename"),
        ("idx_docs_text_id", "documents", "text_processed, id"),
        ("idx_docs_pdf_id", "documents", "pdf_processed, id"),
        ("idx_docs_source_id", "documents", "source, id"),
        ("idx_merge_created_at", "merge_results", "created_at"),
        ("idx_merge_recovered", "merge_results", "recovered_count"),
    ]

    def __init__(self, config: TeredactaConfig):
        self.config = config
        self._common_unredactions_cache = None
        self._common_cache_time: float = 0.0
        self._stats_cache: Optional[dict] = None
        self._stats_cache_time: float = 0.0  # monotonic
        self._match_groups_count_cache: Optional[int] = None
        self._match_groups_count_time: float = 0.0
        self._fts_available: Optional[bool] = None
        self._pool = None  # Lazy-initialized ConnectionPool
        self._pool_lock = threading.Lock()

    @staticmethod
    def _estimate_total(rows: list, per_page: int, offset: int) -> tuple[list, int]:
        """Trim fetch+1 rows and estimate total without COUNT."""
        has_more = len(rows) > per_page
        rows = rows[:per_page]
        if has_more:
            return rows, offset + len(rows) + per_page
        return rows, offset + len(rows)

    def _get_db(self) -> sqlite3.Connection:
        if self._pool is None:
            with self._pool_lock:
                if self._pool is None:  # double-checked locking
                    from teredacta.db_pool import ConnectionPool
                    db_path = Path(self.config.db_path)
                    if not db_path.exists():
                        raise FileNotFoundError(
                            f"Database not found at {db_path}. "
                            "Check your TEREDACTA configuration."
                        )
                    self._pool = ConnectionPool(
                        str(db_path),
                        max_size=self.config.max_pool_size,
                        read_only=True,
                        busy_timeout=5000,
                    )
        return self._pool.acquire()

    def _release_db(self, conn: sqlite3.Connection):
        if self._pool:
            self._pool.release(conn)
        else:
            conn.close()

    def pool_status(self) -> dict | None:
        """Return DB pool metrics, or None if pool not yet initialized."""
        if self._pool is None:
            return None
        return self._pool.pool_status()

    def close(self):
        if self._pool:
            self._pool.close()

    def ensure_indexes(self):
        """Create performance indexes if missing (must run before query_only)."""
        db_path = Path(self.config.db_path)
        if not db_path.exists():
            return
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        try:
            conn.execute("PRAGMA busy_timeout = 10000")
            for idx_name, table, column in self._INDEXES:
                try:
                    conn.execute(
                        f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})"
                    )
                except sqlite3.OperationalError:
                    # Table does not exist yet — skip index creation for now.
                    pass
            conn.commit()
        finally:
            conn.close()

    def warm_up(self):
        """Run the same queries each tab uses to page data into OS cache.

        Best-effort — failures are logged and swallowed so a cold DB
        never prevents startup.
        """
        try:
            conn = self._get_db()
        except FileNotFoundError:
            return
        try:
            # /documents tab: paginated listing
            conn.execute(
                "SELECT COUNT(*) FROM documents"
            ).fetchone()
            conn.execute(
                "SELECT id, source, release_batch, original_filename, "
                "page_count, description, text_processed, pdf_processed "
                "FROM documents ORDER BY id LIMIT 50"
            ).fetchall()

            # /recoveries tab: top recoveries
            conn.execute(
                "SELECT group_id, recovered_count, recovered_segments "
                "FROM merge_results WHERE recovered_count > 0 "
                "ORDER BY recovered_count DESC LIMIT 50"
            ).fetchall()

            # /highlights tab: common unredactions (json_each on top 500)
            conn.execute(
                "SELECT mr.group_id, value FROM "
                "(SELECT group_id, recovered_segments FROM merge_results "
                " WHERE recovered_count > 0 AND recovered_segments IS NOT NULL "
                " ORDER BY recovered_count DESC LIMIT 500) mr, "
                "json_each(mr.recovered_segments) WHERE value IS NOT NULL"
            ).fetchall()

            # /groups tab: match groups with member stats
            conn.execute(
                "SELECT mg.group_id, mg.merged, mg.created_at, "
                "  COUNT(mgm.doc_id) as member_count, "
                "  AVG(mgm.similarity) as avg_similarity "
                "FROM match_groups mg "
                "LEFT JOIN match_group_members mgm ON mg.group_id = mgm.group_id "
                "GROUP BY mg.group_id ORDER BY mg.group_id DESC LIMIT 50"
            ).fetchall()
        except Exception as exc:
            logging.getLogger(__name__).warning("warm_up failed: %s", exc)
        finally:
            self._release_db(conn)

    def run_migration(self):
        """Run performance migrations: has_redactions column + FTS5 index.

        Opens the DB in write mode (bypasses read-only pool). Idempotent.
        """
        logger = logging.getLogger(__name__)
        db_path = Path(self.config.db_path)
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found at {db_path}")

        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            # 1. Add has_redactions column if missing
            columns = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
            if "has_redactions" not in columns:
                logger.info("Adding has_redactions column...")
                conn.execute("ALTER TABLE documents ADD COLUMN has_redactions INTEGER DEFAULT 0")
                conn.commit()

            # 2. Backfill has_redactions for rows that haven't been set
            updated = conn.execute(
                "UPDATE documents SET has_redactions = 1 "
                "WHERE (has_redactions IS NULL OR has_redactions = 0) AND ("
                "  extracted_text LIKE '%[REDACTED]%' "
                "  OR extracted_text LIKE '%[b(6)]%' "
                "  OR extracted_text LIKE '%XXXXXXXXX%'"
                ")"
            ).rowcount
            if updated:
                logger.info("Backfilled has_redactions for %d documents", updated)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_docs_has_redactions "
                "ON documents(has_redactions)"
            )
            conn.commit()

            # 3. Create FTS5 virtual table if missing
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "documents_fts" not in tables:
                logger.info("Creating FTS5 index on id, original_filename...")
                conn.execute(
                    "CREATE VIRTUAL TABLE documents_fts USING fts5("
                    "  id, original_filename, content='documents', content_rowid='rowid'"
                    ")"
                )
                conn.execute(
                    "INSERT INTO documents_fts(documents_fts) VALUES('rebuild')"
                )
                conn.commit()
                logger.info("FTS5 index built")
            else:
                logger.info("FTS5 table already exists, skipping rebuild")

        finally:
            conn.close()
            self._fts_available = None  # invalidate cache after migration

    def get_max_merge_ts(self) -> str | None:
        """Return MAX(created_at) from merge_results using the warm pool."""
        try:
            conn = self._get_db()
        except FileNotFoundError:
            return None
        try:
            row = conn.execute(
                "SELECT MAX(created_at) as max_ts FROM merge_results"
            ).fetchone()
            return row["max_ts"] if row else None
        except Exception:
            return None
        finally:
            self._release_db(conn)

    # --- Stats ---

    def get_stats(self) -> dict:
        now = time.monotonic()
        if self._stats_cache and (now - self._stats_cache_time) < self._STATS_CACHE_TTL:
            return self._stats_cache
        conn = self._get_db()
        try:
            stats = {}
            stats["total_documents"] = conn.execute(
                "SELECT COUNT(*) FROM documents"
            ).fetchone()[0]
            stats["indexed"] = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE text_processed = 1"
            ).fetchone()[0]
            stats["fingerprinted"] = conn.execute(
                "SELECT COUNT(*) FROM document_fingerprints"
            ).fetchone()[0]
            stats["matched"] = conn.execute(
                "SELECT COUNT(*) FROM match_group_members"
            ).fetchone()[0]
            stats["groups"] = conn.execute(
                "SELECT COUNT(*) FROM match_groups"
            ).fetchone()[0]
            stats["merged"] = conn.execute(
                "SELECT COUNT(*) FROM merge_results WHERE recovered_count > 0"
            ).fetchone()[0]
            stats["recovered"] = conn.execute(
                "SELECT COALESCE(SUM(recovered_count), 0) FROM merge_results"
            ).fetchone()[0]
            stats["soft_recovered"] = conn.execute(
                "SELECT COALESCE(SUM(soft_recovered_count), 0) FROM merge_results"
            ).fetchone()[0]
            stats["pdfs_processed"] = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE pdf_processed = 1"
            ).fetchone()[0]
            stats["outputs_generated"] = conn.execute(
                "SELECT COUNT(*) FROM merge_results WHERE output_generated = 1"
            ).fetchone()[0]
            stats["failed_jobs"] = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = 'failed'"
            ).fetchone()[0]
            self._stats_cache = stats
            self._stats_cache_time = time.monotonic()
            return stats
        finally:
            self._release_db(conn)

    # --- Documents ---

    def _has_fts(self, conn: sqlite3.Connection) -> bool:
        """Check if the FTS5 virtual table exists (cached after first check)."""
        if self._fts_available is not None:
            return self._fts_available
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents_fts'"
            ).fetchone()
            self._fts_available = row is not None
        except sqlite3.OperationalError:
            self._fts_available = False
        return self._fts_available

    def get_documents(
        self,
        page: int = 1,
        per_page: int = 50,
        search: Optional[str] = None,
        source: Optional[str] = None,
        batch: Optional[str] = None,
        has_redactions: Optional[bool] = None,
        stage: Optional[str] = None,
        extra_doc_ids: Optional[set[str]] = None,
    ) -> tuple[list[dict], int]:
        conn = self._get_db()
        try:
            offset = (page - 1) * per_page
            cols = ("id, source, release_batch, original_filename, "
                    "page_count, description, text_processed, pdf_processed")

            if search:
                # Try FTS5 first (fast word-based search)
                fts_available = self._has_fts(conn)
                if fts_available:
                    fts_term = search.replace('"', '""')
                    fts_failed = False
                    try:
                        parts_fts = [
                            f"SELECT {cols} FROM documents "
                            f"WHERE rowid IN ("
                            f"  SELECT rowid FROM documents_fts "
                            f"  WHERE documents_fts MATCH ?"
                            f")"
                        ]
                        params_fts: list = [f'"{fts_term}"']
                        if extra_doc_ids:
                            placeholders = ",".join("?" for _ in extra_doc_ids)
                            parts_fts.append(
                                f"SELECT {cols} FROM documents WHERE id IN ({placeholders})"
                            )
                            params_fts.extend(sorted(extra_doc_ids))
                        query_fts = " UNION ".join(parts_fts) + " ORDER BY id LIMIT ? OFFSET ?"
                        rows = conn.execute(
                            query_fts, params_fts + [per_page + 1, offset]
                        ).fetchall()
                    except sqlite3.OperationalError:
                        rows = []
                        fts_failed = True

                    if not fts_failed:
                        rows, total = self._estimate_total(rows, per_page, offset)
                        return [dict(row) for row in rows], total

                # Fallback: LIKE on id and original_filename (used when FTS unavailable or errored)
                safe_search = search.replace("!", "!!").replace("%", "!%").replace("_", "!_")
                like_pattern = f"%{safe_search}%"
                parts = [
                    f"SELECT {cols} FROM documents WHERE original_filename LIKE ? ESCAPE '!'",
                    f"SELECT {cols} FROM documents WHERE id LIKE ? ESCAPE '!'",
                ]
                params_search: list = [like_pattern, like_pattern]
                if extra_doc_ids:
                    placeholders = ",".join("?" for _ in extra_doc_ids)
                    parts.append(f"SELECT {cols} FROM documents WHERE id IN ({placeholders})")
                    params_search.extend(sorted(extra_doc_ids))
                query = " UNION ".join(parts) + " ORDER BY id LIMIT ? OFFSET ?"
                rows = conn.execute(
                    query, params_search + [per_page + 1, offset]
                ).fetchall()
                rows, total = self._estimate_total(rows, per_page, offset)
                return [dict(row) for row in rows], total

            where_clauses = []
            params: list = []
            if source:
                where_clauses.append("source = ?")
                params.append(source)
            if batch:
                where_clauses.append("release_batch = ?")
                params.append(batch)
            if has_redactions is True:
                where_clauses.append("has_redactions = 1")
            if stage:
                if stage == "text_processed":
                    where_clauses.append("text_processed = 1")
                elif stage == "pdf_processed":
                    where_clauses.append("pdf_processed = 1")
                elif stage == "unprocessed":
                    where_clauses.append("text_processed = 0")

            where = " AND ".join(where_clauses) if where_clauses else "1=1"
            has_filters = bool(where_clauses)

            # For unfiltered listing, use cached total document count
            # (fast covering-index scan). For filtered queries, skip
            # the expensive COUNT and use fetch+1 to detect more pages.
            if has_filters:
                rows = conn.execute(
                    f"SELECT {cols} "
                    f"FROM documents WHERE {where} "
                    f"ORDER BY id "
                    f"LIMIT ? OFFSET ?",
                    params + [per_page + 1, offset],
                ).fetchall()
                rows, total = self._estimate_total(rows, per_page, offset)
            else:
                total = conn.execute(
                    f"SELECT COUNT(*) FROM documents WHERE {where}", params
                ).fetchone()[0]
                rows = conn.execute(
                    f"SELECT {cols} "
                    f"FROM documents WHERE {where} "
                    f"ORDER BY id "
                    f"LIMIT ? OFFSET ?",
                    params + [per_page, offset],
                ).fetchall()

            docs = [dict(row) for row in rows]
            return docs, total
        finally:
            self._release_db(conn)

    def get_document(self, doc_id: str) -> Optional[dict]:
        conn = self._get_db()
        try:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if row is None:
                return None
            doc = dict(row)

            # Check for match group membership
            group_row = conn.execute(
                "SELECT group_id, similarity FROM match_group_members WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
            if group_row:
                doc["group_id"] = group_row["group_id"]
                doc["similarity"] = group_row["similarity"]

            return doc
        finally:
            self._release_db(conn)

    def get_docs_by_group_ids(self, group_ids: list[int], limit: int = 200) -> set[str]:
        """Return doc_ids for the given match group IDs."""
        if not group_ids:
            return set()
        conn = self._get_db()
        try:
            placeholders = ",".join("?" for _ in group_ids)
            rows = conn.execute(
                f"SELECT DISTINCT doc_id FROM match_group_members "
                f"WHERE group_id IN ({placeholders}) LIMIT ?",
                list(group_ids) + [limit],
            ).fetchall()
            return {r["doc_id"] for r in rows}
        finally:
            self._release_db(conn)

    # --- Match Groups ---

    def get_match_groups(
        self,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[dict], int]:
        conn = self._get_db()
        try:
            now = time.monotonic()
            if (
                self._match_groups_count_cache is not None
                and (now - self._match_groups_count_time) < 30
            ):
                total = self._match_groups_count_cache
            else:
                total = conn.execute("SELECT COUNT(*) FROM match_groups").fetchone()[0]
                self._match_groups_count_cache = total
                self._match_groups_count_time = now

            offset = (page - 1) * per_page
            rows = conn.execute("""
                SELECT mg.group_id, mg.merged, mg.created_at,
                       COUNT(mgm.doc_id) as member_count,
                       AVG(mgm.similarity) as avg_similarity
                FROM match_groups mg
                LEFT JOIN match_group_members mgm ON mg.group_id = mgm.group_id
                GROUP BY mg.group_id
                ORDER BY mg.group_id DESC
                LIMIT ? OFFSET ?
            """, (per_page, offset)).fetchall()
            return [dict(row) for row in rows], total
        finally:
            self._release_db(conn)

    def get_match_group_detail(self, group_id: int) -> Optional[dict]:
        conn = self._get_db()
        try:
            group = conn.execute(
                "SELECT * FROM match_groups WHERE group_id = ?", (group_id,)
            ).fetchone()
            if group is None:
                return None

            total_members = conn.execute(
                "SELECT COUNT(*) FROM match_group_members WHERE group_id = ?",
                (group_id,),
            ).fetchone()[0]

            members = conn.execute(
                "SELECT mgm.doc_id, mgm.similarity, d.original_filename, d.source, "
                "d.release_batch, d.description "
                "FROM match_group_members mgm "
                "JOIN documents d ON mgm.doc_id = d.id "
                "WHERE mgm.group_id = ? ORDER BY mgm.similarity DESC "
                "LIMIT 100",
                (group_id,),
            ).fetchall()

            merge = conn.execute(
                "SELECT * FROM merge_results WHERE group_id = ?", (group_id,)
            ).fetchone()

            result = dict(group)
            result["members"] = [dict(m) for m in members]
            result["total_members"] = total_members
            result["merge_result"] = dict(merge) if merge else None
            return result
        finally:
            self._release_db(conn)

    # --- Recoveries ---

    def get_recoveries(
        self,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
        sort: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        conn = self._get_db()
        try:
            where = "mr.recovered_count > 0"
            params: list = []
            if search:
                terms = parse_boolean_search(search)
                if terms:
                    clauses = []
                    for term_text, _op in terms:
                        json_escaped = json.dumps(term_text)[1:-1]
                        escaped = json_escaped.replace("!", "!!").replace("%", "!%").replace("_", "!_")
                        clauses.append("mr.recovered_segments LIKE ? ESCAPE '!'")
                        params.append(f"%{escaped}%")

                    # Build boolean expression
                    combined = clauses[0]
                    for i in range(1, len(clauses)):
                        op = terms[i][1]  # AND or OR
                        combined = f"({combined} {op} {clauses[i]})"
                    where += f" AND ({combined})"

            # Determine sort order
            order_by = "mr.recovered_count DESC"
            if sort == "date":
                order_by = "mr.created_at DESC"

            total = conn.execute(
                f"SELECT COUNT(*) FROM merge_results mr WHERE {where}",
                params,
            ).fetchone()[0]

            rows = conn.execute(
                f"SELECT mr.group_id, mr.recovered_count, mr.total_redacted, "
                f"mr.soft_recovered_count, mr.source_doc_ids, mr.output_generated, "
                f"mr.created_at "
                f"FROM merge_results mr WHERE {where} "
                f"ORDER BY {order_by} "
                f"LIMIT ? OFFSET ?",
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
            return [dict(row) for row in rows], total
        finally:
            self._release_db(conn)

    def get_recovery_detail(self, group_id: int) -> Optional[dict]:
        conn = self._get_db()
        try:
            row = conn.execute(
                "SELECT * FROM merge_results WHERE group_id = ? AND recovered_count > 0",
                (group_id,),
            ).fetchone()
            if row is None:
                return None

            result = dict(row)
            # Parse JSON fields
            if result.get("source_doc_ids"):
                result["source_doc_ids"] = json.loads(result["source_doc_ids"])
            if result.get("recovered_segments"):
                segs = json.loads(result["recovered_segments"])
                for seg in segs:
                    if isinstance(seg, dict) and "text" in seg:
                        seg["text_html"] = self.format_merged_text(seg["text"])
                result["recovered_segments"] = segs
            # Pre-render merged text as safe HTML (with segment mapping for click-to-source)
            result["merged_text_html"] = self.format_merged_text(
                result.get("merged_text") or "",
                segments=result.get("recovered_segments"),
            )

            # Get group members with PDF cache paths.
            # Limit to source docs + top donors by similarity to avoid
            # rendering thousands of rows for large groups.
            source_ids = result.get("source_doc_ids") or []
            placeholders = ",".join("?" for _ in source_ids) if source_ids else "''"
            members = conn.execute(
                f"SELECT mgm.doc_id, mgm.similarity, d.original_filename, d.source, "
                f"d.release_batch, d.text_source, d.pdf_url "
                f"FROM match_group_members mgm "
                f"JOIN documents d ON mgm.doc_id = d.id "
                f"WHERE mgm.group_id = ? "
                f"ORDER BY CASE WHEN mgm.doc_id IN ({placeholders}) THEN 0 ELSE 1 END, "
                f"mgm.similarity DESC "
                f"LIMIT 50",
                [group_id] + source_ids,
            ).fetchall()
            total_members = conn.execute(
                "SELECT COUNT(*) FROM match_group_members WHERE group_id = ?",
                (group_id,),
            ).fetchone()[0]
            result["total_members"] = total_members
            member_list = []
            for m in members:
                member = dict(m)
                if m["release_batch"] and m["original_filename"]:
                    cache_path = Path(self.config.pdf_cache_dir) / m["release_batch"] / m["original_filename"]
                    member["pdf_cache_path"] = f"{m['release_batch']}/{m['original_filename']}" if cache_path.exists() else None
                else:
                    member["pdf_cache_path"] = None
                # jmail/backfill_miss docs are email records with no PDF representation
                member["has_pdf"] = m["text_source"] in _PDF_TEXT_SOURCES or bool(m["pdf_url"])
                member_list.append(member)
            result["members"] = member_list

            # Compute output PDF path: {source}/{release_batch}/{primary_doc_id}_merged.pdf
            result["output_pdf_path"] = None
            if result.get("output_generated") and result.get("source_doc_ids"):
                primary_doc_id = result["source_doc_ids"][0]
                doc_row = conn.execute(
                    "SELECT source, release_batch FROM documents WHERE id = ?",
                    (primary_doc_id,),
                ).fetchone()
                if doc_row and doc_row["source"] and doc_row["release_batch"]:
                    candidate = (
                        Path(self.config.output_dir)
                        / doc_row["source"]
                        / doc_row["release_batch"]
                        / f"{primary_doc_id}_merged.pdf"
                    )
                    if candidate.exists():
                        result["output_pdf_path"] = (
                            f"{doc_row['source']}/{doc_row['release_batch']}/{primary_doc_id}_merged.pdf"
                        )

            return result
        finally:
            self._release_db(conn)

    def get_top_recoveries(self, limit: int = 20) -> list[dict]:
        """Get top recoveries by recovered_count."""
        conn = self._get_db()
        try:
            rows = conn.execute(
                "SELECT group_id, recovered_count, recovered_segments "
                "FROM merge_results WHERE recovered_count > 0 "
                "ORDER BY recovered_count DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            self._release_db(conn)

    def get_source_context(self, group_id: int, segment_index: int) -> Optional[dict]:
        """Get source document context for a recovered segment.

        Returns a dict with source document info, surrounding unredacted text,
        and PDF availability details.
        """
        conn = self._get_db()
        try:
            row = conn.execute(
                "SELECT merged_text, recovered_segments FROM merge_results "
                "WHERE group_id = ? AND recovered_count > 0",
                (group_id,),
            ).fetchone()
            if row is None:
                return None

            segments = json.loads(row["recovered_segments"]) if row["recovered_segments"] else []
            if segment_index < 0 or segment_index >= len(segments):
                return None

            seg = segments[segment_index]
            if not isinstance(seg, dict):
                return None

            recovered_text = seg.get("text", "")
            source_doc_id = seg.get("source_doc_id", "")

            # Find surrounding unredacted context in the raw merged text
            merged_text = row["merged_text"] or ""
            search_context = ""
            if recovered_text and merged_text:
                # Strip <change><u>...</u></change> markup for plain-text search
                plain = re.sub(r"</?(?:change|u)>", "", merged_text)
                pos = plain.find(recovered_text)
                if pos < 0:
                    # Try normalised whitespace match
                    norm_rec = " ".join(recovered_text.split())
                    norm_plain = " ".join(plain.split())
                    pos = norm_plain.find(norm_rec)
                    plain = norm_plain
                if pos >= 0:
                    # Grab up to 40 chars before/after, skipping [REDACTED] markers
                    before = plain[:pos]
                    after = plain[pos + len(recovered_text):]
                    # Remove redaction markers from context
                    before = re.sub(r"\[REDACTED\]|\[b\(6\)\]|XXXXXXXXX", "", before).strip()
                    after = re.sub(r"\[REDACTED\]|\[b\(6\)\]|XXXXXXXXX", "", after).strip()
                    ctx_before = before[-40:].strip() if before else ""
                    ctx_after = after[:40].strip() if after else ""
                    search_context = f"{ctx_before} {recovered_text} {ctx_after}".strip()

            if not search_context:
                search_context = recovered_text

            # Look up source document details
            doc_row = conn.execute(
                "SELECT text_source, pdf_url, release_batch, original_filename, extracted_text "
                "FROM documents WHERE id = ?",
                (source_doc_id,),
            ).fetchone()

            has_pdf = False
            pdf_cached = False
            pdf_cache_path = None
            extracted_text = ""

            if doc_row:
                has_pdf = doc_row["text_source"] in _PDF_TEXT_SOURCES or bool(doc_row["pdf_url"])
                extracted_text = doc_row["extracted_text"] or ""
                if doc_row["release_batch"] and doc_row["original_filename"]:
                    cache_file = (
                        Path(self.config.pdf_cache_dir)
                        / doc_row["release_batch"]
                        / doc_row["original_filename"]
                    )
                    if cache_file.exists():
                        pdf_cached = True
                        pdf_cache_path = f"{doc_row['release_batch']}/{doc_row['original_filename']}"

            # Build a focused excerpt: ~500 chars before/after the recovered
            # passage in the source document, with the passage highlighted.
            # This is much more useful than showing the full 200KB+ source text
            # and trying to scroll to the right spot.
            highlighted_text = ""
            if extracted_text and recovered_text:
                pos = extracted_text.find(recovered_text)
                if pos < 0:
                    # Try normalized whitespace match
                    norm_rec = " ".join(recovered_text.split())
                    norm_ext = " ".join(extracted_text.split())
                    pos = norm_ext.find(norm_rec)
                    if pos >= 0:
                        # Map back to original positions approximately
                        extracted_text = norm_ext
                if pos >= 0:
                    # Extract surrounding context
                    start = max(0, pos - 500)
                    end = min(len(extracted_text), pos + len(recovered_text) + 500)
                    excerpt = extracted_text[start:end]
                    # Adjust recovered_text position within excerpt
                    rec_start = pos - start
                    before = html.escape(excerpt[:rec_start])
                    middle = html.escape(excerpt[rec_start:rec_start + len(recovered_text)])
                    after = html.escape(excerpt[rec_start + len(recovered_text):])
                    ellipsis_before = "..." if start > 0 else ""
                    ellipsis_after = "..." if end < len(extracted_text) else ""
                    highlighted_text = (
                        f'{ellipsis_before}{before}'
                        f'<mark class="recovered-inline">{middle}</mark>'
                        f'{after}{ellipsis_after}'
                    )
                else:
                    # Can't find passage — show first 1000 chars as fallback
                    highlighted_text = html.escape(extracted_text[:1000])
                    if len(extracted_text) > 1000:
                        highlighted_text += "..."
            elif extracted_text:
                highlighted_text = html.escape(extracted_text[:1000])
                if len(extracted_text) > 1000:
                    highlighted_text += "..."

            return {
                "source_doc_id": source_doc_id,
                "recovered_text": recovered_text,
                "search_context": search_context,
                "has_pdf": has_pdf,
                "pdf_cached": pdf_cached,
                "pdf_cache_path": pdf_cache_path,
                "pdf_url": doc_row["pdf_url"] if doc_row else None,
                "extracted_text": extracted_text,
                "highlighted_text": highlighted_text,
            }
        finally:
            self._release_db(conn)

    def get_member_text(self, group_id: int, doc_id: str) -> Optional[dict]:
        """Get full extracted text for a group member with recovered passages highlighted.

        Returns a dict with 'doc_id' and 'text_html', or None if doc_id is not
        a member of group_id.
        """
        conn = self._get_db()
        try:
            # 1. Verify membership
            membership = conn.execute(
                "SELECT 1 FROM match_group_members WHERE group_id = ? AND doc_id = ?",
                (group_id, doc_id),
            ).fetchone()
            if membership is None:
                return None

            # 2. Fetch extracted text
            doc_row = conn.execute(
                "SELECT extracted_text FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
            if doc_row is None:
                return None

            extracted = doc_row["extracted_text"] or ""
            if not extracted.strip():
                return {"doc_id": doc_id, "text_html": '<span style="color:var(--text-secondary);">No extracted text available for this document.</span>'}

            # 3. Truncate if over limit
            truncated = False
            if len(extracted) > self._MAX_MEMBER_TEXT_CHARS:
                cut = extracted.rfind(" ", self._MAX_MEMBER_TEXT_CHARS - 200, self._MAX_MEMBER_TEXT_CHARS)
                if cut < 0:
                    cut = self._MAX_MEMBER_TEXT_CHARS
                extracted = extracted[:cut]
                truncated = True

            # 4. Fetch recovered segments (no filter on recovered_count)
            seg_row = conn.execute(
                "SELECT recovered_segments FROM merge_results WHERE group_id = ?",
                (group_id,),
            ).fetchone()
            segments = []
            if seg_row and seg_row["recovered_segments"]:
                raw = json.loads(seg_row["recovered_segments"])
                for seg in raw:
                    if isinstance(seg, dict) and seg.get("text"):
                        segments.append(seg["text"])

            # 5. Find all highlight ranges (role-agnostic)
            ranges = []
            for seg_text in segments:
                # Try exact match first — find all occurrences
                found = False
                pos = extracted.find(seg_text)
                while pos >= 0:
                    ranges.append((pos, pos + len(seg_text)))
                    found = True
                    pos = extracted.find(seg_text, pos + len(seg_text))
                if not found:
                    # Exact match failed — try regex with flexible whitespace between words
                    words = seg_text.split()
                    if words:
                        pattern = r'\s+'.join(re.escape(w) for w in words)
                        for m in re.finditer(pattern, extracted):
                            ranges.append((m.start(), m.end()))

            # 6. Merge overlapping/adjacent ranges
            if ranges:
                ranges.sort()
                merged = [ranges[0]]
                for start, end in ranges[1:]:
                    if start <= merged[-1][1]:
                        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
                    else:
                        merged.append((start, end))
                ranges = merged

            # 7. Build HTML in one pass
            parts = []
            prev = 0
            for start, end in ranges:
                if start > prev:
                    parts.append(html.escape(extracted[prev:start]))
                parts.append('<mark class="recovered-inline">')
                parts.append(html.escape(extracted[start:end]))
                parts.append("</mark>")
                prev = end
            if prev < len(extracted):
                parts.append(html.escape(extracted[prev:]))

            text_html = "".join(parts)
            if truncated:
                text_html += (
                    '\n<div style="padding:0.5rem;color:var(--text-secondary);font-size:0.8rem;'
                    'border-top:1px solid var(--border);margin-top:0.5rem;">'
                    "Showing first ~100KB. View full text on document detail page.</div>"
                )

            return {"doc_id": doc_id, "text_html": text_html}
        finally:
            self._release_db(conn)

    def get_common_unredactions(
        self,
        min_occurrences: int = 2,
        min_words: int = 3,
        limit: int = 20,
    ) -> list[dict]:
        """Get most frequently recovered text strings.

        Results are cached for _COMMON_CACHE_TTL seconds to avoid
        the expensive json_each expansion on every page load.
        """
        now = time.monotonic()
        if (
            self._common_unredactions_cache is not None
            and (now - self._common_cache_time) < self._COMMON_CACHE_TTL
        ):
            return self._common_unredactions_cache[:limit]

        conn = self._get_db()
        try:
            # Limit to the 500 most-recovered groups to keep this fast on large datasets
            rows = conn.execute(
                "SELECT mr.group_id, value FROM "
                "(SELECT group_id, recovered_segments FROM merge_results "
                " WHERE recovered_count > 0 AND recovered_segments IS NOT NULL "
                " ORDER BY recovered_count DESC LIMIT 500) mr, "
                "json_each(mr.recovered_segments) "
                "WHERE value IS NOT NULL"
            ).fetchall()

            # Count distinct documents (group_ids) per recovered phrase.
            # We normalize whitespace for aggregation but keep one raw variant
            # so the search link uses text that matches the raw JSON column.
            doc_sets: dict[str, set] = {}
            raw_variants: dict[str, str] = {}
            for row in rows:
                segment = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                raw_text = segment.get("text", "") if isinstance(segment, dict) else str(segment)
                text = " ".join(raw_text.split()).strip()
                if not text:
                    continue
                if len(text.split()) < min_words:
                    continue
                if text not in doc_sets:
                    doc_sets[text] = set()
                    raw_variants[text] = raw_text.strip()
                doc_sets[text].add(row["group_id"])

            results = [
                {"text": text, "search_text": raw_variants[text], "count": len(group_ids)}
                for text, group_ids in doc_sets.items()
                if len(group_ids) >= min_occurrences
            ]
            results.sort(key=lambda x: x["count"], reverse=True)

            self._common_unredactions_cache = results
            self._common_cache_time = now
            return results[:limit]
        finally:
            self._release_db(conn)

    # --- Jobs ---

    def get_jobs(
        self,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> list[dict]:
        conn = self._get_db()
        try:
            where = "1=1"
            params = []
            if status:
                where = "status = ?"
                params.append(status)

            rows = conn.execute(
                f"SELECT * FROM jobs WHERE {where} "
                f"ORDER BY job_id DESC LIMIT ? OFFSET ?",
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            self._release_db(conn)

    # --- Subprocess Commands ---

    def run_command(self, args: list[str]) -> dict:
        """Run an unobfuscator CLI command."""
        cmd = shlex.split(self.config.unobfuscator_bin) + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.subprocess_timeout_seconds,
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": f"Timeout after {self.config.subprocess_timeout_seconds}s",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": f"Unobfuscator not found at: {self.config.unobfuscator_bin}",
            }

    def get_daemon_status(self) -> str:
        """Check if the daemon is running."""
        pid_file = Path(self.config.unobfuscator_path) / ".unobfuscator.pid"
        if not pid_file.exists():
            return "stopped"
        try:
            pid = int(pid_file.read_text().strip())
            # Check if process is alive
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True,
                )
                return "running" if str(pid) in result.stdout else "stopped"
            else:
                import signal
                os.kill(pid, 0)  # Doesn't actually kill, just checks
                return "running"
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            return "stopped"

    def start_daemon(self) -> dict:
        return self.run_command(["start"])

    def stop_daemon(self) -> dict:
        if platform.system() == "Windows":
            pid_file = Path(self.config.unobfuscator_path) / ".unobfuscator.pid"
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text().strip())
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True,
                        timeout=30,
                    )
                    pid_file.unlink(missing_ok=True)
                    return {"success": True, "stdout": "Daemon stopped"}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            return {"success": True, "stdout": "Daemon not running"}
        return self.run_command(["stop"])

    def restart_daemon(self) -> dict:
        stop_result = self.stop_daemon()
        combined = (
            stop_result.get("stdout", "")
            + stop_result.get("stderr", "")
            + stop_result.get("error", "")
        )
        if not stop_result.get("success", False) and "not running" not in combined.lower():
            return {
                "success": False,
                "error": f"Stop failed: {stop_result.get('error', stop_result.get('stderr', ''))}",
            }
        return self.start_daemon()

    def search(self, **kwargs) -> dict:
        args = ["search"]
        if kwargs.get("person"):
            args.extend(["--person", kwargs["person"]])
        if kwargs.get("batch"):
            args.extend(["--batch", kwargs["batch"]])
        if kwargs.get("doc_id"):
            args.extend(["--doc", kwargs["doc_id"]])
        if kwargs.get("query"):
            args.append(kwargs["query"])
        return self.run_command(args)

    # --- Log Tailing ---

    def read_log_lines(self, n: int = 50, level: Optional[str] = None) -> list[str]:
        """Read last n lines from the log file.

        Uses a seek-from-end approach to avoid reading the entire file into
        memory, which matters for large log files.
        """
        log_path = Path(self.config.log_path)
        if not log_path.exists():
            return []

        # When filtering by level we may need many more raw lines to find n matches
        raw_needed = n * 10 if level else n
        chunk_size = 8192
        lines: list[str] = []

        max_total_bytes = 10 * 1024 * 1024  # 10 MB cap
        total_read = 0

        with open(log_path, "r") as f:
            f.seek(0, 2)  # seek to end
            remaining = f.tell()
            buffer = ""
            while remaining > 0 and len(lines) < raw_needed and total_read < max_total_bytes:
                read_size = min(chunk_size, remaining, max_total_bytes - total_read)
                remaining -= read_size
                f.seek(remaining)
                chunk = f.read(read_size)
                total_read += read_size
                buffer = chunk + buffer
                lines = buffer.splitlines()
            # If the entire file is smaller than what we need, lines already has everything

        if level:
            level_upper = level.upper()
            level_re = re.compile(r'\b' + re.escape(level_upper) + r'\b')
            lines = [line for line in lines if level_re.search(line[:80])]
        return lines[-n:]

    def get_log_position(self) -> int:
        """Get current log file size for tailing."""
        log_path = Path(self.config.log_path)
        if not log_path.exists():
            return 0
        return log_path.stat().st_size

    def read_log_from(self, position: int, max_bytes: int = 1_048_576) -> tuple[list[str], int]:
        """Read new log lines from a given byte position.

        At most *max_bytes* (default 1 MB) are read per call to avoid
        unbounded memory usage on very large log deltas.
        """
        log_path = Path(self.config.log_path)
        if not log_path.exists():
            return [], 0
        current_size = log_path.stat().st_size
        if current_size <= position:
            return [], current_size
        with open(log_path, "r") as f:
            f.seek(position)
            new_content = f.read(max_bytes)
            actual_position = f.tell()
        new_lines = new_content.splitlines()
        return new_lines, actual_position

    # --- Text Formatting ---

    @staticmethod
    def format_merged_text(text: str, segments: list = None) -> str:
        """Convert merged text to safe HTML for display.
        Escapes all HTML, then converts known Unobfuscator markup back to styled elements.

        When *segments* is provided (list of dicts with 'text' and 'source_doc_id'),
        recovered passages are annotated with data-segment-index and data-source-doc
        attributes to support click-to-source jumping.
        """
        # Build a lookup of normalised segment text -> (index, source_doc_id)
        seg_lookup = {}
        if segments:
            for idx, seg in enumerate(segments):
                if isinstance(seg, dict) and seg.get("text"):
                    norm = " ".join(seg["text"].split())
                    seg_lookup[norm] = (idx, seg.get("source_doc_id", ""))

        def _match_segment(recovered_text: str) -> str:
            """Return data attribute string if recovered text matches a segment.
            recovered_text may be HTML-escaped (from the regex match on escaped text),
            so we unescape it before comparing against the raw segment text."""
            # Unescape HTML entities so we can compare against raw segment text
            unescaped = html.unescape(recovered_text)
            norm = " ".join(unescaped.split())
            if not norm:
                return ""
            # Exact match
            if norm in seg_lookup:
                idx, doc_id = seg_lookup[norm]
                return f' data-segment-index="{idx}" data-source-doc="{html.escape(doc_id)}" title="Click to view source document"'
            # Substring match: find longest segment that contains this text or vice versa
            best = None
            best_len = 0
            for seg_norm, (idx, doc_id) in seg_lookup.items():
                if norm in seg_norm or seg_norm in norm:
                    if len(seg_norm) > best_len:
                        best = (idx, doc_id)
                        best_len = len(seg_norm)
            if best:
                idx, doc_id = best
                return f' data-segment-index="{idx}" data-source-doc="{html.escape(doc_id)}" title="Click to view source document"'
            return ""

        # Escape everything first
        escaped = html.escape(text)

        # <change><u>recovered text</u></change> → highlighted span
        def _replace_recovered(m: re.Match) -> str:
            inner = m.group(1)
            attrs = _match_segment(inner) if segments else ""
            return f'<mark class="recovered-inline"{attrs}>{inner}</mark>'

        escaped = _RE_CHANGE_U.sub(_replace_recovered, escaped)
        # <change> without <u> (partial markup)
        escaped = _RE_CHANGE_BARE.sub("", escaped)
        escaped = _RE_U_BARE.sub("", escaped)

        # Fallback: if no <change><u> markup was present but segments exist,
        # search for segment text directly in the escaped text and wrap matches.
        # This handles merged texts that contain recovered content inline
        # without Unobfuscator markup (common for large concatenated merges).
        if segments and "recovered-inline" not in escaped:
            for idx, seg in enumerate(segments):
                if not isinstance(seg, dict) or not seg.get("text"):
                    continue
                seg_text = seg["text"].strip()
                if len(seg_text) < 10:
                    continue
                # Use a unique-enough prefix (first 60 chars) to find the segment
                search_key = html.escape(seg_text[:60])
                if search_key in escaped:
                    doc_id = html.escape(seg.get("source_doc_id", ""))
                    tag_open = (
                        f'<mark class="recovered-inline" '
                        f'data-segment-index="{idx}" '
                        f'data-source-doc="{doc_id}" '
                        f'title="Click to view source document">'
                    )
                    # Wrap just the first occurrence of the full escaped segment text
                    full_escaped = html.escape(seg_text)
                    escaped = escaped.replace(
                        full_escaped, f"{tag_open}{full_escaped}</mark>", 1
                    )
        # Restore table markup that was originally inserted by the Unobfuscator
        # tool. We only restore tags that appear in a valid table structure
        # (table containing tr/th/td rows) to avoid injecting HTML if
        # document text happens to contain literal "<table>" strings.
        # Uses string search instead of regex to avoid catastrophic
        # backtracking on malformed/unclosed table markup.
        parts = []
        search_start = 0
        while True:
            open_idx = escaped.find(_TABLE_OPEN, search_start)
            if open_idx == -1:
                break
            close_idx = escaped.find(_TABLE_CLOSE, open_idx + len(_TABLE_OPEN))
            if close_idx == -1:
                break  # Unclosed table — skip, don't hang
            inner = escaped[open_idx + len(_TABLE_OPEN):close_idx]
            # Only restore if inner contains tr/th/td tags
            if _TABLE_TAG_RE.search(inner):
                inner = inner.replace("&lt;tr&gt;", "<tr>")
                inner = inner.replace("&lt;/tr&gt;", "</tr>")
                inner = inner.replace("&lt;th&gt;", "<th>")
                inner = inner.replace("&lt;/th&gt;", "</th>")
                inner = inner.replace("&lt;td&gt;", "<td>")
                inner = inner.replace("&lt;/td&gt;", "</td>")
                parts.append(escaped[search_start:open_idx])
                parts.append(f'<table class="data-table" style="margin:0.5rem 0;">{inner}</table>')
            else:
                parts.append(escaped[search_start:close_idx + len(_TABLE_CLOSE)])
            search_start = close_idx + len(_TABLE_CLOSE)
        parts.append(escaped[search_start:])
        escaped = "".join(parts)
        return escaped

    # --- PDF File Access ---

    def get_pdf_path(self, pdf_type: str, *path_parts: str) -> Optional[Path]:
        """Get path to a PDF file. pdf_type is 'cache', 'output', or 'summary'."""
        if pdf_type == "cache":
            base = Path(self.config.pdf_cache_dir)
        elif pdf_type == "output":
            base = Path(self.config.output_dir)
        elif pdf_type == "summary":
            base = Path(self.config.output_dir)
        else:
            return None

        full_path = base / "/".join(path_parts)
        # Security: ensure path stays within base directory
        try:
            full_path.resolve().relative_to(base.resolve())
        except ValueError:
            return None

        if full_path.exists() and full_path.suffix.lower() == ".pdf":
            return full_path
        return None

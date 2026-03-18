import html
import json
import os
import platform
import sqlite3
import subprocess
import re
import time
from pathlib import Path
from typing import Optional

from teredacta.config import TeredactaConfig

# Pre-compiled regexes for format_merged_text
_RE_CHANGE_U = re.compile(
    r"&lt;change&gt;&lt;u&gt;(.*?)&lt;/u&gt;&lt;/change&gt;", re.DOTALL
)
_RE_CHANGE_BARE = re.compile(r"&lt;/?change&gt;")
_RE_U_BARE = re.compile(r"&lt;/?u&gt;")


def calc_total_pages(total: int, per_page: int) -> int:
    return max(1, (total + per_page - 1) // per_page)


class UnobInterface:
    """Single interface to all Unobfuscator interactions."""

    # TTL for common unredactions cache (seconds)
    _COMMON_CACHE_TTL = 300  # 5 minutes
    _STATS_CACHE_TTL = 10  # seconds

    _INDEXES = [
        ("idx_docs_text_processed", "documents", "text_processed"),
        ("idx_docs_pdf_processed", "documents", "pdf_processed"),
        ("idx_docs_original_filename", "documents", "original_filename"),
        ("idx_docs_text_id", "documents", "text_processed, id"),
        ("idx_docs_pdf_id", "documents", "pdf_processed, id"),
        ("idx_docs_source_id", "documents", "source, id"),
    ]

    def __init__(self, config: TeredactaConfig):
        self.config = config
        self._common_unredactions_cache = None
        self._common_cache_time: float = 0.0
        self._stats_cache: Optional[dict] = None
        self._stats_cache_time: float = 0.0  # monotonic

    @staticmethod
    def _estimate_total(rows: list, per_page: int, offset: int) -> tuple[list, int]:
        """Trim fetch+1 rows and estimate total without COUNT."""
        has_more = len(rows) > per_page
        rows = rows[:per_page]
        return rows, offset + len(rows) + (1 if has_more else 0)

    def _get_db(self) -> sqlite3.Connection:
        db_path = Path(self.config.db_path)
        if not db_path.exists():
            raise FileNotFoundError(
                f"Database not found at {db_path}. "
                "Check your TEREDACTA configuration."
            )
        conn = sqlite3.connect(
            str(db_path),
            timeout=5.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def ensure_indexes(self):
        """Create performance indexes if missing (must run before query_only)."""
        db_path = Path(self.config.db_path)
        if not db_path.exists():
            return
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        conn.execute("PRAGMA busy_timeout = 10000")
        for idx_name, table, column in self._INDEXES:
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})"
            )
        conn.commit()
        conn.close()

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
            conn.close()

    # --- Documents ---

    def get_documents(
        self,
        page: int = 1,
        per_page: int = 50,
        search: Optional[str] = None,
        source: Optional[str] = None,
        batch: Optional[str] = None,
        has_redactions: Optional[bool] = None,
        stage: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        conn = self._get_db()
        try:
            offset = (page - 1) * per_page
            cols = ("id, source, release_batch, original_filename, "
                    "page_count, description, text_processed, pdf_processed")

            # Search uses GLOB (case-sensitive) for index-backed prefix
            # matching on original_filename and id. UNION merges results
            # across case variants (upper, lower, original).
            if search:
                # Build deduplicated set of GLOB patterns
                patterns = list(dict.fromkeys([
                    search.upper() + "*",
                    search.lower() + "*",
                    search + "*",
                ]))
                # UNION across both columns with each unique pattern
                parts = []
                params_search = []
                for col in ("original_filename", "id"):
                    for pat in patterns:
                        parts.append(f"SELECT {cols} FROM documents WHERE {col} GLOB ?")
                        params_search.append(pat)
                query = " UNION ".join(parts) + " ORDER BY id LIMIT ? OFFSET ?"
                rows = conn.execute(
                    query, params_search + [per_page + 1, offset]
                ).fetchall()
                rows, total = self._estimate_total(rows, per_page, offset)
                docs = [dict(row) for row in rows]
                return docs, total

            where_clauses = []
            params: list = []
            if source:
                where_clauses.append("source = ?")
                params.append(source)
            if batch:
                where_clauses.append("release_batch = ?")
                params.append(batch)
            if has_redactions is True:
                where_clauses.append(
                    "(extracted_text LIKE '%[REDACTED]%' OR extracted_text LIKE '%[b(6)]%' "
                    "OR extracted_text LIKE '%XXXXXXXXX%')"
                )
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
            conn.close()

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
            conn.close()

    # --- Match Groups ---

    def get_match_groups(
        self,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[dict], int]:
        conn = self._get_db()
        try:
            total = conn.execute("SELECT COUNT(*) FROM match_groups").fetchone()[0]
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
            conn.close()

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
            conn.close()

    # --- Recoveries ---

    def get_recoveries(
        self,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[dict], int]:
        conn = self._get_db()
        try:
            where = "mr.recovered_count > 0"
            params = []
            if search:
                # Search within recovered_segments JSON so we only match text
                # that was actually unredacted, not text already in the document
                where += " AND mr.recovered_segments LIKE ?"
                params.append(f"%{search}%")

            total = conn.execute(
                f"SELECT COUNT(*) FROM merge_results mr WHERE {where}",
                params,
            ).fetchone()[0]

            rows = conn.execute(
                f"SELECT mr.group_id, mr.recovered_count, mr.total_redacted, "
                f"mr.soft_recovered_count, mr.source_doc_ids, mr.output_generated, "
                f"mr.created_at "
                f"FROM merge_results mr WHERE {where} "
                f"ORDER BY mr.recovered_count DESC "
                f"LIMIT ? OFFSET ?",
                params + [per_page, (page - 1) * per_page],
            ).fetchall()
            return [dict(row) for row in rows], total
        finally:
            conn.close()

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
            # Pre-render merged text as safe HTML
            result["merged_text_html"] = self.format_merged_text(result.get("merged_text") or "")

            # Get group members with PDF cache paths.
            # Limit to source docs + top donors by similarity to avoid
            # rendering thousands of rows for large groups.
            source_ids = result.get("source_doc_ids") or []
            placeholders = ",".join("?" for _ in source_ids) if source_ids else "''"
            members = conn.execute(
                f"SELECT mgm.doc_id, mgm.similarity, d.original_filename, d.source, "
                f"d.release_batch "
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
                # Compute cache PDF path: {release_batch}/{original_filename}
                if m["release_batch"] and m["original_filename"]:
                    cache_path = Path(self.config.pdf_cache_dir) / m["release_batch"] / m["original_filename"]
                    member["pdf_cache_path"] = f"{m['release_batch']}/{m['original_filename']}" if cache_path.exists() else None
                else:
                    member["pdf_cache_path"] = None
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
            conn.close()

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

            # Count distinct documents (group_ids) per recovered phrase
            doc_sets: dict[str, set] = {}
            for row in rows:
                segment = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                text = segment.get("text", "") if isinstance(segment, dict) else str(segment)
                text = " ".join(text.split()).strip()
                if not text:
                    continue
                if len(text.split()) < min_words:
                    continue
                if text not in doc_sets:
                    doc_sets[text] = set()
                doc_sets[text].add(row["group_id"])

            results = [
                {"text": text, "count": len(group_ids)}
                for text, group_ids in doc_sets.items()
                if len(group_ids) >= min_occurrences
            ]
            results.sort(key=lambda x: x["count"], reverse=True)

            self._common_unredactions_cache = results
            self._common_cache_time = now
            return results[:limit]
        finally:
            conn.close()

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
            conn.close()

    # --- Subprocess Commands ---

    def run_command(self, args: list[str]) -> dict:
        """Run an unobfuscator CLI command."""
        cmd = self.config.unobfuscator_bin.split() + args
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
        if not stop_result.get("success", False) and "not running" not in stop_result.get("stdout", ""):
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
        """Read last n lines from the log file."""
        log_path = Path(self.config.log_path)
        if not log_path.exists():
            return []
        lines = log_path.read_text().splitlines()
        if level:
            level_upper = level.upper()
            lines = [l for l in lines if level_upper in l]
        return lines[-n:]

    def get_log_position(self) -> int:
        """Get current log file size for tailing."""
        log_path = Path(self.config.log_path)
        if not log_path.exists():
            return 0
        return log_path.stat().st_size

    def read_log_from(self, position: int) -> tuple[list[str], int]:
        """Read new log lines from a given byte position."""
        log_path = Path(self.config.log_path)
        if not log_path.exists():
            return [], 0
        current_size = log_path.stat().st_size
        if current_size <= position:
            return [], current_size
        with open(log_path, "r") as f:
            f.seek(position)
            new_content = f.read()
        new_lines = new_content.splitlines()
        return new_lines, current_size

    # --- Text Formatting ---

    @staticmethod
    def format_merged_text(text: str) -> str:
        """Convert merged text to safe HTML for display.
        Escapes all HTML, then converts known Unobfuscator markup back to styled elements.
        """
        # Escape everything first
        escaped = html.escape(text)
        # <change><u>recovered text</u></change> → highlighted span
        escaped = _RE_CHANGE_U.sub(
            r'<mark class="recovered-inline">\1</mark>', escaped
        )
        # <change> without <u> (partial markup)
        escaped = _RE_CHANGE_BARE.sub("", escaped)
        escaped = _RE_U_BARE.sub("", escaped)
        # Render table markup
        escaped = escaped.replace("&lt;table&gt;", '<table class="data-table" style="margin:0.5rem 0;">')
        escaped = escaped.replace("&lt;/table&gt;", "</table>")
        escaped = escaped.replace("&lt;tr&gt;", "<tr>")
        escaped = escaped.replace("&lt;/tr&gt;", "</tr>")
        escaped = escaped.replace("&lt;th&gt;", "<th>")
        escaped = escaped.replace("&lt;/th&gt;", "</th>")
        escaped = escaped.replace("&lt;td&gt;", "<td>")
        escaped = escaped.replace("&lt;/td&gt;", "</td>")
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

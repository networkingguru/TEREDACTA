# Performance Optimization Design

**Date:** 2026-04-02
**Problem:** Server is painfully slow on cold cache and for any text search or filter involving full table scans on a 6.3GB SQLite database with 1.4M documents.

## Diagnosis

Benchmarking revealed:

| Page | Cold Cache | Warm Cache |
|------|-----------|------------|
| `/` (Explore) | 28.6s | 0.2s |
| `/documents` | 4.3s | 0.07s |
| `/highlights` | 0.3s | 0.15s |
| `/recoveries` | 0.19s | 0.21s |
| `/summary` | 0.01s | 0.003s |

Additional findings:
- **GLOB search** (e.g. "CIA") on `original_filename` and `id` columns: **190 seconds** — full table scan across 1.4M rows
- **`has_redactions` filter**: 2.7s warm — scans `extracted_text` with `LIKE '%[REDACTED]%'`
- **Cold cache penalty**: The 6.3GB DB file must be paged into OS memory from disk; first access to large tables triggers sequential reads
- **`entity_index.get_status()`**: Opens a second SQLite connection to the main DB on every Explore page load for staleness check

## Root Causes

1. **No precomputed `has_redactions` column** — every filter request scans the full `extracted_text` blob for every document
2. **GLOB-based search** — case-insensitive substring search via GLOB does full table scans; no FTS index exists
3. **Cold cache penalty** — 6.3GB DB; OS page cache is the only "warm-up" mechanism
4. **`entity_index.get_status()`** — opens a separate connection to the main DB every page load to check `MAX(created_at) FROM merge_results`
5. **`get_common_unredactions()`** — `json_each()` expansion over 500 rows of JSON on cache miss

## Approach Selected: Precomputed Columns + FTS5 + Startup Warm-up

### Alternative approaches considered:

**A. Precomputed columns only (no FTS)** — Add `has_redactions` boolean column, replace GLOB with `LIKE` + `COLLATE NOCASE`. Simple, handles the `has_redactions` bottleneck, but LIKE substring search is still O(n) on 1.4M rows (~10-20s).

**B. Full FTS5 index** — Create FTS5 virtual table over `extracted_text`, `original_filename`, `id`. Handles all search cases with sub-second performance. However, FTS5 index on extracted_text would add ~2-4GB to disk and take significant time to build.

**C. Precomputed columns + targeted FTS5 + warm-up (recommended)** — Add `has_redactions` column. Add FTS5 only on `original_filename` and `id` (small columns, fast to build). Use `mmap_size` pragma for warm-up. Cache `entity_index` staleness check. This gives the best cost/benefit ratio.

### Recommendation: Approach C

## Design

### 1. Precomputed `has_redactions` column

Add a boolean column `has_redactions` to the `documents` table. Backfill with a single UPDATE:

```sql
ALTER TABLE documents ADD COLUMN has_redactions INTEGER DEFAULT 0;
UPDATE documents SET has_redactions = 1
WHERE extracted_text LIKE '%[REDACTED]%'
   OR extracted_text LIKE '%[b(6)]%'
   OR extracted_text LIKE '%XXXXXXXXX%';
CREATE INDEX idx_docs_has_redactions ON documents(has_redactions);
```

Then change `get_documents()` to filter on `has_redactions = 1` instead of scanning `extracted_text`.

The Unobfuscator daemon (which populates these rows) should set `has_redactions` when it writes `extracted_text`. This is outside TEREDACTA's scope — TEREDACTA reads this DB read-only. So we'll run the backfill as a one-time migration and add a periodic re-check (or a migration on startup that processes any NULL rows).

**Important:** The main DB (`unobfuscator.db`) is owned by the Unobfuscator process. TEREDACTA opens it read-only. The migration must be run separately or via a new `teredacta migrate` CLI command that opens the DB in write mode specifically for this purpose.

### 2. FTS5 index on `original_filename` and `id`

Create an FTS5 virtual table for document search fields only (not `extracted_text` — that would be too large):

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    id, original_filename, content='documents', content_rowid='rowid'
);
INSERT INTO documents_fts(documents_fts) VALUES('rebuild');
```

This will be small (~50-100MB for 1.4M rows of short text fields) and fast to build (~30-60 seconds).

Replace the GLOB-based search in `get_documents()` with:

```sql
SELECT {cols} FROM documents WHERE rowid IN (
    SELECT rowid FROM documents_fts WHERE documents_fts MATCH ?
)
```

FTS5 supports prefix queries (`term*`) for substring-like behavior. For exact substring matching, we can use `LIKE` as a secondary filter on the small result set.

**Limitation:** FTS5 is word-based, not substring-based. A search for "CIA" will match documents with "CIA" as a word but not "SPECIAL" containing "CIA". The current GLOB search does match substrings. This is an acceptable trade-off — word-based search is what users typically want, and it's what the entity search already does.

**Fallback strategy:** Use FTS5 as the primary search. If FTS5 returns zero results, fall back to `LIKE '%term%' COLLATE NOCASE` on `original_filename` and `id` only (these columns are small and indexed, so LIKE on them is fast — unlike GLOB which couldn't use the index). This preserves substring matching as a fallback without the 190-second full table scan.

### 3. Startup DB warm-up via `mmap_size`

Set `PRAGMA mmap_size` on the connection pool to memory-map the database file. This tells SQLite to use the OS's memory-mapped I/O, which:
- Avoids the cold-cache penalty by letting the OS prefault pages
- Reduces syscall overhead for reads
- Works within the existing read-only connection pool

```python
conn.execute("PRAGMA mmap_size = 8589934592")  # 8GB — larger than DB, maps whole file
```

Add this to the `ConnectionPool` initialization. The OS will lazily page in data as needed, but subsequent accesses will be fast.

Additionally, add an optional startup warm-up that touches the key tables:

```python
def warm_up(conn):
    conn.execute("SELECT COUNT(*) FROM documents")
    conn.execute("SELECT COUNT(*) FROM merge_results")
    conn.execute("SELECT COUNT(*) FROM match_group_members")
```

This forces the OS to page in the index pages for these tables during startup rather than on first user request.

### 4. Cache `entity_index.get_status()` staleness check

The Explore page calls `entity_index.get_status(unob_db_path=config.db_path)` which opens a new connection to the main DB every time to check `MAX(created_at) FROM merge_results`. Cache this result for 60 seconds:

```python
def get_status(self, unob_db_path=None):
    now = time.monotonic()
    if self._status_cache and (now - self._status_cache_time) < 60:
        return self._status_cache
    # ... existing logic ...
    self._status_cache = result
    self._status_cache_time = now
    return result
```

### 5. `get_match_groups` COUNT optimization

`get_match_groups()` does `SELECT COUNT(*) FROM match_groups` which took 0.8s. Cache this like `get_stats()` already does:

```python
# Use cached count, refresh every 30s
if self._match_groups_count_cache is None or (now - self._match_groups_count_time) > 30:
    self._match_groups_count_cache = conn.execute("SELECT COUNT(*) FROM match_groups").fetchone()[0]
    self._match_groups_count_time = now
```

## Migration Strategy

Since TEREDACTA opens the DB read-only, we need a `teredacta migrate` CLI command:

1. Opens the DB in write mode
2. Adds `has_redactions` column if missing
3. Backfills `has_redactions` from `extracted_text` (batch UPDATE, ~30-60s)
4. Creates FTS5 table and populates it (~30-60s)
5. Creates any missing indexes

This command is idempotent — safe to run multiple times. The backfill UPDATE only touches rows where `has_redactions IS NULL`.

On subsequent app starts, `ensure_indexes()` already runs — we extend it to also verify the FTS5 table exists and warn if not.

## Files to Change

- `teredacta/unob.py` — `get_documents()` search/filter rewrite, `get_match_groups()` count cache, add `mmap_size` pragma, warm-up
- `teredacta/db_pool.py` — Add `mmap_size` pragma to connection init
- `teredacta/entity_index.py` — Cache `get_status()` result
- `teredacta/__main__.py` — Add `teredacta migrate` CLI command
- `teredacta/config.py` — No changes needed

## Testing Strategy

- Profile before/after on cold and warm cache for all pages
- Verify `has_redactions` filter returns same results as `LIKE` scan
- Verify FTS5 search returns relevant results for common search terms
- Verify migration is idempotent
- Verify read-only connections still work after migration
- Stress test with concurrent requests during migration

## Risk Assessment

- **Migration on 6.3GB DB**: The backfill UPDATE and FTS5 rebuild will take 1-2 minutes and lock the DB for writes. The Unobfuscator daemon should be stopped during migration. TEREDACTA's read-only connections will continue working (SQLite WAL mode allows concurrent readers).
- **FTS5 sync**: The FTS5 content table uses `content='documents'` which means it must be manually kept in sync when new documents are added. Since TEREDACTA doesn't write documents, this only matters when the Unobfuscator adds new batches — the migration command handles the rebuild.
- **Disk space**: FTS5 index on `id` + `original_filename` will add ~50-100MB. The `has_redactions` column adds negligible space.

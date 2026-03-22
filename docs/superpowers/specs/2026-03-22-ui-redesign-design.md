# TEREDACTA UI Redesign — Design Spec

## Overview

Restructure TEREDACTA from an admin-oriented pipeline monitor into a discovery-first investigative tool, while preserving all existing functionality for admin users. Three major improvements:

1. **Entity graph explorer** — interactive, sliding three-column interface for discovering connections between people, organizations, locations, and documents
2. **Redaction jumping with synchronized source view** — click any recovered passage to see the source document with the redaction location highlighted
3. **Role-appropriate navigation** — researcher pages first, admin pages tucked behind a dropdown

## Navigation & Page Structure

### New nav bar

```
TEREDACTA  |  Explore  Highlights  Recoveries  Documents  Summary  |  Admin ▾
```

- First 5 links are always visible (public/researcher pages)
- "Admin" appears only when `is_admin` is true, as a dropdown or link to `/admin/`
- Admin section contains: Dashboard (pipeline stats), Groups, Queue, Config, Logs, Downloads

### Router changes

Create a new `explore.py` router that owns `/`. The existing `dashboard.py` router is remounted under `/admin/` prefix (its `/` route becomes `/admin/`, `/stats-fragment` becomes `/admin/stats-fragment`).

**SSE endpoints** (`/sse/stats`, `/sse/daemon-status`) remain at the root level (no prefix) since the daemon status indicator in the nav bar is shown to all users and must be accessible without admin auth. These stay on a small unprefixed SSE router or remain on `dashboard.py` with those specific routes excluded from the prefix.

### Page mapping

| URL | Page | Audience | Status |
|-----|------|----------|--------|
| `/` | Explore (entity graph) | Everyone | **New** |
| `/highlights/` | Highlights (curated findings) | Everyone | **New** |
| `/recoveries/` | Recoveries (search + detail) | Everyone | Enhanced |
| `/documents/` | Documents (search + detail) | Everyone | Enhanced |
| `/summary/` | Summary report | Everyone | Unchanged |
| `/admin/` | Admin dashboard (pipeline stats) | Admin | Relocated from `/` |
| `/admin/groups/` | Match groups | Admin | Relocated from `/groups/` |
| `/admin/queue/` | Job queue | Admin | Relocated from `/queue/` |
| `/admin/config` | Configuration | Admin | Unchanged |
| `/admin/logs` | Log viewer | Admin | Unchanged |
| `/admin/downloads` | Dataset downloads | Admin | Unchanged |

### Redirects

Wildcard redirects for old URLs:
- `/groups/{path:path}` → 301 → `/admin/groups/{path}`
- `/queue/{path:path}` → 301 → `/admin/queue/{path}`

This covers both list pages and detail pages (e.g., `/groups/8848` → `/admin/groups/8848`).

## Entity Index

### Storage

A TEREDACTA-side SQLite database (separate from Unobfuscator's DB, located at `~/.teredacta/entities.db` or next to the TEREDACTA config). Three tables:

```sql
entities (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- person, org, location, email, phone
    occurrence_count INTEGER DEFAULT 0,
    document_count INTEGER DEFAULT 0,  -- precomputed for display
    UNIQUE(name, type)
)

entity_mentions (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER REFERENCES entities(id),
    group_id INTEGER NOT NULL,
    segment_index INTEGER,  -- index into recovered_segments JSON array for this group_id
    snippet TEXT  -- surrounding context, ~100 chars
)

entity_links (
    entity_a_id INTEGER REFERENCES entities(id),
    entity_b_id INTEGER REFERENCES entities(id),
    co_occurrence_count INTEGER DEFAULT 0,
    shared_group_ids TEXT,  -- JSON array
    PRIMARY KEY (entity_a_id, entity_b_id)
)
```

Indexes on: `entities(type, occurrence_count)`, `entity_mentions(entity_id)`, `entity_mentions(group_id)`, `entity_links(entity_a_id)`, `entity_links(entity_b_id)`.

`occurrence_count` and `document_count` are precomputed during the index build so the Explore page never needs to aggregate at query time.

### Extraction

Triggered via admin action (`POST /admin/entity-index/build`, admin-only + CSRF protected) or auto-triggered on first visit to Explore if the index doesn't exist. Scans `recovered_segments` JSON from all groups with `recovered_count > 0`.

**Build endpoint:** `POST /admin/entity-index/build` — requires admin auth + CSRF token. Returns an HTMX fragment showing build progress/completion. A "Build Entity Index" / "Rebuild Entity Index" button on the admin dashboard triggers this.

**Regex patterns:**

- **People:** Pattern `\b[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+(?:\s+(?:Jr|Sr|III?|IV)\.?)?\b` — handles "Leon Black", "J. Smith", "Alan Dershowitz Jr." All-caps text (common in legal docs like "JEFFREY EPSTEIN") is case-normalized before matching. Filtered against a stop list including: common legal phrases ("United States", "Southern District", "Circuit Court"), month+day patterns, document labels ("Page Break", "Case Number").
- **Organizations:** Known list (FBI, SDNY, DOJ, USAO, JPMorgan, SEC, BOP, CART, BRG, IRS, etc.) matched as whole words. Plus parenthetical patterns: `(USANYS)`, `(NY) (FBI)`, `(CRM)`.
- **Locations:** Known list (Mar-a-Lago, Palm Beach, Virgin Islands, New York, Manhattan, New Mexico, etc.) matched as whole words.
- **Emails:** `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`
- **Phones:** `(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}`

The entity index quality can be iteratively improved post-launch since it's a rebuildable cache — the known lists and stop lists can grow over time without any schema or architectural changes.

Co-occurrence links are computed per-group: if entity A and entity B both appear in segments from the same `group_id`, they get a link with that group_id added to `shared_group_ids`.

### Staleness detection

Compare `MAX(created_at)` from Unobfuscator's `merge_results` table against the entity index build timestamp (stored in the entity DB as a metadata row). Unobfuscator inserts new merge results rather than updating existing ones, so `MAX(created_at)` reliably indicates when new data arrived.

### Admin stats

The admin dashboard gets a new "Entity Index" stat card showing:
- Entity count by type (people: N, orgs: N, etc.)
- Total entity mentions
- Total co-occurrence links
- Last built timestamp
- Build/Rebuild button
- Status indicator (not built / building / ready / stale)

## Explore Page (Entity Graph)

Three-column sliding layout. This is the home page (`/`).

### Architecture note

This page is JS-heavy. HTMX is used for the initial page load and entity list filtering, but the column slide and preview interactions use custom JavaScript with `fetch()` calls to HTML fragment endpoints. This is architecturally different from the rest of the app's HTMX-partial pattern but necessary for the smooth slide animation, breadcrumb history, and `pushState` URL management. The JS is contained in a single `explore.js` file.

### API endpoints

All return HTML fragments (consistent with HTMX patterns elsewhere):

- `GET /api/entities?type=&filter=&page=` — paginated entity list, returns `<div>` with entity items
- `GET /api/entities/{id}/connections` — connections for an entity (recoveries, linked entities, documents), returns `<div>` with connection items
- `GET /api/preview/recovery/{group_id}` — recovery snippet preview, returns `<div>` with highlighted text
- `GET /api/preview/document/{doc_id}` — document text excerpt preview, returns `<div>` with text
- `GET /api/preview/entity/{id}` — entity summary card, returns `<div>` with stats

These endpoints read from the entity index DB and Unobfuscator DB (read-only). No admin auth required.

### Left column: Entity list
- Filterable text input at top with hint text: `Filter by name`
- Type filter tabs: All | People | Orgs | Locations | Emails | Phones
- Scrollable list sorted by occurrence count (descending)
- Each entry shows: entity name, type badge with hover help, occurrence count
- Clicking an entity selects it and populates the middle column
- Hover help on type badges explains what each type means (e.g., "Person — named individual found in recovered text")

### Middle column: Connections
- Header showing selected entity name, type badge, summary stats ("Found in 8 recoveries, 23 documents")
- Scrollable list of connections, color-coded:
  - **Green** (recoveries): recovery group_id, recovered_count, first ~80 chars of the most substantive segment. Hover help: "Recovered redaction — click to preview"
  - **Orange** (entities): connected entity name, co-occurrence count, sample context. Hover help: "Related entity — click to explore connections"
  - **Blue** (documents): document ID, filename, source. Hover help: "Source document — click to preview"
- Clicking a recovery or document populates the right column (preview)
- Clicking a connected entity **slides** the view: middle column becomes the left column, new connections appear in the middle, preview clears. Animation: CSS transform slide-left, ~200ms ease-out.
- Small color-coded legend visible in the column header: ● Recoveries ● Entities ● Documents

### Right column: Preview
- Shows a preview of whatever is selected in the middle column
- Recovery: snippet of recovered text with green highlighting, "Open Recovery →" link
- Document: first ~500 chars of extracted text, "Open Document →" link
- Entity: summary card with stats, "Explore →" link
- Links navigate to the full detail pages

### Navigation
- Back button at top of middle column to rewind the slide history
- Breadcrumb trail showing the entity navigation path
- Browser back/forward works (URL updates with query params: `/?entity=123`)

### Empty/loading states
- If entity index doesn't exist: full-page message "Entity index has not been built yet" with "Build Now" button (admin) or "Ask your administrator to build the entity index" (non-admin)
- If index is stale: small banner at top "Entity index may be out of date — last built [date]" with rebuild link (admin only)
- Loading spinner while entity connections are fetched

## Highlights Page

Auto-generated from recovery data and entity index. No manual curation. URL: `/highlights/`

### Sections

**Top Recoveries:** 10-20 groups with highest `recovered_count`. Each shows:
- Headline: first ~100 chars of the most substantive recovered segment (longest segment with >3 words, excluding segments that begin with "The image", "This image", or "This page" — consistent with the existing merged_text template filter)
- Badge: "N passages recovered" with hover help
- Source document count
- Link to full recovery detail

**Notable Entities:** Top entities by connection count, displayed as cards. Each shows:
- Entity name and type badge
- Occurrence count and connection count
- A sample recovered snippet
- Link to Explore page focused on that entity

**Common Unredactions:** Moved from the current recoveries page sidebar. The "most frequently recovered strings" panel with occurrence counts and links to search results.

All sections include hover help on badges and counts explaining what they mean.

## Recovery Detail: Redaction Jumping & Source View

### Merged Text tab changes

Each recovered passage (`class="recovered"`) becomes interactive:
- **Hover effect:** subtle glow or brightness increase, cursor changes to pointer. Tooltip: "Click to view source document"
- **Click behavior:** opens/updates a source panel on the right side, splitting the merged text view 60/40
- **Source indicator:** small label on each recovered passage showing the source doc ID
- **Segment mapping:** each `<span class="recovered">` in the rendered HTML has a `data-segment-index` attribute corresponding to the index in the `recovered_segments` JSON array and a `data-source-doc` attribute with the `source_doc_id`. These are added during `format_merged_text` rendering.
- **Navigation arrows:** floating "↑ Previous recovery" / "↓ Next recovery" buttons, always visible when scrolling, similar to scroll-to-top pattern. Keyboard shortcuts: `j`/`k` or up/down arrows when merged text is focused.

### Source panel (appears on click)

Slides in from the right with a brief animation (~200ms). Has a close button (×) to return to full-width merged text.

**Search context extraction:** When a recovered passage is clicked, the client sends the `segment_index` and `group_id` to the server. The server reads the raw `merged_text` (pre-HTML) and extracts 30-40 chars of unredacted text adjacent to the recovered segment, skipping `[REDACTED]` markers and taking text from the unredacted side of the boundary. Fallback chain: try 40 chars → try 20 chars → page-number-only → no scroll.

**When source doc has a cached PDF:**
- Loads a new source-panel-specific PDF embed that uses the **full PDF.js viewer** (`PDFViewer` + text layer + `PDFFindController`), not the current lightweight canvas-only embed. This is a separate template from `embed.html`.
- Passes the search context string as a URL parameter; the viewer auto-searches on load
- If search finds a match, scrolls to and highlights that location in the PDF
- If search fails, shows PDF at page 1 with a note: "Could not locate exact position — the redaction may span multiple pages"

**Alternative (simpler) approach for PDF location:** If the full PDFViewer integration proves too complex, fall back to server-side search: search the source doc's `extracted_text` for the context string, estimate the page number from character offset (chars_before / total_chars × page_count), and load the PDF scrolled to that page. This avoids findController entirely at the cost of less precise positioning.

**When source doc is an email record (no PDF):**
- Shows extracted text in a scrollable text pane (monospaced, matching the app's log-viewer style)
- The recovered passage is highlighted in green within the text (server-side substring search on `extracted_text`, returning the text with `<mark>` tags around the match)
- The surrounding redacted markers (`[REDACTED]`, etc.) are visible, showing where the original redaction was

**When source doc has no text and no PDF:**
- Shows message: "Source document text not available"

### Source panel endpoint

`GET /recoveries/{group_id}/source?segment_index=N` — returns the source panel HTML fragment. The server:
1. Looks up `recovered_segments[N]` to get `source_doc_id` and `text`
2. Looks up the source document's `text_source`, `pdf_url`, `release_batch`, `original_filename`, `extracted_text`
3. Extracts the search context string from the raw `merged_text`
4. Returns the appropriate panel (PDF embed with search param, text pane with highlighting, or "not available" message)

### Original PDFs tab

Stays as the manual comparison tool. No changes beyond the existing has_pdf/email record messaging from the prior fix.

## Research Improvements

### Documents page

- **Entity-aware search:** searching for a person name queries the entity index DB first to get matching `group_id`s, then queries Unobfuscator's `match_group_members` to get `doc_id`s, then includes those in the document results. This is a two-step query approach — no cross-database ATTACH needed. Search hint text: `Search by filename, document ID, or entity name`
- **Date range filter** if extractable from document metadata or filenames (stretch goal — only if dates are reliably available)

### Recoveries page

- **Boolean search:** support AND, OR, quoted exact phrases. Parsed into an AST on the Python side — each term becomes a parameterized `LIKE ? ESCAPE '!'` clause, boolean operators are hardcoded SQL keywords (never user-supplied strings). Example: `"Jeffrey Epstein" AND FBI` → `WHERE recovered_segments LIKE ? ESCAPE '!' AND recovered_segments LIKE ? ESCAPE '!'` with params `['%Jeffrey Epstein%', '%FBI%']`. Search hint text: `Search recovered text — use AND, OR, quotes for exact phrases`
- **Common unredactions panel removed** from this page (moved to Highlights page, decluttering the research view)
- **Sort options:** by recovered_count (default) or by date

## Discoverability & Help

### Hover help (title tooltips)

Applied to:
- Entity type badges in Explore
- Recovery count badges everywhere they appear
- Stat cards on admin dashboard and highlights page
- Recovered passages in merged text ("Click to view the source document this text was recovered from")
- Column headers in all data tables
- Navigation arrows ("Jump to next recovered passage (keyboard: j)")
- Color-coded connection items in Explore

### Search hints

Small muted text directly below each search input:
- Recoveries: `Search recovered text — use AND, OR, quotes for exact phrases`
- Documents: `Search by filename, document ID, or entity name`
- Explore entity filter: `Filter by name`

### Visual discoverability cues

- Recovered passages: hover glow effect so users discover clickability naturally
- Source panel: slide-in animation makes the cause-effect relationship clear
- Entity graph: color legend always visible; connection items have distinct left-border colors
- Floating recovery nav arrows: appear after first scroll, fade in gently
- All clickable table rows keep the existing pointer cursor + row highlight on hover

### No tutorial needed

The design relies on progressive disclosure:
1. User lands on Explore, sees entities, clicks one → connections appear
2. Clicks a recovery → preview appears, "Open Recovery →" link is obvious
3. On recovery page, hovers over green text → tooltip says "click to view source"
4. Clicks → source panel slides in
5. Search boxes have hints right below them explaining syntax

Each interaction teaches the next one through visual feedback and contextual help text.

## Technical Notes

### No changes to Unobfuscator
All new features use read-only access to the existing Unobfuscator SQLite database. The entity index is a separate TEREDACTA-owned database. No Unobfuscator code or schema changes required.

### Performance considerations
- Entity index build: scans `recovered_segments` JSON, regex extraction, SQLite inserts. Expected: 2-10 seconds for 15K groups.
- Explore page: entity list query + connections query per click. Both are indexed lookups on the entity DB. Sub-100ms.
- Source panel PDF location: either client-side PDF.js findController (~1-3s for large PDFs) or server-side character-offset estimation (sub-100ms).
- Source panel text search: server-side substring search on `extracted_text` column. Single indexed lookup + substring match.
- Highlights page: cached queries (same TTL pattern as existing stats cache).
- Precomputed counts (`occurrence_count`, `document_count`) on `entities` table avoid expensive aggregations at query time.

### Route changes
- `/` → Explore page (new `explore.py` router)
- `/highlights/` → Highlights page (new `highlights.py` router)
- `/groups/{path:path}` → 301 redirect to `/admin/groups/{path}`
- `/queue/{path:path}` → 301 redirect to `/admin/queue/{path}`
- `/admin/` → Admin dashboard (relocated from `/`, `dashboard.py` remounted with `/admin/` prefix)
- `/admin/groups/` → Groups page (relocated, `groups.py` remounted with `/admin/` prefix)
- `/admin/queue/` → Queue page (relocated, `queue.py` remounted with `/admin/` prefix)
- `/admin/entity-index/build` → POST endpoint for entity index build (admin-only + CSRF)
- `/api/entities*` → Entity graph API endpoints (new `api.py` router)
- `/recoveries/{group_id}/source` → Source panel endpoint (added to `recoveries.py`)
- `/sse/stats`, `/sse/daemon-status` → remain at root level (unprefixed), accessible to all users

### New static assets
- `explore.js` — entity graph column slide animation, entity loading via fetch(), preview rendering, breadcrumb/pushState management
- `source-panel.js` — recovery click handler, source panel slide-in, PDF search trigger, text highlighting
- CSS additions for three-column layout, slide animations, floating nav arrows, hover effects, source panel split view

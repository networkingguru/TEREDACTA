# Recovery View: Text Comparison for Email Documents

**Date:** 2026-03-31
**Issue:** networkingguru/TEREDACTA#1

## Problem

The "Original PDFs" tab in the recovery detail view shows two side-by-side panes for comparing document versions. When documents are email records (no PDF), both panes display a useless "No PDF available" message. The extracted text exists in the database but is not surfaced in the comparison view.

Most recoveries involve email-only documents, making this tab effectively broken for the majority of cases.

## Solution

Upgrade the Original Documents tab to render extracted text in scrollable panes when PDFs are not available for both members of the current comparison pair. Text panes highlight recovered passages and support scroll sync, providing the same comparison UX as the PDF view.

## Design

### Tab Rename

The tab label changes from "Original PDFs" to "Original Documents" unconditionally. The HTMX URL slug remains `original-pdfs` to avoid breaking bookmarks and internal references.

### Pane Mode Selection

The comparison view operates in one of two modes based on the current pair (left primary + right donor):

- **PDF mode:** Both members have PDFs cached locally (`pdf_cache_path` is set). Render two PDF iframes with scroll sync. This is the existing behavior, unchanged. External-URL-only PDFs do not qualify for PDF mode since they cannot be embedded in iframes due to cross-origin restrictions.
- **Text mode:** Either member lacks a locally cached PDF. Render two `log-viewer` text panes with scroll sync. Both panes show extracted text, even if one member has a PDF available.

**Why text-only when either lacks a PDF:** The purpose of this tab is side-by-side comparison. Mixed mode (PDF iframe left, text right) breaks scroll sync and provides an incoherent comparison experience — one pane is a rendered page image, the other is raw text. Showing text for both keeps the comparison meaningful and enables scroll sync. The user can always view individual PDFs via the "Document Details" link.

When the donor changes via the dropdown, the mode is re-evaluated and both panes update accordingly.

### Backend: Lazy Text Endpoint

**Endpoint:** `GET /recoveries/{group_id}/member-text?doc_id={doc_id}`

Returns an HTML fragment: a `log-viewer` div containing the document's `extracted_text` (HTML-escaped), with recovered passages highlighted using `<mark class="recovered-inline">`.

**Text size handling:** Truncation logic is defined in the `get_member_text` method steps below.

**Error cases:**
- `doc_id` not in group `group_id` → 404
- `group_id` does not exist → 404
- `extracted_text` is NULL or empty → return a styled message: "No extracted text available for this document."

**Implementation in `unob.py`:**

New method `get_member_text(group_id, doc_id)`:

1. Verify `doc_id` is a member of `group_id` by querying the `match_group_members` table. Return None if not found.
2. Fetch `extracted_text` from the `documents` table for `doc_id`.
3. If `extracted_text` is NULL/empty, return a dict with `text_html` set to the "no text" message.
4. Truncate `extracted_text` if it exceeds 100KB: find the last whitespace before the 100KB mark and cut there. If no whitespace exists within 200 bytes before the mark, truncate at 100KB exactly. Append an ellipsis with note: "Showing first ~100KB. View full text on document detail page."
5. Fetch `recovered_segments` from `merge_results` for `group_id`. Do NOT filter on `recovered_count > 0` — if no segments exist, render the text without highlights.
6. **Highlighting is role-agnostic:** For each recovered segment, search for its text in `extracted_text` and highlight all matches found. Since group members contain overlapping text, recovered passages will appear in most members regardless of whether they are the source or destination.
7. **Matching approach:** For each segment, try exact substring match first, then whitespace-normalized match (same as existing `get_source_context()`). If a segment cannot be found, skip it silently — partial highlighting is better than failing.
8. **Overlap handling:** Collect all (start, end) positions, sort by start, merge overlapping/adjacent ranges, then build the HTML in one pass: escape non-highlighted text, wrap highlighted ranges with `<mark>`.
9. All text outside `<mark>` tags is `html.escape()`d to prevent XSS.
10. Return dict with `text_html` (the highlighted HTML string) and `doc_id`.

**Router in `recoveries.py`:**
- New route handler calling `get_member_text()`, returning an `HTMLResponse` with the fragment (a `log-viewer` div wrapping `text_html`).

### Frontend: Template Changes

**`original_pdfs.html` (filename unchanged):**

- Dropdown options already carry `data-pdf-path`, `data-has-pdf`, `data-pdf-url`. No new attributes needed — PDF mode is determined by checking `data-pdf-path` on both the primary and the selected donor.
- **Primary doc_id exposure:** The left pane div gets a `data-doc-id="{{ recovery.members[0].doc_id }}"` attribute and the primary's `data-pdf-path` is stored on the pane div as well. This lets JS determine the primary's identity and PDF status without parsing the dropdown.
- **Left pane (primary):** On initial tab load, if text mode applies (primary has no `pdf_cache_path`), render a placeholder `<div class="log-viewer" id="primary-text">` and fire a `fetch()` to `/recoveries/{group_id}/member-text?doc_id={primary_doc_id}` to populate it.
- **Right pane (donor):** `updateDonor()` JS function extended:
  1. Check if both the primary and new donor have `pdf_cache_path` set.
  2. If yes → PDF mode: render iframes as today.
  3. If no → Text mode: fetch `/member-text` for both docs (in parallel), inject HTML into both panes, attach scroll sync.
- When switching from text mode back to PDF mode (user picks a donor that has a cached PDF while primary also has one), restore the iframe rendering for both panes.

**Scroll sync (`comparison.js`):**

Extended to handle two `log-viewer` divs:
- If both panes contain `.log-viewer` elements, attach proportional scroll sync directly on those divs' `scroll` events.
- If both panes contain iframes, use existing iframe scroll sync (unchanged).
- No mixed-mode sync (design guarantees both panes are the same type).
- **Listener cleanup:** When switching modes (text→PDF or PDF→text), previous scroll listeners must be removed before attaching new ones. Add a cleanup function that detaches existing listeners, called at the start of `setupScrollSync` and when `updateDonor()` switches modes.
- Note: Proportional scroll sync on text panes of very different lengths will produce uneven scrolling (one pane moves fast, the other slow). This mirrors the existing PDF behavior for documents of different page counts and is acceptable.

**Single/Split toggle:** Unchanged — CSS class toggle hides/shows the second pane.

### Data Flow

```
User clicks "Original Documents" tab
  -> HTMX loads tab template
  -> Template renders dropdown + two pane containers
  -> JS evaluates mode for primary + first donor
  -> If text mode: fetch /member-text for both docs, inject into log-viewer divs, attach scroll sync
  -> If PDF mode: render iframes as today
  
User selects different donor from dropdown
  -> JS checks if primary + new donor both have pdf_cache_path
  -> If PDF mode: render iframes (existing behavior), tear down any text panes
  -> If text mode: fetch /member-text for both docs (in parallel; each pane handles its fetch independently, showing error message in failing pane while successful pane renders normally), inject, re-attach scroll sync, tear down any iframes
```

### Files to Modify

| File | Change |
|------|--------|
| `teredacta/unob.py` | Add `get_member_text(group_id, doc_id)` method |
| `teredacta/routers/recoveries.py` | Add `/recoveries/{group_id}/member-text` route |
| `teredacta/templates/recoveries/detail.html` | Tab button label: "Original Documents" |
| `teredacta/templates/recoveries/tabs/original_pdfs.html` | Text pane rendering, updated `updateDonor()`, fetch-based text loading |
| `teredacta/static/js/comparison.js` | Scroll sync for `log-viewer` divs |

### What Does NOT Change

- Merged Text tab and source panel behavior
- Output PDF tab
- Metadata tab
- PDF iframe rendering when both members have cached PDFs
- Dropdown member list and ordering
- Single/split view toggle CSS mechanics
- Template filename (`original_pdfs.html`) and URL slug (`original-pdfs`)

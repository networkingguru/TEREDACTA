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

The tab label changes from "Original PDFs" to "Original Documents" unconditionally.

### Pane Mode Selection

The comparison view operates in one of two modes based on the current pair (left primary + right donor):

- **PDF mode:** Both members have PDFs cached locally. Render two PDF iframes with scroll sync. This is the existing behavior, unchanged. (External-URL-only PDFs cannot be embedded in iframes due to cross-origin restrictions, so they do not qualify for PDF mode.)
- **Text mode:** Either member lacks a PDF. Render two `log-viewer` text panes with scroll sync. Both panes show extracted text, even if one member has a PDF available — consistency trumps fidelity.

When the donor changes via the dropdown, the mode is re-evaluated and both panes update accordingly.

### Backend: Lazy Text Endpoint

**Endpoint:** `GET /recoveries/{group_id}/member-text?doc_id={doc_id}`

Returns an HTML fragment: a `log-viewer` div containing the document's `extracted_text`. Recovered passages that originated from this document (within this recovery group) are highlighted with `<mark class="recovered-inline">`.

**Implementation in `unob.py`:**

New method `get_member_text(group_id, doc_id)`:
1. Fetch `extracted_text` from the `documents` table for `doc_id`.
2. Fetch `recovered_segments` from `merge_results` for `group_id`.
3. Filter segments where `source_doc_id == doc_id`.
4. For each matching segment, find its position in `extracted_text` and wrap with `<mark class="recovered-inline">`.
5. Handle overlapping/adjacent segments by sorting by position and merging.
6. Return the highlighted HTML string.

**Router in `recoveries.py`:**
- New route handler calling `get_member_text()` and returning an HTML fragment via a minimal template (or inline HTML response).

### Frontend: Template Changes

**`original_pdfs.html` (renamed conceptually to "original documents"):**

- Dropdown options gain a `data-has-text="true"` attribute for members that are email records (no PDF). All members already have `data-has-pdf` and `data-pdf-path`.
- Left pane: if primary member has no PDF, render a placeholder div and fire an HTMX request on tab load to `/recoveries/{group_id}/member-text?doc_id={primary_doc_id}`.
- Right pane: `updateDonor()` JS function extended — when the new pair triggers text mode, both panes fetch text from the endpoint and inject the HTML fragments.

**Scroll sync (`comparison.js`):**

Extended to handle two `log-viewer` divs in addition to two iframes:
- If both panes contain `.log-viewer` elements, attach proportional scroll sync on those divs directly.
- If both panes contain iframes, use existing iframe scroll sync.
- No mixed-mode sync needed (design guarantees both panes are the same type).

**Single/Split toggle:** Unchanged — CSS class toggle hides/shows the second pane.

### Data Flow

```
User clicks "Original Documents" tab
  -> HTMX loads tab template
  -> Template renders dropdown + two pane containers
  -> If text mode: both panes fire fetch to /member-text endpoint
  -> Server returns highlighted extracted text HTML fragments
  -> Injected into log-viewer divs
  -> Scroll sync attached to both divs

User selects different donor from dropdown
  -> JS checks if new pair is PDF-PDF or not
  -> If PDF mode: render iframes (existing behavior)
  -> If text mode: fetch /member-text for both docs, inject, re-attach scroll sync
```

### Files to Modify

| File | Change |
|------|--------|
| `teredacta/unob.py` | Add `get_member_text(group_id, doc_id)` method |
| `teredacta/routers/recoveries.py` | Add `/recoveries/{group_id}/member-text` route, rename tab label |
| `teredacta/templates/recoveries/detail.html` | Tab button label: "Original Documents" |
| `teredacta/templates/recoveries/tabs/original_pdfs.html` | Text pane rendering, updated `updateDonor()`, HTMX triggers |
| `teredacta/static/js/comparison.js` | Scroll sync for `log-viewer` divs |

### What Does NOT Change

- Merged Text tab and source panel behavior
- Output PDF tab
- Metadata tab
- PDF iframe rendering when both members have PDFs
- Dropdown member list and ordering
- Single/split view toggle CSS mechanics

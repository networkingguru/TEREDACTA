# Recovery Text Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show extracted text side-by-side with highlighted recovered passages in the recovery detail view when PDFs are not available.

**Architecture:** New backend method `get_member_text()` in `unob.py` serves highlighted text fragments via a new route. The existing `original_pdfs.html` template and `comparison.js` are extended to render text panes when either member lacks a cached PDF, with scroll sync between text divs.

**Tech Stack:** Python/FastAPI (backend), Jinja2 templates, vanilla JS, SQLite

---

### Task 1: Backend — `get_member_text()` method

**Files:**
- Modify: `teredacta/unob.py` (add method after `get_source_context`, around line 702)
- Test: `teredacta/tests/test_unob.py`

- [ ] **Step 1: Write failing tests for `get_member_text`**

Add to `teredacta/tests/test_unob.py`:

```python
class TestGetMemberText:
    """Tests for get_member_text() — highlighted text for comparison panes."""

    def test_returns_highlighted_text(self, test_config, populated_db):
        """Recovered passages are highlighted in source doc text."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(1, "doc-002")
        assert result is not None
        assert result["doc_id"] == "doc-002"
        assert '<mark class="recovered-inline">' in result["text_html"]
        # "Ghislaine Maxwell" is a recovered segment from doc-002
        assert "Ghislaine Maxwell" in result["text_html"]

    def test_returns_none_for_nonmember(self, test_config, populated_db):
        """doc_id not in the group returns None."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(1, "nonexistent-doc")
        assert result is None

    def test_returns_none_for_nonexistent_group(self, test_config, populated_db):
        """Nonexistent group_id returns None."""
        test_config.db_path = str(populated_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(999, "doc-001")
        assert result is None

    def test_no_segments_returns_plain_text(self, test_config, mock_db):
        """Group with no recovered segments still renders text without highlights."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed) "
            "VALUES ('solo-doc', 'test', 'plain text here', 1)"
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (50, 1)")
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (50, 'solo-doc', 0.9)"
        )
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count) "
            "VALUES (50, 'plain text here', 0)"
        )
        conn.commit()
        conn.close()

        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(50, "solo-doc")
        assert result is not None
        assert "plain text here" in result["text_html"]
        assert "<mark" not in result["text_html"]

    def test_empty_extracted_text(self, test_config, mock_db):
        """NULL/empty extracted_text returns a no-text message."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed) "
            "VALUES ('empty-doc', 'test', '', 1)"
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (51, 1)")
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (51, 'empty-doc', 0.9)"
        )
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count) "
            "VALUES (51, '', 0)"
        )
        conn.commit()
        conn.close()

        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(51, "empty-doc")
        assert result is not None
        assert "No extracted text available" in result["text_html"]

    def test_html_escaping(self, test_config, mock_db):
        """Angle brackets in extracted_text are escaped to prevent XSS."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed) "
            "VALUES ('xss-doc', 'test', '<script>alert(1)</script> safe text', 1)"
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (52, 1)")
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (52, 'xss-doc', 0.9)"
        )
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count) "
            "VALUES (52, '', 0)"
        )
        conn.commit()
        conn.close()

        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(52, "xss-doc")
        assert "<script>" not in result["text_html"]
        assert "&lt;script&gt;" in result["text_html"]

    def test_truncation_over_100kb(self, test_config, mock_db):
        """Text over 100KB is truncated with a message."""
        big_text = "word " * 25000  # ~125KB
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed) "
            "VALUES ('big-doc', 'test', ?, 1)", (big_text,)
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (53, 1)")
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (53, 'big-doc', 0.9)"
        )
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count) "
            "VALUES (53, '', 0)"
        )
        conn.commit()
        conn.close()

        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(53, "big-doc")
        assert "Showing first" in result["text_html"]
        # Should be roughly 100KB, not the full 125KB
        assert len(result["text_html"]) > 90_000
        assert len(result["text_html"]) < 110_000

    def test_whitespace_normalized_match(self, test_config, mock_db):
        """Segments with different whitespace still match via normalization."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed) "
            "VALUES ('ws-doc', 'test', 'hello   world  foo   bar', 1)"
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (55, 1)")
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (55, 'ws-doc', 0.9)"
        )
        segments = json.dumps([
            {"source_doc_id": "other", "text": "hello world"},
        ])
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count, recovered_segments) "
            "VALUES (55, '', 1, ?)", (segments,)
        )
        conn.commit()
        conn.close()

        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(55, "ws-doc")
        assert '<mark class="recovered-inline">' in result["text_html"]
        assert "hello world" in result["text_html"]

    def test_multiple_occurrences_all_highlighted(self, test_config, mock_db):
        """If a recovered passage appears twice, both occurrences are highlighted."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed) "
            "VALUES ('multi-doc', 'test', 'hello world then hello world again', 1)"
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (56, 1)")
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (56, 'multi-doc', 0.9)"
        )
        segments = json.dumps([
            {"source_doc_id": "other", "text": "hello world"},
        ])
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count, recovered_segments) "
            "VALUES (56, '', 1, ?)", (segments,)
        )
        conn.commit()
        conn.close()

        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(56, "multi-doc")
        mark_count = result["text_html"].count('<mark class="recovered-inline">')
        assert mark_count == 2

    def test_overlapping_segments_merged(self, test_config, mock_db):
        """Overlapping highlight ranges are merged, not doubled."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed) "
            "VALUES ('overlap-doc', 'test', 'ABCDEFGHIJ', 1)"
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (54, 1)")
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) "
            "VALUES (54, 'overlap-doc', 0.9)"
        )
        segments = json.dumps([
            {"source_doc_id": "other", "text": "BCDEF"},
            {"source_doc_id": "other", "text": "DEFGH"},
        ])
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count, recovered_segments) "
            "VALUES (54, '', 2, ?)", (segments,)
        )
        conn.commit()
        conn.close()

        test_config.db_path = str(mock_db)
        unob = UnobInterface(test_config)
        result = unob.get_member_text(54, "overlap-doc")
        # Should have exactly one <mark> tag covering BCDEFGH (merged range)
        mark_count = result["text_html"].count('<mark class="recovered-inline">')
        assert mark_count == 1
        assert "BCDEFGH" in result["text_html"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_unob.py::TestGetMemberText -v`
Expected: FAIL — `UnobInterface` has no `get_member_text` attribute

- [ ] **Step 3: Implement `get_member_text` in `unob.py`**

Add this method to the `UnobInterface` class, after `get_source_context` (after line 702):

```python
    def get_member_text(self, group_id: int, doc_id: str) -> Optional[dict]:
        """Get full extracted text for a group member with recovered passages highlighted.

        Returns a dict with 'doc_id' and 'text_html', or None if doc_id is not
        a member of group_id.
        """
        _MAX_TEXT_CHARS = 102_400  # ~100K characters

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
            if len(extracted) > _MAX_TEXT_CHARS:
                cut = extracted.rfind(" ", _MAX_TEXT_CHARS - 200, _MAX_TEXT_CHARS)
                if cut < 0:
                    cut = _MAX_TEXT_CHARS
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
            # First try exact matches. If any segment fails exact match,
            # normalize the entire text once and retry all segments.
            ranges = []
            unmatched = set()
            for seg_text in segments:
                pos = extracted.find(seg_text)
                if pos >= 0:
                    ranges.append((pos, pos + len(seg_text)))
                    # Also find additional occurrences
                    pos = extracted.find(seg_text, pos + len(seg_text))
                    while pos >= 0:
                        ranges.append((pos, pos + len(seg_text)))
                        pos = extracted.find(seg_text, pos + len(seg_text))
                else:
                    unmatched.add(seg_text)

            # Retry unmatched segments with whitespace normalization
            if unmatched:
                norm_ext = " ".join(extracted.split())
                # Switch to normalized text for all remaining work
                # Re-find previously matched segments in normalized text
                norm_ranges = []
                for seg_text in segments:
                    if seg_text in unmatched:
                        norm_seg = " ".join(seg_text.split())
                    else:
                        norm_seg = seg_text
                    pos = norm_ext.find(norm_seg)
                    while pos >= 0:
                        norm_ranges.append((pos, pos + len(norm_seg)))
                        pos = norm_ext.find(norm_seg, pos + len(norm_seg))
                extracted = norm_ext
                ranges = norm_ranges

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/test_unob.py::TestGetMemberText -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/unob.py teredacta/tests/test_unob.py
git commit -m "feat: add get_member_text() for highlighted text comparison panes"
```

---

### Task 2: Route — `/recoveries/{group_id}/member-text` endpoint

**Files:**
- Modify: `teredacta/routers/recoveries.py` (add route after `source_panel`, around line 78)
- Test: `teredacta/tests/routers/test_recoveries.py`

- [ ] **Step 1: Write failing tests for the endpoint**

Add to `teredacta/tests/routers/test_recoveries.py`:

```python
import json
import sqlite3


def _seed_for_member_text(mock_db):
    """Seed DB for member-text endpoint tests."""
    conn = sqlite3.connect(str(mock_db))
    conn.execute(
        "INSERT INTO documents (id, source, extracted_text, text_processed, text_source) "
        "VALUES ('mt-doc-0', 'test', 'Hello [REDACTED] world', 1, 'jmail')"
    )
    conn.execute(
        "INSERT INTO documents (id, source, extracted_text, text_processed, text_source) "
        "VALUES ('mt-doc-1', 'test', 'Hello beautiful world', 1, 'jmail')"
    )
    conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (10, 1)")
    conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (10, 'mt-doc-0', 0.95)")
    conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (10, 'mt-doc-1', 0.90)")
    segments = json.dumps([{"source_doc_id": "mt-doc-1", "text": "beautiful"}])
    conn.execute(
        "INSERT INTO merge_results (group_id, merged_text, recovered_count, source_doc_ids, recovered_segments) "
        "VALUES (10, 'Hello beautiful world', 1, ?, ?)",
        (json.dumps(["mt-doc-0", "mt-doc-1"]), segments),
    )
    conn.commit()
    conn.close()


class TestMemberTextEndpoint:
    def test_returns_200_with_highlighted_html(self, client, mock_db):
        _seed_for_member_text(mock_db)
        resp = client.get("/recoveries/10/member-text?doc_id=mt-doc-1")
        assert resp.status_code == 200
        assert '<mark class="recovered-inline">' in resp.text
        assert "beautiful" in resp.text

    def test_returns_404_for_nonmember(self, client, mock_db):
        _seed_for_member_text(mock_db)
        resp = client.get("/recoveries/10/member-text?doc_id=nonexistent")
        assert resp.status_code == 404

    def test_returns_404_for_nonexistent_group(self, client, mock_db):
        _seed_for_member_text(mock_db)
        resp = client.get("/recoveries/999/member-text?doc_id=mt-doc-0")
        assert resp.status_code == 404

    def test_returns_html_content_type(self, client, mock_db):
        _seed_for_member_text(mock_db)
        resp = client.get("/recoveries/10/member-text?doc_id=mt-doc-0")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/routers/test_recoveries.py::TestMemberTextEndpoint -v`
Expected: FAIL — 404 (route not defined)

- [ ] **Step 3: Add the route to `recoveries.py`**

Add after the `source_panel` function (after line 78):

```python
@router.get("/{group_id:int}/member-text", response_class=HTMLResponse)
def member_text(request: Request, group_id: int, doc_id: str = Query(...)):
    unob = request.app.state.unob
    result = unob.get_member_text(group_id, doc_id)
    if result is None:
        return Response(status_code=404)
    # Return raw HTML fragment — the calling template already provides
    # the wrapping log-viewer div, so we don't add another one here.
    return HTMLResponse(result["text_html"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/routers/test_recoveries.py::TestMemberTextEndpoint -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add teredacta/routers/recoveries.py teredacta/tests/routers/test_recoveries.py
git commit -m "feat: add /member-text endpoint for text comparison panes"
```

---

### Task 3: Tab rename — "Original Documents"

**Files:**
- Modify: `teredacta/templates/recoveries/detail.html:10`
- Modify: `teredacta/templates/recoveries/tabs/merged_text.html:19,41` (references to "Original PDFs")
- Test: `teredacta/tests/routers/test_original_pdfs_tab.py`

- [ ] **Step 1: Write a failing test for the tab label**

Add to `TestOriginalPDFsTab` class in `teredacta/tests/routers/test_original_pdfs_tab.py`:

```python
    def test_tab_label_says_original_documents(self, client, tmp_dir, mock_db):
        """Tab button should say 'Original Documents', not 'Original PDFs'."""
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1")
        assert resp.status_code == 200
        assert "Original Documents" in resp.text
        assert "Original PDFs" not in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/routers/test_original_pdfs_tab.py::TestOriginalPDFsTab::test_tab_label_says_original_documents -v`
Expected: FAIL — "Original PDFs" is still in the text

- [ ] **Step 3: Update the tab label in `detail.html`**

In `teredacta/templates/recoveries/detail.html` line 10, change:

```
>Original PDFs</button>
```
to:
```
>Original Documents</button>
```

- [ ] **Step 4: Update "Original PDFs" references in `merged_text.html`**

The detail page includes `merged_text.html` by default, which references "Original PDFs" in two places. Update both:

In `teredacta/templates/recoveries/tabs/merged_text.html` line 19, change:
```
the <strong>Original PDFs</strong> tab to view the scanned pages.
```
to:
```
the <strong>Original Documents</strong> tab to view the source documents.
```

In `teredacta/templates/recoveries/tabs/merged_text.html` line 41, change:
```
Use the <strong>Original PDFs</strong> tab to view the source documents.
```
to:
```
Use the <strong>Original Documents</strong> tab to view the source documents.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/routers/test_original_pdfs_tab.py::TestOriginalPDFsTab::test_tab_label_says_original_documents -v`
Expected: PASS

- [ ] **Step 6: Run ALL original_pdfs_tab tests to check for regressions**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/routers/test_original_pdfs_tab.py -v`
Expected: All tests PASS (no test checks for "Original PDFs" text)

- [ ] **Step 7: Commit**

```bash
git add teredacta/templates/recoveries/detail.html teredacta/templates/recoveries/tabs/merged_text.html teredacta/tests/routers/test_original_pdfs_tab.py
git commit -m "feat: rename 'Original PDFs' tab to 'Original Documents'"
```

---

### Task 4: Template — Text pane rendering in `original_pdfs.html`

**Files:**
- Modify: `teredacta/templates/recoveries/tabs/original_pdfs.html`
- Test: `teredacta/tests/routers/test_original_pdfs_tab.py`

- [ ] **Step 1: Write failing tests for text pane rendering**

Add to `teredacta/tests/routers/test_original_pdfs_tab.py`:

```python
class TestTextPaneRendering:
    """Tests for text mode in the Original Documents tab."""

    def test_email_members_get_text_panes(self, client, tmp_dir, mock_db):
        """Email-only members should get text pane placeholders, not 'No PDF' messages."""
        _seed_recovery_with_email(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        # Should NOT show the old useless message
        assert "No PDF available" not in resp.text
        # Should have a text pane placeholder that loads via fetch
        assert "member-text" in resp.text

    def test_primary_pane_has_data_doc_id(self, client, tmp_dir, mock_db):
        """Primary pane div exposes doc_id as a data attribute."""
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert 'data-doc-id="test-doc-0"' in resp.text

    def test_primary_pane_has_data_pdf_path(self, client, tmp_dir, mock_db):
        """Primary pane div exposes pdf_cache_path as a data attribute."""
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert 'data-pdf-path="TestBatch/doc1.pdf"' in resp.text

    def test_pdf_mode_still_renders_iframes(self, client, tmp_dir, mock_db):
        """When both members have cached PDFs, iframes render as before."""
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert "iframe" in resp.text
        assert "/pdf/embed?" in resp.text

    def test_two_email_members_both_get_text_panes(self, client, tmp_dir, mock_db):
        """Two email members — both panes should load text."""
        conn = sqlite3.connect(str(mock_db))
        for i in range(2):
            conn.execute(
                "INSERT INTO documents (id, source, extracted_text, text_processed, text_source) "
                "VALUES (?, 'test', 'email text', 1, 'jmail')",
                (f"email-doc-{i}",),
            )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (1, 1)")
        for i in range(2):
            conn.execute(
                "INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, ?, ?)",
                (f"email-doc-{i}", 0.95 - i * 0.05),
            )
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count, source_doc_ids) "
            "VALUES (1, 'email text', 1, ?)",
            (json.dumps(["email-doc-0", "email-doc-1"]),),
        )
        conn.commit()
        conn.close()
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert "No PDF available" not in resp.text
        assert resp.text.count("member-text") >= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/routers/test_original_pdfs_tab.py::TestTextPaneRendering -v`
Expected: FAIL — current template shows "No PDF available" for email records

- [ ] **Step 3: Rewrite `original_pdfs.html` to support text mode**

Replace the full content of `teredacta/templates/recoveries/tabs/original_pdfs.html` with:

```html
<h3>Original Documents{% if recovery.total_members > recovery.members|length %} <span style="color:var(--text-secondary);font-size:0.875rem;">(showing {{ recovery.members|length }} of {{ recovery.total_members }} group members)</span>{% endif %}</h3>
{% if recovery.members|length > 1 %}
<div class="comparison-controls">
    <select id="donor-select" class="filter-select" onchange="updateDonor(this.options[this.selectedIndex])">
        {% for m in recovery.members %}
        <option value="{{ m.doc_id }}" data-pdf-path="{{ m.pdf_cache_path or '' }}" data-has-pdf="{{ 'true' if m.has_pdf else 'false' }}" data-pdf-url="{{ m.pdf_url or '' }}">{{ m.doc_id }} ({{ "%.2f"|format(m.similarity) if m.similarity else '?' }})</option>
        {% endfor %}
    </select>
    <button class="btn btn-primary" onclick="toggleComparison(this)">Single View</button>
</div>
{% endif %}
<div class="pdf-comparison" data-group-id="{{ group_id }}">
    {% if recovery.members|length > 0 %}
    {% set primary = recovery.members[0] %}
    <div class="pdf-pane" id="primary-pane" data-doc-id="{{ primary.doc_id }}" data-pdf-path="{{ primary.pdf_cache_path or '' }}">
        <h4>{{ primary.doc_id }}</h4>
        {% if primary.pdf_cache_path and (recovery.members|length <= 1 or recovery.members[1].pdf_cache_path) %}
        <iframe src="/pdf/embed?type=cache&path={{ primary.pdf_cache_path | urlencode }}" style="width:100%;height:600px;border:none;background:#525659;"></iframe>
        {% else %}
        <div class="log-viewer" id="primary-text" style="max-height:600px;font-size:0.85rem;line-height:1.7;">Loading...</div>
        {% endif %}
    </div>
    {% endif %}
    {% if recovery.members|length > 1 %}
    {% set donor = recovery.members[1] %}
    <div class="pdf-pane" id="donor-pane" data-doc-id="{{ donor.doc_id }}" data-pdf-path="{{ donor.pdf_cache_path or '' }}">
        <h4 id="donor-title">{{ donor.doc_id }}</h4>
        {% if donor.pdf_cache_path and recovery.members[0].pdf_cache_path %}
        <iframe id="donor-iframe" src="/pdf/embed?type=cache&path={{ donor.pdf_cache_path | urlencode }}" style="width:100%;height:600px;border:none;background:#525659;"></iframe>
        {% else %}
        <div class="log-viewer" id="donor-text" style="max-height:600px;font-size:0.85rem;line-height:1.7;">Loading...</div>
        {% endif %}
    </div>
    {% endif %}
</div>
{% if recovery.members|length > 1 %}
<script>
(function() {
    const groupId = {{ group_id }};
    const primaryPane = document.getElementById('primary-pane');
    const primaryPdfPath = primaryPane ? primaryPane.dataset.pdfPath : '';
    const primaryDocId = primaryPane ? primaryPane.dataset.docId : '';

    function loadText(pane, docId) {
        const viewer = pane.querySelector('.log-viewer');
        if (!viewer) return;
        fetch('/recoveries/' + groupId + '/member-text?doc_id=' + encodeURIComponent(docId))
            .then(function(r) {
                if (!r.ok) throw new Error('Failed to load text');
                return r.text();
            })
            .then(function(html) { viewer.innerHTML = html; })
            .catch(function() { viewer.textContent = 'Failed to load document text.'; });
    }

    function isPdfMode(primaryPath, donorPath) {
        return !!(primaryPath && donorPath);
    }

    function renderPrimaryAsText() {
        const pane = document.getElementById('primary-pane');
        const h4 = pane.querySelector('h4');
        pane.innerHTML = '';
        if (h4) pane.appendChild(h4);
        var div = document.createElement('div');
        div.className = 'log-viewer';
        div.id = 'primary-text';
        div.style.cssText = 'max-height:600px;font-size:0.85rem;line-height:1.7;';
        div.textContent = 'Loading...';
        pane.appendChild(div);
        loadText(pane, primaryDocId);
    }

    function renderPrimaryAsPdf() {
        if (!primaryPdfPath) return;
        var pane = document.getElementById('primary-pane');
        var h4 = pane.querySelector('h4');
        pane.innerHTML = '';
        if (h4) pane.appendChild(h4);
        var iframe = document.createElement('iframe');
        iframe.src = '/pdf/embed?type=cache&path=' + encodeURIComponent(primaryPdfPath);
        iframe.style.cssText = 'width:100%;height:600px;border:none;background:#525659;';
        pane.appendChild(iframe);
    }

    window.updateDonor = function(option) {
        var docId = option.value;
        var donorPdfPath = option.dataset.pdfPath;
        var pdfMode = isPdfMode(primaryPdfPath, donorPdfPath);

        // Update donor pane
        var pane = document.getElementById('donor-pane');
        pane.dataset.docId = docId;
        pane.dataset.pdfPath = donorPdfPath || '';
        pane.innerHTML = '';
        var title = document.createElement('h4');
        title.id = 'donor-title';
        title.textContent = docId;
        pane.appendChild(title);

        if (pdfMode) {
            // Both have cached PDFs — iframe mode
            var iframe = document.createElement('iframe');
            iframe.id = 'donor-iframe';
            iframe.src = '/pdf/embed?type=cache&path=' + encodeURIComponent(donorPdfPath);
            iframe.style.cssText = 'width:100%;height:600px;border:none;background:#525659;';
            pane.appendChild(iframe);
            // Ensure primary is also in PDF mode
            if (!document.querySelector('#primary-pane iframe')) {
                renderPrimaryAsPdf();
            }
            if (window.setupScrollSync) window.setupScrollSync();
        } else {
            // Text mode — show text for both panes
            var div = document.createElement('div');
            div.className = 'log-viewer';
            div.id = 'donor-text';
            div.style.cssText = 'max-height:600px;font-size:0.85rem;line-height:1.7;';
            div.textContent = 'Loading...';
            pane.appendChild(div);
            loadText(pane, docId);
            // Ensure primary is also in text mode
            if (!document.querySelector('#primary-pane .log-viewer')) {
                renderPrimaryAsText();
            }
            if (window.setupScrollSync) window.setupScrollSync();
        }
    };

    // Initial load: if text panes exist, fetch their content
    if (document.getElementById('primary-text')) {
        loadText(document.getElementById('primary-pane'), primaryDocId);
    }
    if (document.getElementById('donor-text')) {
        var donorDocId = document.getElementById('donor-pane').dataset.docId;
        loadText(document.getElementById('donor-pane'), donorDocId);
    }
})();
</script>
<script src="/static/js/comparison.js"></script>
{% elif recovery.members|length == 1 %}
<script>
(function() {
    var groupId = {{ group_id }};
    var pane = document.getElementById('primary-pane');
    var viewer = pane ? pane.querySelector('.log-viewer') : null;
    if (viewer) {
        var docId = pane.dataset.docId;
        fetch('/recoveries/' + groupId + '/member-text?doc_id=' + encodeURIComponent(docId))
            .then(function(r) { return r.ok ? r.text() : Promise.reject(); })
            .then(function(html) { viewer.innerHTML = html; })
            .catch(function() { viewer.textContent = 'Failed to load document text.'; });
    }
})();
</script>
{% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/routers/test_original_pdfs_tab.py::TestTextPaneRendering -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run ALL original_pdfs_tab tests to check for regressions**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/routers/test_original_pdfs_tab.py -v`
Expected: All tests PASS. Some existing tests may need adjustment (e.g., `test_email_message_unchanged` expects "email record" text which is now replaced with text panes). If any fail, update them to match the new behavior.

- [ ] **Step 6: Commit**

```bash
git add teredacta/templates/recoveries/tabs/original_pdfs.html teredacta/tests/routers/test_original_pdfs_tab.py
git commit -m "feat: render text comparison panes for email-only documents"
```

---

### Task 5: Scroll sync for text panes in `comparison.js`

**Files:**
- Modify: `teredacta/static/js/comparison.js`
- Test: Manual browser test (JS scroll sync is not testable via pytest)

- [ ] **Step 1: Write the updated `comparison.js`**

Replace the full content of `teredacta/static/js/comparison.js` with:

```javascript
(function() {
    var syncing = false;
    var cleanupFns = [];

    function cleanup() {
        cleanupFns.forEach(function(fn) { fn(); });
        cleanupFns = [];
    }

    function addScrollListener(el, handler) {
        el.addEventListener('scroll', handler);
        cleanupFns.push(function() { el.removeEventListener('scroll', handler); });
    }

    function attachIframeScrollSync(iframe, otherIframe) {
        iframe.addEventListener('load', function() {
            var doc = iframe.contentDocument || iframe.contentWindow.document;
            var container = doc.getElementById('viewerContainer');
            if (!container) return;
            var handler = function() {
                if (syncing) return;
                syncing = true;
                try {
                    var otherDoc = otherIframe.contentDocument || otherIframe.contentWindow.document;
                    var otherContainer = otherDoc.getElementById('viewerContainer');
                    if (otherContainer && container.scrollHeight > container.clientHeight) {
                        var ratio = container.scrollTop / (container.scrollHeight - container.clientHeight);
                        var otherMax = otherContainer.scrollHeight - otherContainer.clientHeight;
                        if (otherMax > 0) {
                            otherContainer.scrollTop = ratio * otherMax;
                        }
                    }
                } catch (e) { /* cross-origin or not loaded yet */ }
                requestAnimationFrame(function() { syncing = false; });
            };
            addScrollListener(container, handler);
        });
    }

    function attachTextScrollSync(div1, div2) {
        function syncScroll(source, target) {
            var handler = function() {
                if (syncing) return;
                syncing = true;
                var maxScroll = source.scrollHeight - source.clientHeight;
                if (maxScroll > 0) {
                    var ratio = source.scrollTop / maxScroll;
                    var targetMax = target.scrollHeight - target.clientHeight;
                    if (targetMax > 0) {
                        target.scrollTop = ratio * targetMax;
                    }
                }
                requestAnimationFrame(function() { syncing = false; });
            };
            addScrollListener(source, handler);
        }
        syncScroll(div1, div2);
        syncScroll(div2, div1);
    }

    function setupComparison() {
        cleanup();
        // Check for text panes first
        var textPanes = document.querySelectorAll('.pdf-pane .log-viewer');
        if (textPanes.length >= 2) {
            attachTextScrollSync(textPanes[0], textPanes[1]);
            return;
        }
        // Fall back to iframe sync
        var iframes = document.querySelectorAll('.pdf-pane iframe');
        if (iframes.length >= 2) {
            attachIframeScrollSync(iframes[0], iframes[1]);
            attachIframeScrollSync(iframes[1], iframes[0]);
        }
    }

    window.toggleComparison = function(btn) {
        var container = document.querySelector('.pdf-comparison');
        if (container) {
            container.classList.toggle('single-view');
            btn.textContent = container.classList.contains('single-view') ? 'Side by Side' : 'Single View';
        }
    };

    window.setupScrollSync = function() {
        // Delay slightly to let DOM update after fetch
        setTimeout(setupComparison, 100);
    };

    document.addEventListener('DOMContentLoaded', setupComparison);
    document.addEventListener('htmx:afterSwap', setupComparison);
})();
```

- [ ] **Step 2: Run existing CSS test to ensure no regressions**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/routers/test_original_pdfs_tab.py::TestSideBySideCSS -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add teredacta/static/js/comparison.js
git commit -m "feat: extend scroll sync to support text comparison panes"
```

---

### Task 6: Fix regressions in existing tests

**Files:**
- Modify: `teredacta/tests/routers/test_original_pdfs_tab.py`

This task handles existing tests that fail due to the template changes. Known tests that will break:

- `test_email_message_unchanged` (line 251) — asserts `"email record" in resp.text`, but email records now get text panes instead
- `test_tab_shows_message_when_no_cache` (line 136) — asserts `"email record" in resp.text or "not in local cache" in resp.text`, but non-cached docs without `text_source` set are treated as email records and get text panes
- `test_tab_renders_with_cached_pdfs` (line 118) — should still pass (both members have cached PDFs → iframe mode), but verify
- `test_donor_pane_renders_link_for_pdf_url_member` (line 295) — donor with pdf_url but no cache now gets text pane in text mode, not the external link
- `test_renders_source_link_when_pdf_url_present_no_cache` (line 224) — single member with pdf_url but no cache; primary pane is now a text pane

- [ ] **Step 1: Run all original_pdfs_tab tests and identify failures**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/routers/test_original_pdfs_tab.py -v 2>&1`

- [ ] **Step 2: Update failing tests to match new behavior**

Apply these specific changes:

- `test_email_message_unchanged`: Change assertion to `assert "member-text" in resp.text` (text pane loads via fetch instead of static message)
- `test_tab_shows_message_when_no_cache`: Change assertion to `assert "member-text" in resp.text or "log-viewer" in resp.text` (text pane loading replaces static messages)
- `test_renders_source_link_when_pdf_url_present_no_cache`: Update to expect text pane rendering instead of external link for single-member case
- `test_donor_pane_renders_link_for_pdf_url_member`: Update to expect text pane in donor for non-cached members
- Any other failures: adapt assertions to match the new template's text-mode behavior

The agent executing this task should run the tests first and fix based on actual failures.

- [ ] **Step 3: Run all tests to confirm everything passes**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add teredacta/tests/routers/test_original_pdfs_tab.py
git commit -m "test: update original documents tab tests for text pane rendering"
```

---

### Task 7: Full integration test

**Files:**
- Test: `teredacta/tests/routers/test_original_pdfs_tab.py`

- [ ] **Step 1: Write an end-to-end integration test**

Add to `teredacta/tests/routers/test_original_pdfs_tab.py`:

```python
class TestTextComparisonIntegration:
    """End-to-end tests verifying the full text comparison flow."""

    def test_member_text_endpoint_highlights_in_context(self, client, tmp_dir, mock_db):
        """Fetch member-text for a doc and verify highlighted recovered passages."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed, text_source) "
            "VALUES ('int-redacted', 'test', 'The [REDACTED] met with [REDACTED] on Tuesday.', 1, 'jmail')"
        )
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed, text_source) "
            "VALUES ('int-source', 'test', 'The director met with analysts on Tuesday.', 1, 'jmail')"
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (1, 1)")
        conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'int-redacted', 0.95)")
        conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'int-source', 0.90)")
        segments = json.dumps([
            {"source_doc_id": "int-source", "text": "director"},
            {"source_doc_id": "int-source", "text": "analysts"},
        ])
        conn.execute(
            "INSERT INTO merge_results (group_id, merged_text, recovered_count, source_doc_ids, recovered_segments) "
            "VALUES (1, 'The director met with analysts on Tuesday.', 2, ?, ?)",
            (json.dumps(["int-redacted", "int-source"]), segments),
        )
        conn.commit()
        conn.close()

        # Source doc should highlight "director" and "analysts"
        resp = client.get("/recoveries/1/member-text?doc_id=int-source")
        assert resp.status_code == 200
        assert "director" in resp.text
        assert "analysts" in resp.text
        assert resp.text.count('<mark class="recovered-inline">') == 2

        # Redacted doc won't have "director"/"analysts" — no highlights
        resp2 = client.get("/recoveries/1/member-text?doc_id=int-redacted")
        assert resp2.status_code == 200
        assert "[REDACTED]" in resp2.text
        assert '<mark class="recovered-inline">' not in resp2.text

    def test_tab_and_endpoint_work_together(self, client, tmp_dir, mock_db):
        """Tab renders text mode, endpoint returns valid HTML for both members."""
        _seed_recovery_with_email(tmp_dir, mock_db)
        # Tab should reference member-text endpoint
        tab_resp = client.get("/recoveries/1/tab/original-pdfs")
        assert tab_resp.status_code == 200
        assert "member-text" in tab_resp.text
        # Endpoint should return valid HTML fragment
        text_resp = client.get("/recoveries/1/member-text?doc_id=test-doc-0")
        assert text_resp.status_code == 200
        assert "text/html" in text_resp.headers["content-type"]

    def test_xss_in_member_text_endpoint(self, client, tmp_dir, mock_db):
        """Extracted text with HTML is escaped in member-text response."""
        conn = sqlite3.connect(str(mock_db))
        conn.execute(
            "INSERT INTO documents (id, source, extracted_text, text_processed, text_source) "
            "VALUES ('xss-test', 'test', '<img onerror=alert(1) src=x> normal text', 1, 'jmail')"
        )
        conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (1, 1)")
        conn.execute("INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'xss-test', 0.9)")
        conn.execute("INSERT INTO merge_results (group_id, merged_text, recovered_count) VALUES (1, '', 0)")
        conn.commit()
        conn.close()
        resp = client.get("/recoveries/1/member-text?doc_id=xss-test")
        assert resp.status_code == 200
        assert "<img" not in resp.text
        assert "&lt;img" in resp.text
```

- [ ] **Step 2: Run integration tests**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/routers/test_original_pdfs_tab.py::TestTextComparisonIntegration -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Run the full test suite one final time**

Run: `cd /root/TEREDACTA && python -m pytest teredacta/tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add teredacta/tests/routers/test_original_pdfs_tab.py
git commit -m "test: add integration tests for text comparison flow"
```

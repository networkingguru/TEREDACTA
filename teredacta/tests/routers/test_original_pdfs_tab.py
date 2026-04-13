"""Thorough tests for the Original PDFs tab in recovery detail."""
import json
import sqlite3
import pytest


def _seed_recovery(tmp_dir, mock_db, *, batch="TestBatch", filenames=("doc1.pdf", "doc2.pdf"), with_cache=True):
    """Seed the database with a recovery group that has 2 members, optionally create PDF cache files."""
    conn = sqlite3.connect(str(mock_db))
    # Insert documents
    for i, fname in enumerate(filenames):
        doc_id = f"test-doc-{i}"
        conn.execute(
            "INSERT INTO documents (id, source, release_batch, original_filename, extracted_text, text_processed) "
            "VALUES (?, 'test', ?, ?, 'some text', 1)",
            (doc_id, batch, fname),
        )
    # Create match group with merge result
    conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (1, 1)")
    for i in range(len(filenames)):
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, ?, ?)",
            (f"test-doc-{i}", 0.95 - i * 0.05),
        )
    conn.execute(
        "INSERT INTO merge_results (group_id, merged_text, recovered_count, total_redacted, source_doc_ids, output_generated) "
        "VALUES (1, 'recovered text', 3, 10, ?, 0)",
        (f'["test-doc-0","test-doc-1"]',),
    )
    conn.commit()
    conn.close()

    if with_cache:
        pdf_cache = tmp_dir / "pdf_cache"
        batch_dir = pdf_cache / batch
        batch_dir.mkdir(parents=True, exist_ok=True)
        for fname in filenames:
            pdf_file = batch_dir / fname
            pdf_file.write_bytes(
                b"%PDF-1.0\n1 0 obj<</Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
                b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
                b"0000000043 00000 n \n0000000096 00000 n \n"
                b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n170\n%%EOF"
            )


def _seed_recovery_with_pdf_url(tmp_dir, mock_db, *, pdf_url="https://www.courtlistener.com/docket/99/doc1.pdf",
                                with_cache=False, two_members=False, second_pdf_url=None):
    """Seed a recovery where documents have pdf_url set."""
    conn = sqlite3.connect(str(mock_db))
    conn.execute(
        "INSERT INTO documents (id, source, release_batch, original_filename, extracted_text, "
        "text_processed, text_source, pdf_url) "
        "VALUES (?, 'test', 'TestBatch', 'doc1.pdf', 'some text', 1, 'pdf_text_layer', ?)",
        ("test-doc-0", pdf_url),
    )
    conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (1, 1)")
    conn.execute(
        "INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'test-doc-0', 0.95)"
    )
    source_doc_ids = ["test-doc-0"]
    if two_members:
        conn.execute(
            "INSERT INTO documents (id, source, release_batch, original_filename, extracted_text, "
            "text_processed, text_source, pdf_url) "
            "VALUES (?, 'test', 'TestBatch', 'doc2.pdf', 'more text', 1, 'pdf_text_layer', ?)",
            ("test-doc-1", second_pdf_url),
        )
        conn.execute(
            "INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'test-doc-1', 0.90)"
        )
        source_doc_ids.append("test-doc-1")
    conn.execute(
        "INSERT INTO merge_results (group_id, merged_text, recovered_count, total_redacted, source_doc_ids, output_generated) "
        "VALUES (1, 'recovered text', 3, 10, ?, 0)",
        (f'[{",".join(repr(s) for s in source_doc_ids)}]'.replace("'", '"'),),
    )
    conn.commit()
    conn.close()
    if with_cache:
        pdf_cache = tmp_dir / "pdf_cache" / "TestBatch"
        pdf_cache.mkdir(parents=True, exist_ok=True)
        (pdf_cache / "doc1.pdf").write_bytes(
            b"%PDF-1.0\n1 0 obj<</Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
            b"0000000043 00000 n \n0000000096 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n170\n%%EOF"
        )


def _seed_recovery_with_email(tmp_dir, mock_db):
    """Seed a recovery where the document is an email record (no PDF)."""
    conn = sqlite3.connect(str(mock_db))
    conn.execute(
        "INSERT INTO documents (id, source, release_batch, original_filename, extracted_text, "
        "text_processed, text_source) "
        "VALUES (?, 'test', 'TestBatch', 'email1.pdf', 'email text', 1, 'jmail')",
        ("test-doc-0",),
    )
    conn.execute("INSERT INTO match_groups (group_id, merged) VALUES (1, 1)")
    conn.execute(
        "INSERT INTO match_group_members (group_id, doc_id, similarity) VALUES (1, 'test-doc-0', 0.95)"
    )
    conn.execute(
        "INSERT INTO merge_results (group_id, merged_text, recovered_count, total_redacted, source_doc_ids, output_generated) "
        "VALUES (1, 'recovered text', 3, 10, '[\"test-doc-0\"]', 0)",
    )
    conn.commit()
    conn.close()


class TestOriginalPDFsTab:
    """Tests for the Original PDFs tab rendering and functionality."""

    def test_tab_renders_with_cached_pdfs(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        # Should contain iframes for both PDFs
        assert "iframe" in resp.text
        assert "/pdf/embed?" in resp.text
        assert "test-doc-0" in resp.text
        assert "test-doc-1" in resp.text

    def test_tab_uses_embed_not_raw_pdf(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        # Should use embed viewer, NOT raw PDF URLs
        assert "/pdf/embed?type=cache" in resp.text
        assert 'src="/pdf/cache/' not in resp.text

    def test_tab_shows_message_when_no_cache(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db, with_cache=False)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        # New behavior: non-cached docs without text_source get text panes instead of error messages
        assert "log-viewer" in resp.text
        # Should NOT have iframe src for PDFs when not cached
        assert '<iframe src="/pdf/embed' not in resp.text

    def test_tab_has_donor_selector(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert "donor-select" in resp.text
        assert "donor-pane" in resp.text

    def test_tab_has_toggle_button(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert "toggleComparison" in resp.text
        # Button should start as "Single View" (since side-by-side is the default)
        assert "Single View" in resp.text

    def test_tab_loads_comparison_js(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert "comparison.js" in resp.text

    def test_tab_has_updateDonor_function(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert "updateDonor" in resp.text

    def test_embed_renders_pdfjs_viewer(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/pdf/embed?type=cache&path=TestBatch/doc1.pdf")
        assert resp.status_code == 200
        assert "viewerContainer" in resp.text
        assert "pdf-embed.js" in resp.text
        assert "/pdf/cache/TestBatch/doc1.pdf" in resp.text

    def test_embed_rejects_invalid_type(self, client):
        resp = client.get("/pdf/embed?type=evil&path=test.pdf")
        assert resp.status_code == 400

    def test_raw_pdf_still_served(self, client, tmp_dir, mock_db):
        """The embed viewer fetches the raw PDF — make sure that route works."""
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/pdf/cache/TestBatch/doc1.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    def test_paths_with_spaces_in_batch(self, client, tmp_dir, mock_db):
        """Batch names with spaces must be URL-encoded in iframe src."""
        _seed_recovery(tmp_dir, mock_db, batch="DOJ Release Batch", filenames=("doc1.pdf",))
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        # The path in the iframe src must be URL-encoded
        assert "DOJ%20Release%20Batch" in resp.text or "DOJ+Release+Batch" in resp.text

    def test_paths_with_parens_in_batch(self, client, tmp_dir, mock_db):
        """Batch names with parens (like court case names) must be URL-encoded."""
        _seed_recovery(tmp_dir, mock_db, batch="Doe v. Epstein (S.D. Fla. 2008)", filenames=("doc1.pdf",))
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        # Must not contain raw parens in the query parameter
        if "iframe" in resp.text:
            assert "path=Doe v." not in resp.text

    def test_donor_options_have_pdf_path_data(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert 'data-pdf-path="TestBatch/doc1.pdf"' in resp.text
        assert 'data-pdf-path="TestBatch/doc2.pdf"' in resp.text

    def test_tab_label_says_original_documents(self, client, tmp_dir, mock_db):
        """Tab button should say 'Original Documents', not 'Original PDFs'."""
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1")
        assert resp.status_code == 200
        assert "Original Documents" in resp.text
        assert "Original PDFs" not in resp.text

    def test_single_member_no_donor_pane(self, client, tmp_dir, mock_db):
        """With only 1 member, there should be no donor pane, no comparison controls."""
        _seed_recovery(tmp_dir, mock_db, filenames=("doc1.pdf",))
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert 'id="donor-pane"' not in resp.text
        assert "donor-select" not in resp.text
        assert "comparison.js" not in resp.text
        assert "updateDonor" not in resp.text


class TestOriginalPDFsTabPdfUrl:
    """Tests for pdf_url messaging in the Original PDFs tab."""

    def test_renders_source_link_when_pdf_url_present_no_cache(self, client, tmp_dir, mock_db):
        """When has_pdf and pdf_url but no local cache, new template shows a text pane."""
        _seed_recovery_with_pdf_url(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        # New behavior: single member without local PDF cache gets a text pane
        assert "log-viewer" in resp.text
        assert "primary-text" in resp.text

    def test_renders_plain_message_when_no_pdf_url_no_cache(self, client, tmp_dir, mock_db):
        """When has_pdf but no pdf_url and no cache, new template shows a text pane."""
        _seed_recovery_with_pdf_url(tmp_dir, mock_db, pdf_url=None)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        # New behavior: single member without local PDF cache gets a text pane
        assert "log-viewer" in resp.text
        assert "primary-text" in resp.text

    def test_iframe_when_cached_overrides_pdf_url(self, client, tmp_dir, mock_db):
        """When pdf_cache_path exists, show iframe regardless of pdf_url."""
        _seed_recovery_with_pdf_url(tmp_dir, mock_db, with_cache=True)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert "iframe" in resp.text
        assert "/pdf/embed?" in resp.text
        # Should NOT show the "not in local cache" message
        assert "not in local cache" not in resp.text

    def test_email_message_unchanged(self, client, tmp_dir, mock_db):
        """Email records now get a text pane (loaded via fetch) instead of a static message."""
        _seed_recovery_with_email(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert "log-viewer" in resp.text
        assert "primary-text" in resp.text

    def test_data_pdf_url_attribute_populated(self, client, tmp_dir, mock_db):
        """Select options have data-pdf-url attribute populated."""
        _seed_recovery_with_pdf_url(tmp_dir, mock_db, two_members=True)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert 'data-pdf-url="https://www.courtlistener.com/docket/99/doc1.pdf"' in resp.text

    def test_data_pdf_url_empty_when_no_url(self, client, tmp_dir, mock_db):
        """Select options have empty data-pdf-url when document has no url."""
        _seed_recovery_with_pdf_url(tmp_dir, mock_db, pdf_url=None, two_members=True)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert 'data-pdf-url=""' in resp.text

    def test_pdf_url_xss_in_template(self, client, tmp_dir, mock_db):
        """XSS in pdf_url should be escaped in both href and data attribute."""
        xss_url = '"><script>alert(1)</script><a href="'
        _seed_recovery_with_pdf_url(tmp_dir, mock_db, pdf_url=xss_url)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert "<script>alert(1)</script>" not in resp.text

    def test_pdf_url_xss_in_data_attribute(self, client, tmp_dir, mock_db):
        """XSS in data-pdf-url attribute should be escaped."""
        xss_url = '" onmouseover="alert(1)" data-x="'
        _seed_recovery_with_pdf_url(tmp_dir, mock_db, pdf_url=xss_url, two_members=True)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert 'onmouseover="alert(1)"' not in resp.text

    def test_updateDonor_reads_pdf_url(self, client, tmp_dir, mock_db):
        """The updateDonor JS function references dataset.pdfUrl."""
        _seed_recovery_with_pdf_url(tmp_dir, mock_db, two_members=True)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert "dataset.pdfUrl" in resp.text or "data-pdf-url" in resp.text

    def test_donor_pane_renders_link_for_pdf_url_member(self, client, tmp_dir, mock_db):
        """Donor pane (member[1]) shows source link when it has pdf_url but no cache."""
        _seed_recovery_with_pdf_url(tmp_dir, mock_db, two_members=True,
                                     second_pdf_url="https://example.com/donor.pdf")
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert "https://example.com/donor.pdf" in resp.text


class TestEmbedViewer:
    """Tests for the PDF embed viewer."""

    def test_embed_has_pdf_url_data_attribute(self, client, tmp_dir, mock_db):
        """The pdf_url should be in a data attribute on the container."""
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/pdf/embed?type=cache&path=TestBatch/doc1.pdf")
        assert 'data-pdf-url="/pdf/cache/TestBatch/doc1.pdf"' in resp.text

    def test_embed_has_loading_indicator(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/pdf/embed?type=cache&path=TestBatch/doc1.pdf")
        assert "Loading PDF" in resp.text

    def test_embed_has_error_element(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/pdf/embed?type=cache&path=TestBatch/doc1.pdf")
        assert "Failed to load PDF" in resp.text

    def test_embed_loads_external_script(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/pdf/embed?type=cache&path=TestBatch/doc1.pdf")
        assert "pdf-embed.js" in resp.text


class TestTextPaneRendering:
    """Tests for text mode in the Original Documents tab."""

    def test_email_members_get_text_panes(self, client, tmp_dir, mock_db):
        """Email-only members should get text pane placeholders, not 'No PDF' messages."""
        _seed_recovery_with_email(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert "No PDF available" not in resp.text
        assert "log-viewer" in resp.text

    def test_primary_pane_has_data_doc_id(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert 'data-doc-id="test-doc-0"' in resp.text

    def test_primary_pane_has_data_pdf_path(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert 'data-pdf-path="TestBatch/doc1.pdf"' in resp.text

    def test_pdf_mode_still_renders_iframes(self, client, tmp_dir, mock_db):
        _seed_recovery(tmp_dir, mock_db)
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert "iframe" in resp.text
        assert "/pdf/embed?" in resp.text

    def test_two_email_members_both_get_text_panes(self, client, tmp_dir, mock_db):
        import json as _json
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
            (_json.dumps(["email-doc-0", "email-doc-1"]),),
        )
        conn.commit()
        conn.close()
        resp = client.get("/recoveries/1/tab/original-pdfs")
        assert resp.status_code == 200
        assert "No PDF available" not in resp.text
        # New template uses log-viewer divs with ids primary-text and donor-text
        assert "primary-text" in resp.text
        assert "donor-text" in resp.text
        assert resp.text.count("log-viewer") >= 2


class TestSideBySideCSS:
    """Verify the CSS supports side-by-side and single-view modes."""

    def test_css_has_single_view_rule(self, client):
        resp = client.get("/static/css/app.css")
        assert resp.status_code == 200
        assert "single-view" in resp.text
        assert "display: none" in resp.text or "display:none" in resp.text


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
        # Tab should include text pane placeholder and external script
        tab_resp = client.get("/recoveries/1/tab/original-pdfs")
        assert tab_resp.status_code == 200
        assert "log-viewer" in tab_resp.text
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

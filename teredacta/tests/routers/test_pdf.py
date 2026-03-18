from pathlib import Path
import pytest

@pytest.fixture
def sample_pdf(tmp_dir):
    pdf_path = tmp_dir / "pdf_cache" / "test.pdf"
    pdf_path.write_bytes(
        b"%PDF-1.0\n1 0 obj<</Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000043 00000 n \n0000000096 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n170\n%%EOF"
    )
    return pdf_path

class TestPDFViewer:
    def test_serve_pdf(self, client, sample_pdf):
        resp = client.get("/pdf/cache/test.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    def test_serve_pdf_not_found(self, client):
        resp = client.get("/pdf/cache/nonexistent.pdf")
        assert resp.status_code == 404

    def test_path_traversal_blocked(self, client):
        resp = client.get("/pdf/cache/../../../etc/passwd")
        assert resp.status_code in (400, 404)

    def test_viewer_page(self, client, sample_pdf):
        resp = client.get("/pdf/view?type=cache&path=test.pdf")
        assert resp.status_code == 200
        assert "pdf" in resp.text.lower()

    def test_embed_page(self, client, sample_pdf):
        resp = client.get("/pdf/embed?type=cache&path=test.pdf")
        assert resp.status_code == 200
        assert "viewerContainer" in resp.text
        assert "/pdf/cache/test.pdf" in resp.text

    def test_embed_invalid_type(self, client):
        resp = client.get("/pdf/embed?type=evil&path=test.pdf")
        assert resp.status_code == 400

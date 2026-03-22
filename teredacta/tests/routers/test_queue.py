class TestJobQueue:
    def test_list_returns_200(self, client):
        resp = client.get("/admin/queue")
        assert resp.status_code == 200

    def test_filter_by_status(self, client):
        resp = client.get("/admin/queue?status=pending")
        assert resp.status_code == 200

class TestSummary:
    def test_summary_returns_200(self, client):
        resp = client.get("/summary")
        assert resp.status_code == 200

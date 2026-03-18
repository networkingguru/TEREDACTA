class TestRecoveries:
    def test_list_returns_200(self, client):
        resp = client.get("/recoveries")
        assert resp.status_code == 200

    def test_search_recoveries(self, client):
        resp = client.get("/recoveries?search=Maxwell")
        assert resp.status_code == 200

    def test_common_unredactions_endpoint(self, client):
        resp = client.get("/recoveries/common")
        assert resp.status_code == 200

    def test_search_htmx_returns_partial(self, client):
        resp = client.get("/recoveries?search=Maxwell", headers={"HX-Request": "true"})
        assert resp.status_code == 200
        # Should not contain full HTML page chrome
        assert "<html" not in resp.text.lower()

    def test_detail_not_found(self, client):
        resp = client.get("/recoveries/999")
        assert resp.status_code == 404

    def test_tab_merged_text(self, client):
        resp = client.get("/recoveries/1/tab/merged-text", headers={"HX-Request": "true"})
        assert resp.status_code in (200, 404)

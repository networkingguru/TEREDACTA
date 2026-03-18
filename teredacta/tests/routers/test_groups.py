class TestMatchGroups:
    def test_list_returns_200(self, client):
        resp = client.get("/groups")
        assert resp.status_code == 200

    def test_detail_not_found(self, client):
        resp = client.get("/groups/999")
        assert resp.status_code == 404

class TestHighlightsPage:
    """Test the highlights page."""

    def test_page_returns_200(self, client):
        resp = client.get("/highlights")
        assert resp.status_code == 200
        assert "Highlights" in resp.text

    def test_top_recoveries_section(self, client):
        resp = client.get("/highlights")
        assert resp.status_code == 200
        assert "Top Recoveries" in resp.text

    def test_notable_entities_section(self, client):
        resp = client.get("/highlights")
        assert resp.status_code == 200
        assert "Notable Entities" in resp.text

    def test_common_unredactions_section(self, client):
        resp = client.get("/highlights")
        assert resp.status_code == 200
        assert "Common Unredactions" in resp.text

    def test_with_entity_data(self, client_with_entities):
        resp = client_with_entities.get("/highlights")
        assert resp.status_code == 200
        assert "Top Recoveries" in resp.text
        # With fixture data there should be recovery cards
        assert "passage" in resp.text.lower()

    def test_entities_shown(self, client_with_entities):
        resp = client_with_entities.get("/highlights")
        assert resp.status_code == 200
        # Fixture has Jeffrey Epstein, Ghislaine Maxwell, etc.
        assert "Notable Entities" in resp.text
        # Should show entity type badges
        assert "entity-type-badge" in resp.text

    def test_empty_state_no_crash(self, client):
        """Page renders gracefully with no data."""
        resp = client.get("/highlights")
        assert resp.status_code == 200
        assert "No recoveries yet" in resp.text or "Top Recoveries" in resp.text

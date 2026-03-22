class TestEntityAPI:
    """Test /api/entities endpoints."""

    def test_entity_list_returns_200(self, client_with_entities):
        resp = client_with_entities.get("/api/entities")
        assert resp.status_code == 200
        assert "data-entity-id" in resp.text

    def test_entity_list_filter_by_type(self, client_with_entities):
        resp = client_with_entities.get("/api/entities?type=person")
        assert resp.status_code == 200
        # Should contain person entities from fixture data
        assert "person" in resp.text

    def test_entity_list_filter_by_name(self, client_with_entities):
        resp = client_with_entities.get("/api/entities?filter=Epstein")
        assert resp.status_code == 200
        assert "Epstein" in resp.text

    def test_entity_list_empty_filter(self, client_with_entities):
        resp = client_with_entities.get("/api/entities?filter=NONEXISTENT_ZZZZZ")
        assert resp.status_code == 200
        assert "No entities found" in resp.text

    def test_entity_list_pagination(self, client_with_entities):
        resp = client_with_entities.get("/api/entities?page=1")
        assert resp.status_code == 200

    def test_entity_connections_returns_200(self, client_with_entities):
        # Get an entity ID from the list first
        resp = client_with_entities.get("/api/entities")
        assert resp.status_code == 200
        # Parse an entity ID from the response
        import re
        match = re.search(r'data-entity-id="(\d+)"', resp.text)
        assert match, "Expected at least one entity in the list"
        entity_id = match.group(1)
        resp = client_with_entities.get(f"/api/entities/{entity_id}/connections")
        assert resp.status_code == 200
        assert "connections-list" in resp.text

    def test_entity_connections_404(self, client_with_entities):
        resp = client_with_entities.get("/api/entities/999999/connections")
        assert resp.status_code == 404

    def test_preview_recovery_returns_200(self, client_with_entities):
        # Group 100 exists in fixture
        resp = client_with_entities.get("/api/preview/recovery/100")
        assert resp.status_code == 200
        assert "Open Recovery" in resp.text

    def test_preview_recovery_404(self, client_with_entities):
        resp = client_with_entities.get("/api/preview/recovery/999999")
        assert resp.status_code == 404

    def test_preview_document_404(self, client_with_entities):
        resp = client_with_entities.get("/api/preview/document/NONEXISTENT_DOC")
        assert resp.status_code == 404

    def test_preview_entity_returns_200(self, client_with_entities):
        # Get a valid entity ID
        import re
        resp = client_with_entities.get("/api/entities")
        match = re.search(r'data-entity-id="(\d+)"', resp.text)
        assert match
        entity_id = match.group(1)
        resp = client_with_entities.get(f"/api/preview/entity/{entity_id}")
        assert resp.status_code == 200
        assert "preview-card" in resp.text
        assert "Explore" in resp.text

    def test_preview_entity_404(self, client_with_entities):
        resp = client_with_entities.get("/api/preview/entity/999999")
        assert resp.status_code == 404

    def test_connections_color_coding(self, client_with_entities):
        """Verify connection items have correct data-type attributes."""
        import re
        resp = client_with_entities.get("/api/entities")
        match = re.search(r'data-entity-id="(\d+)"', resp.text)
        assert match
        entity_id = match.group(1)
        resp = client_with_entities.get(f"/api/entities/{entity_id}/connections")
        assert resp.status_code == 200
        # Should have at least recovery connections
        assert 'data-type="recovery"' in resp.text or 'data-type="entity"' in resp.text

    def test_entity_list_has_type_badge(self, client_with_entities):
        resp = client_with_entities.get("/api/entities")
        assert resp.status_code == 200
        assert "entity-type-badge" in resp.text


class TestExplorePage:
    """Test the explore page loads."""

    def test_explore_page_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Explore" in resp.text

    def test_explore_page_with_entities(self, client_with_entities):
        resp = client_with_entities.get("/")
        assert resp.status_code == 200

    def test_explore_page_no_index_shows_message(self, client):
        """Without entity index built, page shows 'not been built' message."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "not been built" in resp.text


class TestExplorePageStructure:
    """Verify three-column layout renders with entity index."""

    def test_three_columns_present(self, client_with_entities):
        resp = client_with_entities.get("/")
        assert resp.status_code == 200
        assert "explore-container" in resp.text
        assert "entity-list-col" in resp.text
        assert "connections-col" in resp.text
        assert "preview-col" in resp.text

    def test_type_tabs_present(self, client_with_entities):
        resp = client_with_entities.get("/")
        assert resp.status_code == 200
        assert "entity-type-tabs" in resp.text
        assert 'data-type="person"' in resp.text
        assert 'data-type="org"' in resp.text

    def test_filter_input_present(self, client_with_entities):
        resp = client_with_entities.get("/")
        assert resp.status_code == 200
        assert "entity-filter" in resp.text

    def test_explore_js_loaded(self, client_with_entities):
        resp = client_with_entities.get("/")
        assert resp.status_code == 200
        assert "explore.js" in resp.text

    def test_htmx_entity_list_trigger(self, client_with_entities):
        resp = client_with_entities.get("/")
        assert resp.status_code == 200
        assert 'hx-get="/api/entities"' in resp.text

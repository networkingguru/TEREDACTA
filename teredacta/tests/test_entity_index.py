"""Tests for entity extraction and entity index."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from teredacta.entity_index import EntityIndex, extract_entities


class TestExtractEntities:
    """Test extract_entities() regex patterns and edge cases."""

    # --- People ---

    def test_person_title_case(self):
        entities = extract_entities("Meeting with Jeffrey Epstein at the office.")
        names = [e["name"] for e in entities if e["type"] == "person"]
        assert "Jeffrey Epstein" in names

    def test_person_with_middle_initial(self):
        entities = extract_entities("Report filed by James B. Comey.")
        names = [e["name"] for e in entities if e["type"] == "person"]
        assert "James B. Comey" in names

    def test_person_with_suffix(self):
        entities = extract_entities("Filed by Robert Smith Jr.")
        names = [e["name"] for e in entities if e["type"] == "person"]
        assert any("Robert Smith" in n for n in names)

    def test_person_all_caps_normalized(self):
        entities = extract_entities("JEFFREY EPSTEIN was mentioned in the filing.")
        names = [e["name"] for e in entities if e["type"] == "person"]
        assert "Jeffrey Epstein" in names

    def test_person_stop_list(self):
        entities = extract_entities("The United States Southern District filed a motion.")
        names = [e["name"] for e in entities if e["type"] == "person"]
        assert "United States" not in names
        assert "Southern District" not in names

    def test_person_stop_list_palm_beach(self):
        # Palm Beach should be a location, not a person
        entities = extract_entities("Located in Palm Beach county.")
        names = [e["name"] for e in entities if e["type"] == "person"]
        assert "Palm Beach" not in names

    def test_person_stop_list_federal_bureau(self):
        entities = extract_entities("The Federal Bureau of Investigation reviewed the case.")
        names = [e["name"] for e in entities if e["type"] == "person"]
        assert "Federal Bureau" not in names

    def test_multiple_people(self):
        text = "Ghislaine Maxwell and Alan Dershowitz appeared in court."
        entities = extract_entities(text)
        names = [e["name"] for e in entities if e["type"] == "person"]
        assert "Ghislaine Maxwell" in names
        assert "Alan Dershowitz" in names

    # --- Organizations ---

    def test_known_org(self):
        entities = extract_entities("The FBI investigated the case.")
        orgs = [e["name"] for e in entities if e["type"] == "org"]
        assert "FBI" in orgs

    def test_known_org_multi_word(self):
        entities = extract_entities("Goldman Sachs provided financial records.")
        orgs = [e["name"] for e in entities if e["type"] == "org"]
        assert "Goldman Sachs" in orgs

    def test_parenthetical_org(self):
        entities = extract_entities("Referred to the US Attorney (USANYS) office.")
        orgs = [e["name"] for e in entities if e["type"] == "org"]
        assert "USANYS" in orgs

    def test_parenthetical_known_org_no_dupe(self):
        entities = extract_entities("The FBI (FBI) handled the case.")
        orgs = [e["name"] for e in entities if e["type"] == "org"]
        assert orgs.count("FBI") == 1

    def test_multiple_known_orgs(self):
        entities = extract_entities("Both the DOJ and SEC reviewed the filings.")
        orgs = [e["name"] for e in entities if e["type"] == "org"]
        assert "DOJ" in orgs
        assert "SEC" in orgs

    # --- Locations ---

    def test_known_location(self):
        entities = extract_entities("The property in Palm Beach was searched.")
        locs = [e["name"] for e in entities if e["type"] == "location"]
        assert "Palm Beach" in locs

    def test_mar_a_lago(self):
        entities = extract_entities("Located near Mar-a-Lago resort.")
        locs = [e["name"] for e in entities if e["type"] == "location"]
        assert "Mar-a-Lago" in locs

    def test_virgin_islands(self):
        entities = extract_entities("Travel to Virgin Islands was documented.")
        locs = [e["name"] for e in entities if e["type"] == "location"]
        assert "Virgin Islands" in locs

    def test_little_st_james(self):
        entities = extract_entities("The island Little St. James was mentioned.")
        locs = [e["name"] for e in entities if e["type"] == "location"]
        assert "Little St. James" in locs

    # --- Emails ---

    def test_email(self):
        entities = extract_entities("Contact at user@example.com for details.")
        emails = [e["name"] for e in entities if e["type"] == "email"]
        assert "user@example.com" in emails

    def test_email_complex(self):
        entities = extract_entities("Send to john.doe+tag@law-firm.co.uk")
        emails = [e["name"] for e in entities if e["type"] == "email"]
        assert "john.doe+tag@law-firm.co.uk" in emails

    # --- Phones ---

    def test_phone_dashes(self):
        entities = extract_entities("Call 212-555-1234 for info.")
        phones = [e["name"] for e in entities if e["type"] == "phone"]
        assert any("212" in p and "555" in p and "1234" in p for p in phones)

    def test_phone_parens(self):
        entities = extract_entities("Phone: (212) 555-1234")
        phones = [e["name"] for e in entities if e["type"] == "phone"]
        assert len(phones) >= 1

    def test_phone_with_country_code(self):
        entities = extract_entities("Number: +1 212-555-1234")
        phones = [e["name"] for e in entities if e["type"] == "phone"]
        assert len(phones) >= 1

    # --- Edge cases ---

    def test_empty_text(self):
        assert extract_entities("") == []

    def test_none_text_returns_empty(self):
        # None should be handled gracefully
        assert extract_entities(None) == []

    def test_no_entities(self):
        entities = extract_entities("this is all lowercase with no entities at all.")
        assert len(entities) == 0

    def test_deduplication(self):
        text = "Jeffrey Epstein met with Jeffrey Epstein's lawyer."
        entities = extract_entities(text)
        person_names = [e["name"] for e in entities if e["type"] == "person"]
        assert person_names.count("Jeffrey Epstein") == 1

    def test_mixed_entity_types(self):
        text = (
            "Jeffrey Epstein contacted the FBI from Palm Beach. "
            "Email: jeff@example.com Phone: 212-555-0100"
        )
        entities = extract_entities(text)
        types = {e["type"] for e in entities}
        assert "person" in types
        assert "org" in types
        assert "location" in types
        assert "email" in types
        assert "phone" in types


class TestEntityIndex:
    """Test EntityIndex build, query, staleness, filtering."""

    @pytest.fixture
    def unob_db(self, tmp_path):
        """Create a mock Unobfuscator DB with recovery data."""
        db_path = tmp_path / "unobfuscator.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE merge_results (
                group_id INTEGER PRIMARY KEY,
                recovered_segments TEXT,
                recovered_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT '2020-01-01 00:00:00'
            );
        """)
        segments_1 = json.dumps([
            {"text": "Jeffrey Epstein traveled to Palm Beach with FBI escort."},
            {"text": "Contact: jeff@island.com or call 212-555-0100"},
        ])
        segments_2 = json.dumps([
            {"text": "Ghislaine Maxwell met with Goldman Sachs representatives in Manhattan."},
        ])
        segments_3 = json.dumps([
            {"text": "Jeffrey Epstein and Alan Dershowitz at Mar-a-Lago."},
        ])
        conn.execute(
            "INSERT INTO merge_results (group_id, recovered_segments, recovered_count) VALUES (1, ?, 2)",
            (segments_1,),
        )
        conn.execute(
            "INSERT INTO merge_results (group_id, recovered_segments, recovered_count) VALUES (2, ?, 1)",
            (segments_2,),
        )
        conn.execute(
            "INSERT INTO merge_results (group_id, recovered_segments, recovered_count) VALUES (3, ?, 1)",
            (segments_3,),
        )
        # A row with no recoveries — should be skipped
        conn.execute(
            "INSERT INTO merge_results (group_id, recovered_segments, recovered_count) VALUES (4, NULL, 0)"
        )
        conn.commit()
        conn.close()
        return db_path

    @pytest.fixture
    def entity_db_path(self, tmp_path):
        return str(tmp_path / "entities.db")

    @pytest.fixture
    def index(self, entity_db_path, unob_db):
        idx = EntityIndex(entity_db_path)
        idx.build(str(unob_db))
        return idx

    def test_build_returns_stats(self, entity_db_path, unob_db):
        idx = EntityIndex(entity_db_path)
        result = idx.build(str(unob_db))
        assert result["entities"] > 0
        assert result["mentions"] > 0
        assert result["built_at"] is not None

    def test_build_creates_entities(self, index):
        entities, total = index.list_entities()
        assert total > 0
        names = [e["name"] for e in entities]
        assert "Jeffrey Epstein" in names

    def test_build_creates_mentions(self, index):
        entities, _ = index.list_entities()
        epstein = next(e for e in entities if e["name"] == "Jeffrey Epstein")
        # Should appear in groups 1 and 3
        assert epstein["mention_count"] >= 2

    def test_status_ready(self, index, unob_db):
        status = index.get_status(str(unob_db))
        assert status["state"] == "ready"
        assert status["entities"] > 0
        assert status["built_at"] is not None

    def test_status_not_built(self, tmp_path):
        idx = EntityIndex(str(tmp_path / "nonexistent.db"))
        status = idx.get_status()
        assert status["state"] == "not_built"

    def test_status_stale(self, index, unob_db):
        # Insert a newer merge_result to make the index stale
        import time
        time.sleep(1.1)
        conn = sqlite3.connect(str(unob_db))
        conn.execute(
            "INSERT INTO merge_results (group_id, recovered_segments, recovered_count, created_at) "
            "VALUES (99, '[]', 1, datetime('now', '+1 day'))"
        )
        conn.commit()
        conn.close()
        status = index.get_status(str(unob_db))
        assert status["state"] == "stale"

    def test_list_entities_filter_type(self, index):
        persons, _ = index.list_entities(entity_type="person")
        assert all(e["type"] == "person" for e in persons)
        orgs, _ = index.list_entities(entity_type="org")
        assert all(e["type"] == "org" for e in orgs)

    def test_list_entities_filter_name(self, index):
        results, _ = index.list_entities(name_filter="Epstein")
        assert len(results) >= 1
        assert all("Epstein" in e["name"] for e in results)

    def test_list_entities_pagination(self, index):
        page1, total = index.list_entities(per_page=2, page=1)
        assert len(page1) <= 2
        if total > 2:
            page2, _ = index.list_entities(per_page=2, page=2)
            assert len(page2) > 0
            # Pages should not overlap
            ids1 = {e["id"] for e in page1}
            ids2 = {e["id"] for e in page2}
            assert ids1.isdisjoint(ids2)

    def test_get_entity(self, index):
        entities, _ = index.list_entities()
        eid = entities[0]["id"]
        entity = index.get_entity(eid)
        assert entity is not None
        assert entity["id"] == eid

    def test_get_entity_not_found(self, index):
        assert index.get_entity(99999) is None

    def test_get_connections(self, index):
        # Jeffrey Epstein should have connections
        entities, _ = index.list_entities(name_filter="Epstein")
        epstein = entities[0]
        conns = index.get_connections(epstein["id"])
        assert conns is not None
        assert conns["entity"]["name"] == "Jeffrey Epstein"
        assert len(conns["recoveries"]) >= 2
        assert len(conns["linked_entities"]) >= 1

    def test_get_connections_not_found(self, index):
        assert index.get_connections(99999) is None

    def test_rebuild_clears_old_data(self, entity_db_path, unob_db):
        idx = EntityIndex(entity_db_path)
        idx.build(str(unob_db))
        first_count = idx.list_entities()[1]
        # Rebuild should produce the same count (not doubled)
        idx.build(str(unob_db))
        second_count = idx.list_entities()[1]
        assert first_count == second_count

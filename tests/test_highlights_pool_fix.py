"""Adversarial tests for the connection pool fix in highlights/unob.

The fix:
  1. Added get_top_recoveries() to UnobInterface that properly acquires/releases.
  2. Changed highlights.py to use it instead of leaking via _get_db().

These tests verify no pool exhaustion, correct release, concurrency safety,
error propagation, return-type correctness, and that highlights.py no longer
touches _get_db directly.
"""

import ast
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teredacta.config import TeredactaConfig
from teredacta.unob import UnobInterface
from teredacta.db_pool import ConnectionPool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REAL_DB = Path("/root/Unobfuscator/data/unobfuscator.db")
HIGHLIGHTS_PY = Path(__file__).resolve().parent.parent / "teredacta" / "routers" / "highlights.py"


@pytest.fixture()
def tmp_db(tmp_path):
    """Create a minimal SQLite DB with the merge_results table."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE merge_results ("
        "  group_id INTEGER PRIMARY KEY,"
        "  recovered_count INTEGER,"
        "  recovered_segments TEXT"
        ")"
    )
    for i in range(1, 31):
        conn.execute(
            "INSERT INTO merge_results VALUES (?, ?, ?)",
            (i, 100 - i, f'[{{"text": "segment {i}"}}]'),
        )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def unob_tmp(tmp_db):
    """UnobInterface backed by the temp DB."""
    cfg = TeredactaConfig()
    cfg.db_path = str(tmp_db)
    ui = UnobInterface(cfg)
    yield ui
    ui.close()


@pytest.fixture()
def unob_real():
    """UnobInterface backed by the real Unobfuscator DB (skips if absent)."""
    if not REAL_DB.exists():
        pytest.skip("Real database not available")
    cfg = TeredactaConfig()
    cfg.db_path = str(REAL_DB)
    ui = UnobInterface(cfg)
    yield ui
    ui.close()


# ---------------------------------------------------------------------------
# 1. Pool-leak regression: N > max_size calls must not exhaust the pool
# ---------------------------------------------------------------------------

class TestPoolLeakRegression:
    """Verify that repeated calls don't leak connections."""

    def test_many_sequential_calls_no_exhaustion(self, unob_tmp):
        """Call get_top_recoveries 50 times (pool max is 8).
        If connections leak, we'd block/timeout after 8 calls."""
        for i in range(50):
            result = unob_tmp.get_top_recoveries(limit=5)
            assert isinstance(result, list)

    def test_pool_size_stays_bounded(self, unob_tmp):
        """After many calls the pool._size must never exceed max_size."""
        for _ in range(30):
            unob_tmp.get_top_recoveries(limit=5)
        pool = unob_tmp._pool
        assert pool is not None
        assert pool._size <= pool._max_size

    @pytest.mark.skipif(not REAL_DB.exists(), reason="Real DB not available")
    def test_many_sequential_calls_real_db(self, unob_real):
        """Same test against the real DB."""
        for _ in range(50):
            unob_real.get_top_recoveries(limit=5)


# ---------------------------------------------------------------------------
# 2. Connection release verification
# ---------------------------------------------------------------------------

class TestConnectionRelease:
    """After get_top_recoveries, pool must have connections available."""

    def test_connection_available_after_call(self, unob_tmp):
        unob_tmp.get_top_recoveries(limit=5)
        pool = unob_tmp._pool
        # We should be able to acquire a connection immediately
        conn = pool.acquire(timeout=1.0)
        assert conn is not None
        pool.release(conn)

    def test_all_connections_returned(self, unob_tmp):
        """After N calls, acquiring max_size connections should succeed."""
        for _ in range(20):
            unob_tmp.get_top_recoveries(limit=5)
        pool = unob_tmp._pool
        acquired = []
        for _ in range(pool._max_size):
            acquired.append(pool.acquire(timeout=2.0))
        # All acquired — release them
        for c in acquired:
            pool.release(c)

    def test_release_on_query_error(self, tmp_path):
        """If the query itself fails, connection must still be released."""
        # Create a DB with a broken schema (missing recovered_segments column)
        db_path = tmp_path / "broken.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE merge_results ("
            "  group_id INTEGER PRIMARY KEY,"
            "  recovered_count INTEGER"
            ")"
        )
        conn.execute("INSERT INTO merge_results VALUES (1, 5)")
        conn.commit()
        conn.close()

        cfg = TeredactaConfig()
        cfg.db_path = str(db_path)
        ui = UnobInterface(cfg)
        try:
            # get_top_recoveries should fail (recovered_segments column missing)
            with pytest.raises(sqlite3.OperationalError):
                ui.get_top_recoveries(limit=5)

            # Pool must still be usable — connection was released despite error
            pool = ui._pool
            assert pool is not None
            conn2 = pool.acquire(timeout=2.0)
            assert conn2 is not None
            pool.release(conn2)
        finally:
            ui.close()


# ---------------------------------------------------------------------------
# 3. Concurrent access — no deadlocks
# ---------------------------------------------------------------------------

class TestConcurrentAccess:
    """Multiple threads calling get_top_recoveries simultaneously."""

    def test_concurrent_calls_no_deadlock(self, unob_tmp):
        errors = []
        results = []
        barrier = threading.Barrier(16)

        def worker():
            try:
                barrier.wait(timeout=5)
                for _ in range(10):
                    r = unob_tmp.get_top_recoveries(limit=5)
                    results.append(len(r))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Errors in threads: {errors}"
        assert len(results) == 16 * 10

    def test_concurrent_with_close(self, unob_tmp):
        """Calling close() while threads are active should not hang forever."""
        barrier = threading.Barrier(5)
        errors = []

        def worker():
            try:
                barrier.wait(timeout=5)
                for _ in range(20):
                    try:
                        unob_tmp.get_top_recoveries(limit=2)
                    except (RuntimeError, TimeoutError):
                        # Expected after pool is closed
                        break
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        time.sleep(0.05)
        unob_tmp.close()
        for t in threads:
            t.join(timeout=10)
            assert not t.is_alive(), "Thread hung — possible deadlock"

    @pytest.mark.skipif(not REAL_DB.exists(), reason="Real DB not available")
    def test_concurrent_real_db(self, unob_real):
        errors = []
        barrier = threading.Barrier(8)

        def worker():
            try:
                barrier.wait(timeout=5)
                for _ in range(20):
                    unob_real.get_top_recoveries(limit=10)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors, f"Errors: {errors}"


# ---------------------------------------------------------------------------
# 4. Error handling — FileNotFoundError propagation
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_missing_db_raises_file_not_found(self):
        cfg = TeredactaConfig()
        cfg.db_path = "/nonexistent/path/to/database.db"
        ui = UnobInterface(cfg)
        with pytest.raises(FileNotFoundError, match="Database not found"):
            ui.get_top_recoveries(limit=5)

    def test_missing_db_message_includes_path(self):
        cfg = TeredactaConfig()
        cfg.db_path = "/tmp/does_not_exist_12345.db"
        ui = UnobInterface(cfg)
        with pytest.raises(FileNotFoundError, match="does_not_exist_12345"):
            ui.get_top_recoveries()

    def test_error_does_not_leave_pool_initialized(self):
        """If _get_db raises FileNotFoundError, pool stays None."""
        cfg = TeredactaConfig()
        cfg.db_path = "/nonexistent/db.sqlite3"
        ui = UnobInterface(cfg)
        with pytest.raises(FileNotFoundError):
            ui.get_top_recoveries()
        assert ui._pool is None


# ---------------------------------------------------------------------------
# 5. Return type correctness
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_list_of_dicts(self, unob_tmp):
        results = unob_tmp.get_top_recoveries(limit=5)
        assert isinstance(results, list)
        assert len(results) == 5
        for item in results:
            assert isinstance(item, dict)

    def test_dict_has_expected_keys(self, unob_tmp):
        results = unob_tmp.get_top_recoveries(limit=1)
        assert len(results) >= 1
        row = results[0]
        assert "group_id" in row
        assert "recovered_count" in row
        assert "recovered_segments" in row

    def test_ordered_by_recovered_count_desc(self, unob_tmp):
        results = unob_tmp.get_top_recoveries(limit=20)
        counts = [r["recovered_count"] for r in results]
        assert counts == sorted(counts, reverse=True)

    def test_limit_respected(self, unob_tmp):
        for lim in (1, 5, 10, 20, 100):
            results = unob_tmp.get_top_recoveries(limit=lim)
            assert len(results) <= lim

    def test_empty_table_returns_empty_list(self, tmp_path):
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE merge_results ("
            "  group_id INTEGER, recovered_count INTEGER, recovered_segments TEXT)"
        )
        conn.commit()
        conn.close()
        cfg = TeredactaConfig()
        cfg.db_path = str(db_path)
        ui = UnobInterface(cfg)
        try:
            assert ui.get_top_recoveries() == []
        finally:
            ui.close()

    def test_zero_recovered_count_excluded(self, tmp_path):
        """Rows with recovered_count=0 should not appear (WHERE clause)."""
        db_path = tmp_path / "zeros.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE merge_results ("
            "  group_id INTEGER, recovered_count INTEGER, recovered_segments TEXT)"
        )
        conn.execute("INSERT INTO merge_results VALUES (1, 0, '[]')")
        conn.execute("INSERT INTO merge_results VALUES (2, 3, '[]')")
        conn.commit()
        conn.close()
        cfg = TeredactaConfig()
        cfg.db_path = str(db_path)
        ui = UnobInterface(cfg)
        try:
            results = ui.get_top_recoveries()
            assert len(results) == 1
            assert results[0]["group_id"] == 2
        finally:
            ui.close()

    @pytest.mark.skipif(not REAL_DB.exists(), reason="Real DB not available")
    def test_real_db_return_type(self, unob_real):
        results = unob_real.get_top_recoveries(limit=3)
        assert isinstance(results, list)
        if results:
            assert all(
                {"group_id", "recovered_count", "recovered_segments"} <= set(r.keys())
                for r in results
            )


# ---------------------------------------------------------------------------
# 6. Highlights router must NOT use _get_db directly
# ---------------------------------------------------------------------------

class TestHighlightsNoDirectPoolAccess:
    """Static analysis: highlights.py must not call _get_db or _release_db."""

    def test_no_get_db_in_source(self):
        source = HIGHLIGHTS_PY.read_text()
        assert "_get_db" not in source, (
            "highlights.py still references _get_db — pool leak regression"
        )

    def test_no_release_db_in_source(self):
        source = HIGHLIGHTS_PY.read_text()
        assert "_release_db" not in source, (
            "highlights.py references _release_db — should use public API"
        )

    def test_no_pool_attribute_access(self):
        source = HIGHLIGHTS_PY.read_text()
        assert "._pool" not in source, (
            "highlights.py accesses ._pool directly"
        )

    def test_uses_get_top_recoveries(self):
        source = HIGHLIGHTS_PY.read_text()
        assert "get_top_recoveries" in source, (
            "highlights.py should call get_top_recoveries()"
        )

    def test_ast_no_private_method_calls(self):
        """Parse the AST to verify no attribute access to _get_db on any object."""
        source = HIGHLIGHTS_PY.read_text()
        tree = ast.parse(source)
        private_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in ("_get_db", "_release_db", "_pool"):
                    private_calls.append(node.attr)
        assert not private_calls, (
            f"highlights.py uses private pool methods: {private_calls}"
        )


# ---------------------------------------------------------------------------
# 7. ConnectionPool unit-level adversarial tests
# ---------------------------------------------------------------------------

class TestConnectionPoolDirect:
    """Directly test the pool to ensure it doesn't leak under stress."""

    def test_acquire_release_cycle(self, tmp_db):
        pool = ConnectionPool(str(tmp_db), max_size=2)
        try:
            for _ in range(100):
                c = pool.acquire(timeout=2.0)
                c.execute("SELECT 1")
                pool.release(c)
        finally:
            pool.close()

    def test_exhaust_then_release(self, tmp_db):
        """Acquire all connections, then release, then acquire again."""
        pool = ConnectionPool(str(tmp_db), max_size=4)
        try:
            conns = [pool.acquire(timeout=2.0) for _ in range(4)]
            # Pool is now exhausted — next acquire should timeout quickly
            with pytest.raises(TimeoutError):
                pool.acquire(timeout=0.1)
            # Release all
            for c in conns:
                pool.release(c)
            # Should work again
            c = pool.acquire(timeout=1.0)
            pool.release(c)
        finally:
            pool.close()

    def test_release_in_finally_pattern(self, tmp_db):
        """Simulate the acquire/try/finally/release pattern many times."""
        pool = ConnectionPool(str(tmp_db), max_size=2)
        try:
            for _ in range(50):
                conn = pool.acquire(timeout=2.0)
                try:
                    conn.execute("SELECT 1")
                finally:
                    pool.release(conn)
        finally:
            pool.close()

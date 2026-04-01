"""Stress tests for DB connection pool under contention."""

import sqlite3
import threading
import time

import pytest

from teredacta.db_pool import ConnectionPool


@pytest.mark.stress
@pytest.mark.timeout(90)
class TestDBPoolContention:
    @pytest.fixture
    def stress_db(self, tmp_path):
        """Create a DB with enough data for non-trivial queries."""
        db_path = tmp_path / "stress.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE documents ("
            "id TEXT PRIMARY KEY, source TEXT, extracted_text TEXT, "
            "text_processed BOOLEAN DEFAULT 0, pdf_processed BOOLEAN DEFAULT 0, "
            "original_filename TEXT, page_count INTEGER, size_bytes INTEGER)"
        )
        # Insert 100k rows for meaningful query pressure
        rows = [
            (f"doc-{i}", f"source-{i % 10}", f"text content for document {i} " * 50,
             i % 3 == 0, i % 5 == 0, f"file_{i}.pdf", (i % 20) + 1, (i % 1000) * 1024)
            for i in range(100_000)
        ]
        conn.executemany(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
        conn.commit()
        conn.close()
        return db_path

    @pytest.fixture
    def pool(self, stress_db):
        p = ConnectionPool(str(stress_db), max_size=8, read_only=True)
        yield p
        p.close()

    def test_50_threads_no_deadlock(self, pool, stress_db):
        """50 threads compete for 8 connections — all must complete."""
        results = []
        errors = []

        def worker(thread_id):
            try:
                conn = pool.acquire(timeout=10.0)
                try:
                    # Simulate a non-trivial query
                    row = conn.execute(
                        "SELECT COUNT(*) FROM documents WHERE extracted_text LIKE ?",
                        (f"%document {thread_id % 100}%",),
                    ).fetchone()
                    results.append((thread_id, row[0]))
                finally:
                    pool.release(conn)
            except TimeoutError:
                results.append((thread_id, "timeout"))
            except Exception as e:
                errors.append((thread_id, str(e)))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # All threads must have completed (not hung)
        assert len(results) + len(errors) == 50, (
            f"Only {len(results) + len(errors)}/50 threads completed"
        )
        assert not errors, f"Unexpected errors: {errors}"

    def test_pool_recovers_after_burst(self, pool, stress_db):
        """After a burst of contention, pool returns to normal."""
        # Phase 1: burst — hold all connections for 1 second
        held = []
        for _ in range(8):
            held.append(pool.acquire(timeout=5.0))

        status_during = pool.pool_status()
        assert status_during["idle"] == 0
        assert status_during["in_use"] == 8

        # Release all
        for conn in held:
            pool.release(conn)

        # Phase 2: verify recovery
        status_after = pool.pool_status()
        assert status_after["idle"] == 8
        assert status_after["in_use"] == 0

        # New acquire should succeed instantly
        conn = pool.acquire(timeout=1.0)
        pool.release(conn)

    def test_timeout_error_no_leak(self, pool, stress_db):
        """TimeoutError on acquire does not leak connections."""
        # Hold all 8
        held = []
        for _ in range(8):
            held.append(pool.acquire(timeout=5.0))

        # Short-timeout acquire should raise TimeoutError
        with pytest.raises(TimeoutError):
            pool.acquire(timeout=0.5)

        # Pool status should still show 8 in use (not 9)
        status = pool.pool_status()
        assert status["in_use"] == 8
        assert status["capacity"] == 8

        for conn in held:
            pool.release(conn)

        # After release, all 8 should be idle
        status = pool.pool_status()
        assert status["idle"] == 8

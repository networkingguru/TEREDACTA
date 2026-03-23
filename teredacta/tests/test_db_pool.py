import sqlite3
import threading
from teredacta.db_pool import ConnectionPool

def test_pool_returns_connection(tmp_path):
    db_path = tmp_path / "test.db"
    sqlite3.connect(str(db_path)).close()
    pool = ConnectionPool(str(db_path), max_size=2, read_only=True)
    conn = pool.acquire()
    assert conn is not None
    pool.release(conn)
    pool.close()

def test_pool_reuses_connections(tmp_path):
    db_path = tmp_path / "test.db"
    sqlite3.connect(str(db_path)).close()
    pool = ConnectionPool(str(db_path), max_size=2, read_only=True)
    conn1 = pool.acquire()
    pool.release(conn1)
    conn2 = pool.acquire()
    assert conn1 is conn2
    pool.release(conn2)
    pool.close()

def test_pool_context_manager(tmp_path):
    db_path = tmp_path / "test.db"
    sqlite3.connect(str(db_path)).close()
    pool = ConnectionPool(str(db_path), max_size=2, read_only=True)
    with pool.connection() as conn:
        assert conn is not None
    pool.close()

def test_pool_max_size(tmp_path):
    db_path = tmp_path / "test.db"
    sqlite3.connect(str(db_path)).close()
    pool = ConnectionPool(str(db_path), max_size=2, read_only=True)
    c1 = pool.acquire()
    c2 = pool.acquire()
    try:
        c3 = pool.acquire(timeout=0.1)
        pool.release(c3)
        assert False, "Should have raised"
    except TimeoutError:
        pass
    pool.release(c1)
    pool.release(c2)
    pool.close()

def test_pool_threaded(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.commit()
    conn.close()
    pool = ConnectionPool(str(db_path), max_size=4, read_only=True)
    results = []
    def worker():
        with pool.connection() as c:
            row = c.execute("SELECT 1").fetchone()
            results.append(row[0])
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8
    assert all(r == 1 for r in results)
    pool.close()

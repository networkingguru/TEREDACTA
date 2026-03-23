"""Thread-safe SQLite connection pool."""

import queue
import sqlite3
import threading
from contextlib import contextmanager
from typing import Optional


class ConnectionPool:
    """Reusable pool of SQLite connections.

    Connections are created lazily up to *max_size*. When all connections
    are in use, acquire() blocks until one is returned.
    """

    def __init__(
        self,
        db_path: str,
        max_size: int = 8,
        read_only: bool = False,
        busy_timeout: int = 5000,
    ):
        self._db_path = db_path
        self._max_size = max_size
        self._read_only = read_only
        self._busy_timeout = busy_timeout
        self._pool: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=max_size)
        self._size = 0
        self._lock = threading.Lock()
        self._closed = False

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path, timeout=self._busy_timeout / 1000, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {self._busy_timeout}")
        if self._read_only:
            conn.execute("PRAGMA query_only = ON")
        return conn

    def acquire(self, timeout: Optional[float] = 30.0) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("Pool is closed")
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            if self._size < self._max_size:
                self._size += 1
                try:
                    return self._create_connection()
                except Exception:
                    self._size -= 1
                    raise
        try:
            return self._pool.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"Could not acquire connection within {timeout}s")

    def release(self, conn: sqlite3.Connection):
        if self._closed:
            conn.close()
            return
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            conn.close()
            with self._lock:
                self._size -= 1

    @contextmanager
    def connection(self):
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)

    def close(self):
        self._closed = True
        while True:
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break

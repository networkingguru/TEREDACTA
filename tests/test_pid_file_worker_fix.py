"""
Tests that the atexit handler registered in the daemon child only removes
the PID file when os.getpid() matches the PID captured at registration time.
This prevents worker processes (forked by uvicorn) from deleting the PID file.
"""
import os
import tempfile
import unittest
from unittest.mock import patch


class TestPidFileWorkerFix(unittest.TestCase):
    def _make_handler(self, pid_file, daemon_pid):
        """Replicate the exact lambda registered in __main__.py."""
        return lambda: os.getpid() == daemon_pid and os.path.exists(pid_file) and os.remove(pid_file)

    def test_handler_removes_file_when_pid_matches(self):
        """Handler removes PID file when called from the daemon process."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            pid_file = f.name
        try:
            daemon_pid = os.getpid()
            handler = self._make_handler(pid_file, daemon_pid)
            handler()
            self.assertFalse(os.path.exists(pid_file), "PID file should be removed by daemon process")
        finally:
            if os.path.exists(pid_file):
                os.remove(pid_file)

    def test_handler_does_not_remove_file_when_pid_differs(self):
        """Handler is a no-op when called from a worker (different PID)."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            pid_file = f.name
        try:
            # Simulate a worker: daemon_pid is some other process's PID
            fake_daemon_pid = os.getpid() + 9999
            handler = self._make_handler(pid_file, fake_daemon_pid)
            handler()
            self.assertTrue(os.path.exists(pid_file), "PID file must NOT be removed by worker process")
        finally:
            if os.path.exists(pid_file):
                os.remove(pid_file)

    def test_handler_is_safe_when_file_already_gone(self):
        """Handler does not raise even if the PID file was already removed."""
        with tempfile.TemporaryDirectory() as d:
            pid_file = os.path.join(d, "teredacta.pid")
            # File does not exist
            daemon_pid = os.getpid()
            handler = self._make_handler(pid_file, daemon_pid)
            # Should not raise
            try:
                handler()
            except Exception as exc:
                self.fail(f"Handler raised unexpectedly: {exc}")

    def test_main_module_registers_pid_check(self):
        """Verify __main__.py source contains the PID-guard pattern."""
        import inspect
        import pathlib
        src = pathlib.Path(__file__).parent.parent / "teredacta" / "__main__.py"
        text = src.read_text()
        self.assertIn("_daemon_pid = os.getpid()", text,
                      "_daemon_pid capture must be present in __main__.py")
        self.assertIn("os.getpid() == _daemon_pid", text,
                      "PID equality check must be present in atexit lambda")


if __name__ == "__main__":
    unittest.main()

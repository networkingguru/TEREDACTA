"""Adversarial + user-focused tests for the daemon stop command.

The bug: `teredacta stop` sent SIGTERM then immediately printed "Stopped"
and removed the PID file without verifying the process actually exited.
This meant a still-running server appeared stopped.

Fix: verify process exit after SIGTERM, escalate to SIGKILL if needed.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time

import pytest
from click.testing import CliRunner

from teredacta.__main__ import cli


@pytest.fixture
def pid_file(tmp_path):
    return str(tmp_path / "test.pid")


@pytest.fixture
def runner():
    return CliRunner()


# --- Adversarial: stop must actually stop ---


def test_stop_kills_real_process(pid_file, runner):
    """Stop must actually terminate a running process, not just claim it did."""
    # Start a real subprocess that ignores nothing (easy to kill)
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    with open(pid_file, "w") as f:
        f.write(str(proc.pid))

    result = runner.invoke(cli, ["stop", "--pid-file", pid_file])
    assert result.exit_code == 0
    assert "Stopped" in result.output

    # Verify the process is actually dead
    time.sleep(0.2)
    assert proc.poll() is not None, "Process still running after stop!"


def test_stop_escalates_to_sigkill_for_stubborn_process(pid_file, runner):
    """If a process ignores SIGTERM, stop must escalate to SIGKILL."""
    # Start a process that traps SIGTERM and ignores it
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"],
    )
    with open(pid_file, "w") as f:
        f.write(str(proc.pid))

    result = runner.invoke(cli, ["stop", "--pid-file", pid_file])
    assert result.exit_code == 0
    assert "SIGKILL" in result.output or "Stopped" in result.output

    # Verify the process is actually dead
    time.sleep(0.3)
    assert proc.poll() is not None, "SIGTERM-ignoring process still alive after stop!"


def test_stop_with_stale_pid_file(pid_file, runner):
    """If the PID file references a dead process, stop should clean up gracefully."""
    with open(pid_file, "w") as f:
        f.write("999999999")  # Almost certainly not a real PID

    result = runner.invoke(cli, ["stop", "--pid-file", pid_file])
    assert result.exit_code == 0
    assert "already gone" in result.output
    assert not os.path.exists(pid_file), "Stale PID file not cleaned up"


def test_stop_with_no_pid_file(pid_file, runner):
    """Stop without a PID file should report not running."""
    result = runner.invoke(cli, ["stop", "--pid-file", pid_file])
    assert result.exit_code != 0
    assert "Not running" in result.output


def test_stop_removes_pid_file(pid_file, runner):
    """PID file must be removed after successful stop."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    with open(pid_file, "w") as f:
        f.write(str(proc.pid))

    runner.invoke(cli, ["stop", "--pid-file", pid_file])
    assert not os.path.exists(pid_file), "PID file still exists after stop"


# --- User-focused: the experience of running start then stop ---


def test_start_already_running_rejects(pid_file, runner, tmp_path):
    """If server is running, `start` should refuse with a clear message."""
    # Create a real process to simulate "already running"
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    with open(pid_file, "w") as f:
        f.write(str(proc.pid))

    result = runner.invoke(cli, [
        "start",
        "--pid-file", pid_file,
        "--log-file", str(tmp_path / "test.log"),
    ])
    assert "Already running" in result.output
    assert result.exit_code != 0

    # Cleanup
    proc.terminate()
    proc.wait()


def test_stop_then_start_works(pid_file, runner):
    """After stopping, the PID file is gone so start can proceed."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
    )
    with open(pid_file, "w") as f:
        f.write(str(proc.pid))

    # Stop it
    result = runner.invoke(cli, ["stop", "--pid-file", pid_file])
    assert "Stopped" in result.output
    assert not os.path.exists(pid_file)

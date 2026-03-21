import os
import signal
import sys
from pathlib import Path
import click

_DEFAULT_PID_FILE = "/tmp/teredacta.pid"
_DEFAULT_LOG_FILE = "/tmp/teredacta.log"


def _load_and_patch_cfg(config_path, host, port):
    from teredacta.config import load_config
    cfg = load_config(config_path)
    if host:
        cfg.host = host
    if port:
        cfg.port = port
    return cfg


def _print_banner(cfg):
    click.echo(f"\n  TEREDACTA v{__import__('teredacta').__version__}")
    click.echo(f"  Mode: {'Local' if cfg.is_local_mode else 'Server'}")
    click.echo(f"  URL:  http://{cfg.host}:{cfg.port}")
    if cfg.is_local_mode and not cfg.admin_requires_login:
        click.echo("  Admin: enabled (no login required)")
    elif cfg.admin_enabled:
        click.echo("  Admin: enabled (login required)")
    else:
        click.echo("  Admin: disabled (set password to enable)")
    click.echo()


@click.group()
def cli():
    """TEREDACTA — Web interface for Unobfuscator."""
    pass


@cli.command()
@click.option("--host", default=None, help="Bind host (overrides config)")
@click.option("--port", default=None, type=int, help="Bind port (overrides config)")
@click.option("--config", "config_path", default=None, help="Path to config file")
def run(host, port, config_path):
    """Start the TEREDACTA web server (foreground)."""
    from teredacta.app import create_app
    import uvicorn

    cfg = _load_and_patch_cfg(config_path, host, port)
    _print_banner(cfg)
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port)


@cli.command()
@click.option("--host", default=None, help="Bind host (overrides config)")
@click.option("--port", default=None, type=int, help="Bind port (overrides config)")
@click.option("--config", "config_path", default=None, help="Path to config file")
@click.option("--pid-file", default=_DEFAULT_PID_FILE, show_default=True)
@click.option("--log-file", default=_DEFAULT_LOG_FILE, show_default=True)
def start(host, port, config_path, pid_file, log_file):
    """Start TEREDACTA as a background daemon."""
    if os.path.exists(pid_file):
        with open(pid_file) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, 0)
            click.echo(f"Already running (PID {pid}). Run 'teredacta stop' first.")
            sys.exit(1)
        except ProcessLookupError:
            os.remove(pid_file)

    if sys.platform == "win32":
        click.echo("Error: Daemon mode is not supported on Windows.")
        click.echo("Use 'teredacta run' to start in the foreground instead.")
        sys.exit(1)

    cfg = _load_and_patch_cfg(config_path, host, port)

    pid = os.fork()
    if pid > 0:
        # Parent: write PID file and exit.
        with open(pid_file, "w") as f:
            f.write(str(pid))
        click.echo(f"  TEREDACTA started (PID {pid})")
        click.echo(f"  URL:  http://{cfg.host}:{cfg.port}")
        click.echo(f"  Log:  {log_file}")
        click.echo(f"  Stop: teredacta stop")
        return

    # Child: close stdin and detach from terminal.
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, sys.stdin.fileno())
    os.close(devnull)
    os.setsid()
    import atexit
    atexit.register(lambda: os.path.exists(pid_file) and os.remove(pid_file))
    with open(log_file, "a") as log:
        os.dup2(log.fileno(), sys.stdout.fileno())
        os.dup2(log.fileno(), sys.stderr.fileno())

    from teredacta.app import create_app
    import uvicorn
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port)


@cli.command()
@click.option("--pid-file", default=_DEFAULT_PID_FILE, show_default=True)
def stop(pid_file):
    """Stop the TEREDACTA background daemon."""
    if not os.path.exists(pid_file):
        click.echo("Not running (no PID file found).")
        sys.exit(1)
    pid = int(Path(pid_file).read_text().strip())
    try:
        os.kill(pid, 0)  # Check if process exists first
    except ProcessLookupError:
        os.remove(pid_file)
        click.echo("Process was already gone; PID file removed.")
        return

    # Send SIGTERM and wait for process to actually exit
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        os.remove(pid_file)
        click.echo("Process exited before signal could be sent; PID file removed.")
        return
    except PermissionError:
        click.echo(f"Permission denied sending signal to PID {pid}. Is it owned by another user?")
        sys.exit(1)
    import time
    for _ in range(30):  # Wait up to 3 seconds
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            os.remove(pid_file)
            click.echo(f"Stopped (PID {pid}).")
            return

    # Still alive — force kill
    click.echo(f"Process {pid} didn't exit gracefully, sending SIGKILL...")
    try:
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.2)
    except ProcessLookupError:
        pass
    os.remove(pid_file)
    click.echo(f"Stopped (PID {pid}).")


@cli.command()
def install():
    """Run the guided installation wizard."""
    from teredacta.installer.wizard import run_wizard
    run_wizard()


if __name__ == "__main__":
    cli()

import os
import signal
import sys
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

    # Child: detach from terminal.
    os.setsid()
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
    pid = int(open(pid_file).read().strip())
    try:
        os.kill(pid, 0)  # Check if process exists first
    except ProcessLookupError:
        os.remove(pid_file)
        click.echo("Process was already gone; PID file removed.")
        return

    # Send SIGTERM and wait for process to actually exit
    os.kill(pid, signal.SIGTERM)
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

import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
import click

_DEFAULT_PID_FILE = "/tmp/teredacta.pid"
_DEFAULT_LOG_FILE = "/tmp/teredacta.log"


def setup_logging(cfg):
    """Configure Python logging from TeredactaConfig. Idempotent."""
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)
    root.addHandler(stderr_handler)

    if cfg.log_path:
        file_handler = RotatingFileHandler(
            cfg.log_path, maxBytes=10_485_760, backupCount=5
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    _original_excepthook = sys.excepthook

    def _exception_handler(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            _original_excepthook(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("teredacta").critical(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = _exception_handler


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
@click.option("--workers", "workers_override", default=None, type=int, help="Number of worker processes")
def run(host, port, config_path, workers_override):
    """Start the TEREDACTA web server (foreground)."""
    import uvicorn

    cfg = _load_and_patch_cfg(config_path, host, port)
    setup_logging(cfg)
    if workers_override:
        cfg.workers = workers_override
    if cfg.workers < 1:
        click.echo("Error: workers must be >= 1")
        sys.exit(1)
    _print_banner(cfg)

    if cfg.workers > 1:
        # Multi-worker requires import string, not app instance.
        # Store config in env so _app_factory.py can reconstruct it.
        # Empty string → None round-trip is handled by the factory.
        import os
        os.environ["_TEREDACTA_CONFIG_PATH"] = config_path or ""
        os.environ["_TEREDACTA_SECRET_KEY"] = cfg.secret_key
        if host:
            os.environ["_TEREDACTA_HOST"] = host
        if port:
            os.environ["_TEREDACTA_PORT"] = str(port)
        uvicorn.run("teredacta._app_factory:app", host=cfg.host, port=cfg.port, workers=cfg.workers, log_config=None)
    else:
        from teredacta.app import create_app
        app = create_app(cfg)
        uvicorn.run(app, host=cfg.host, port=cfg.port, log_config=None)


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

    if cfg.workers > 1:
        # Multi-worker requires import string. Pass config via env.
        os.environ["_TEREDACTA_CONFIG_PATH"] = config_path or ""
        os.environ["_TEREDACTA_SECRET_KEY"] = cfg.secret_key
        if host:
            os.environ["_TEREDACTA_HOST"] = host
        if port:
            os.environ["_TEREDACTA_PORT"] = str(port)

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
    setup_logging(cfg)
    import atexit
    _daemon_pid = os.getpid()
    atexit.register(lambda: os.getpid() == _daemon_pid and os.path.exists(pid_file) and os.remove(pid_file))
    with open(log_file, "a") as log:
        os.dup2(log.fileno(), sys.stdout.fileno())
        os.dup2(log.fileno(), sys.stderr.fileno())

    import uvicorn
    if cfg.workers > 1:
        uvicorn.run("teredacta._app_factory:app", host=cfg.host, port=cfg.port, workers=cfg.workers, log_config=None)
    else:
        from teredacta.app import create_app
        app = create_app(cfg)
        uvicorn.run(app, host=cfg.host, port=cfg.port, log_config=None)


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


@cli.command("reset-password")
@click.option("--config", "config_path", default=None, help="Path to config file")
@click.option("--remove", is_flag=True, help="Remove the admin password (disable remote admin)")
def reset_password(config_path, remove):
    """Set or reset the admin password in your config file."""
    import bcrypt
    import yaml
    from teredacta.config import config_search_paths

    # Find config file
    if config_path is None:
        for candidate in config_search_paths():
            if candidate.exists():
                config_path = str(candidate)
                break

    if config_path is None:
        click.echo("Error: No config file found. Searched:")
        for p in config_search_paths():
            click.echo(f"  {p}")
        click.echo("\nSpecify one with --config or run 'teredacta install' first.")
        sys.exit(1)

    config_file = Path(config_path)
    if not config_file.exists():
        click.echo(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    click.echo(f"Config file: {config_file}")

    with open(config_file) as f:
        data = yaml.safe_load(f) or {}

    if remove:
        data.pop("admin_password_hash", None)
        with open(config_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        click.echo("Admin password removed. Remote admin access is now disabled.")
        return

    password = click.prompt("New admin password", hide_input=True)
    confirm = click.prompt("Confirm password", hide_input=True)
    if password != confirm:
        click.echo("Error: Passwords do not match.")
        sys.exit(1)
    if len(password) < 8:
        click.echo("Error: Password must be at least 8 characters.")
        sys.exit(1)

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    data["admin_password_hash"] = hashed

    with open(config_file, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    click.echo("Admin password updated successfully.")


if __name__ == "__main__":
    cli()

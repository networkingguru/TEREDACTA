import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import click
import yaml


_UNOB_REPO_SSH = "git@github.com:networkingguru/Unobfuscator.git"
_UNOB_REPO_HTTPS = "https://github.com/networkingguru/Unobfuscator.git"

def _unob_search_paths() -> list[Path]:
    """Build search paths at call time so cwd() is current."""
    return [
        Path.cwd() / "Unobfuscator",
        Path.cwd().parent / "Unobfuscator",
        Path.home() / "Unobfuscator",
        Path.home() / "Scripts" / "Unobfuscator",
        Path.home() / "src" / "Unobfuscator",
        Path.home() / "projects" / "Unobfuscator",
    ]


def run_wizard():
    """Interactive installation wizard.

    Finds or installs Unobfuscator, writes a TEREDACTA config, and
    optionally starts both the Unobfuscator daemon and the web server.
    """
    click.echo("\n  TEREDACTA Installer\n")

    # --- Step 1: Find or install Unobfuscator ---
    unob_path = _find_unobfuscator()
    if unob_path:
        click.echo(f"  Found Unobfuscator at {unob_path}")
    else:
        click.echo("  Unobfuscator not found.")
        unob_path = _install_unobfuscator()
        if not unob_path:
            click.echo("\n  Cannot proceed without Unobfuscator. Exiting.")
            sys.exit(1)

    # --- Step 2: Verify Unobfuscator dependencies ---
    _ensure_unob_deps(unob_path)

    # --- Step 3: Locate data paths ---
    # Unobfuscator keeps its own config.yaml — read it to find paths
    unob_cfg = _read_unob_config(unob_path)
    db_path = _resolve(unob_path, unob_cfg.get("db_path", "data/unobfuscator.db"))
    pdf_cache = _resolve(unob_path, unob_cfg.get("cache_dir", "data/cache"))
    output_dir = _resolve(unob_path, unob_cfg.get("output_dir", "output"))
    log_path = db_path.parent / "unobfuscator.log"

    # Also check for pdf_cache dir alongside data/
    alt_cache = unob_path / "pdf_cache"
    if alt_cache.is_dir() and not pdf_cache.is_dir():
        pdf_cache = alt_cache

    click.echo(f"  Database:  {db_path}")
    click.echo(f"  PDF cache: {pdf_cache}")
    click.echo(f"  Output:    {output_dir}")

    # --- Step 4: Deployment mode ---
    system = platform.system()
    mode = click.prompt(
        "\n  Deployment mode", type=click.Choice(["local", "server"]), default="local"
    )
    host = "127.0.0.1" if mode == "local" else "0.0.0.0"
    port = click.prompt("  Port", default=8000, type=int)

    admin_password_hash = None
    if mode == "server":
        password = click.prompt("  Admin password", hide_input=True, confirmation_prompt=True)
        import bcrypt
        admin_password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    # --- Step 5: Build and write TEREDACTA config ---
    unob_bin = _find_unob_python(unob_path)
    config = {
        "unobfuscator_path": str(unob_path),
        "unobfuscator_bin": f"{unob_bin} {unob_path / 'unobfuscator.py'}",
        "db_path": str(db_path),
        "pdf_cache_dir": str(pdf_cache),
        "output_dir": str(output_dir),
        "log_path": str(log_path),
        "host": host,
        "port": port,
        "log_level": "info",
        "secret_key": os.urandom(32).hex(),
    }
    if admin_password_hash:
        config["admin_password_hash"] = admin_password_hash

    # Write to both config search locations
    from teredacta.config import config_search_paths
    paths = config_search_paths()
    config_file = paths[0]   # project-local
    user_config = paths[1]   # user-level

    with open(config_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    click.echo(f"\n  Config written to {config_file}")

    user_config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_file, user_config)
    click.echo(f"  Config copied to  {user_config}")

    # --- Step 6: Generate deployment files (optional) ---
    if system == "Linux" and mode == "server":
        if click.confirm("\n  Generate systemd service files?", default=True):
            _generate_systemd(config, unob_path)

    # --- Step 7: Initialize Unobfuscator DB if needed ---
    if not db_path.exists():
        click.echo("\n  Initializing Unobfuscator database...")
        _run_unob(unob_path, unob_bin, ["status"])

    # --- Step 8: Offer to start ---
    click.echo(f"\n  {'=' * 44}")
    click.echo("  Installation complete!\n")

    if click.confirm("  Start Unobfuscator daemon?", default=True):
        _run_unob(unob_path, unob_bin, ["start"])
        click.echo("  Unobfuscator daemon started.")

    if click.confirm("  Start TEREDACTA web server?", default=True):
        click.echo(f"\n  Starting TEREDACTA on http://{host}:{port}")
        click.echo("  Press Ctrl+C to stop.\n")
        from teredacta.app import create_app
        from teredacta.config import load_config
        import uvicorn
        cfg = load_config(str(config_file))
        app = create_app(cfg)
        uvicorn.run(app, host=cfg.host, port=cfg.port)
    else:
        click.echo(f"  To start later:  teredacta run")
        click.echo()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_unobfuscator() -> Path | None:
    """Search common locations for an existing Unobfuscator installation."""
    for candidate in _unob_search_paths():
        if (candidate / "unobfuscator.py").exists():
            return candidate
    return None


def _install_unobfuscator() -> Path | None:
    """Clone Unobfuscator from GitHub and install its dependencies."""
    default_dir = str(Path.cwd().parent / "Unobfuscator")
    install_dir = click.prompt("  Install directory", default=default_dir)
    install_path = Path(install_dir)

    if install_path.exists() and any(install_path.iterdir()):
        if not click.confirm(f"  {install_path} is not empty. Continue?", default=False):
            return None

    # Check for git
    if not shutil.which("git"):
        click.echo("  Error: git is required. Install git and try again.")
        return None

    # Try SSH first (works with deploy keys and SSH agents), fall back to HTTPS
    cloned = False
    for repo_url in [_UNOB_REPO_SSH, _UNOB_REPO_HTTPS]:
        click.echo(f"  Trying {repo_url}...")
        result = subprocess.run(
            ["git", "clone", repo_url, str(install_path)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            cloned = True
            break
        click.echo(f"  Failed ({result.stderr.strip().split(chr(10))[-1]})")
        # Clean up partial clone before retrying
        if install_path.exists():
            shutil.rmtree(install_path, ignore_errors=True)

    if not cloned:
        custom = click.prompt("  Enter a custom clone URL (or 'skip' to skip)", default="skip")
        if custom == "skip":
            return None
        result = subprocess.run(
            ["git", "clone", custom, str(install_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            click.echo(f"  Clone failed: {result.stderr.strip()}")
            return None

    _ensure_unob_deps(install_path)
    return install_path


def _ensure_unob_deps(unob_path: Path):
    """Create a venv and install Unobfuscator's requirements if needed."""
    venv_dir = unob_path / ".venv"
    req_file = unob_path / "requirements.txt"

    if not req_file.exists():
        return  # nothing to install

    pip = str(_venv_bin(venv_dir, "pip"))
    venv_exists = Path(pip).exists()

    if not venv_exists:
        click.echo("  Creating Unobfuscator virtualenv...")
        try:
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
            pip = str(_venv_bin(venv_dir, "pip"))
        except subprocess.CalledProcessError as e:
            click.echo(f"  Warning: venv creation failed: {e}")
            return

    # Always install/update requirements — pip is fast when everything is satisfied
    click.echo("  Installing Unobfuscator dependencies...")
    try:
        subprocess.run([pip, "install", "-q", "-r", str(req_file)], check=True)
        click.echo("  Dependencies installed.")
    except subprocess.CalledProcessError as e:
        click.echo(f"  Warning: dependency install failed: {e}")


def _venv_bin(venv_dir: Path, name: str) -> Path:
    """Return path to a binary inside a venv, platform-aware."""
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / name
    return venv_dir / "bin" / name


def _find_unob_python(unob_path: Path) -> str:
    """Return the best Python to run Unobfuscator with."""
    venv_python = _venv_bin(unob_path / ".venv", "python")
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _read_unob_config(unob_path: Path) -> dict:
    """Read Unobfuscator's config.yaml if it exists."""
    cfg_file = unob_path / "config.yaml"
    if cfg_file.exists():
        with open(cfg_file) as f:
            return yaml.safe_load(f) or {}
    return {}


def _resolve(base: Path, relative: str) -> Path:
    """Resolve a potentially relative path against a base directory."""
    p = Path(relative)
    if p.is_absolute():
        return p
    return (base / p).resolve()


def _run_unob(unob_path: Path, python_bin: str, args: list):
    """Run an Unobfuscator CLI command."""
    cmd = [python_bin, str(unob_path / "unobfuscator.py")] + args
    try:
        subprocess.run(cmd, cwd=str(unob_path), timeout=30)
    except subprocess.TimeoutExpired:
        pass
    except FileNotFoundError:
        click.echo(f"  Warning: could not run {cmd[0]}")


def _generate_systemd(config: dict, unob_path: Path):
    """Generate systemd user service files for both Unobfuscator and TEREDACTA."""
    service_dir = Path.home() / ".config" / "systemd" / "user"
    service_dir.mkdir(parents=True, exist_ok=True)
    user = os.getenv("USER", "root")
    unob_python = _find_unob_python(unob_path)

    # Unobfuscator service
    unob_service = service_dir / "unobfuscator.service"
    unob_service.write_text(
        f"[Unit]\nDescription=Unobfuscator Pipeline Daemon\n\n"
        f"[Service]\nType=simple\n"
        f"WorkingDirectory={unob_path}\n"
        f"ExecStart={unob_python} {unob_path / 'unobfuscator.py'} start -f\n"
        f"Restart=on-failure\n"
        f"RestartSec=10\n\n"
        f"[Install]\nWantedBy=default.target\n"
    )
    click.echo(f"  Wrote {unob_service}")

    # TEREDACTA service
    teredacta_service = service_dir / "teredacta.service"
    teredacta_bin = shutil.which("teredacta") or f"{sys.executable} -m teredacta"
    teredacta_service.write_text(
        f"[Unit]\nDescription=TEREDACTA Web Interface\n"
        f"After=unobfuscator.service\n\n"
        f"[Service]\nType=simple\n"
        f"ExecStart={teredacta_bin} run --host {config['host']} --port {config['port']}\n"
        f"Restart=on-failure\n"
        f"RestartSec=5\n\n"
        f"[Install]\nWantedBy=default.target\n"
    )
    click.echo(f"  Wrote {teredacta_service}")

    # Reload unit files and enable+start both services
    def _systemctl(*args):
        cmd = ["systemctl", "--user"] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            click.echo(f"  Warning: {' '.join(cmd)} failed: {result.stderr.strip()}")
        return result.returncode == 0

    click.echo("  Reloading systemd unit files...")
    _systemctl("daemon-reload")
    for svc in ("unobfuscator", "teredacta"):
        if _systemctl("enable", "--now", svc):
            click.echo(f"  Enabled and started {svc}.service")
        else:
            click.echo(f"  Could not auto-enable {svc}.service — run manually:")
            click.echo(f"    systemctl --user enable --now {svc}")

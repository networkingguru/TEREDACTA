import os
import platform
import subprocess
from pathlib import Path

import click
import yaml
from jinja2 import Environment, FileSystemLoader


def run_wizard():
    """Interactive installation wizard."""
    click.echo("\n=== TEREDACTA Installation Wizard ===\n")

    # 1. Detect OS
    system = platform.system()
    click.echo(f"Detected OS: {system}")

    # 2. Deployment mode
    mode = click.prompt(
        "Deployment mode",
        type=click.Choice(["local", "server"]),
        default="local",
    )
    host = "127.0.0.1" if mode == "local" else "0.0.0.0"

    # 3. Unobfuscator path
    unob_path = _find_or_install_unobfuscator()

    # 4. Data directory
    data_dir = click.prompt(
        "Data directory (for DB, PDFs, output)",
        default=str(Path(unob_path) / "data") if unob_path else str(Path.home() / "teredacta-data"),
    )
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    # 5. Port
    port = click.prompt("Port", default=8000, type=int)

    # 6. Admin password (server mode)
    admin_password_hash = None
    if mode == "server":
        password = click.prompt("Admin password", hide_input=True, confirmation_prompt=True)
        import bcrypt
        admin_password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    # 7. Deployment type
    deployment = click.prompt(
        "Deployment type",
        type=click.Choice(["bare-metal", "docker"]),
        default="bare-metal",
    )

    # Build config
    config = {
        "unobfuscator_path": str(unob_path) if unob_path else "",
        "unobfuscator_bin": f"python {Path(unob_path) / 'unobfuscator.py'}" if unob_path else "",
        "db_path": str(data_path / "unobfuscator.db"),
        "pdf_cache_dir": str(data_path / "pdf_cache"),
        "output_dir": str(data_path / "output"),
        "log_path": str(data_path / "unobfuscator.log"),
        "host": host,
        "port": port,
        "log_level": "info",
        "session_timeout_minutes": 60,
        "sse_poll_interval_seconds": 2,
        "subprocess_timeout_seconds": 60,
    }
    if admin_password_hash:
        config["admin_password_hash"] = admin_password_hash

    # 8. Write config
    config_dir = Path.home() / ".teredacta"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False)
    click.echo(f"\nConfig written to: {config_file}")

    # 9. Generate deployment files
    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))

    if deployment == "docker":
        _generate_docker(env, config, data_path)
    elif system == "Linux" and deployment == "bare-metal":
        if click.confirm("Generate systemd service file?", default=True):
            _generate_systemd(env, config)

    # Create data subdirectories
    (data_path / "pdf_cache").mkdir(exist_ok=True)
    (data_path / "output").mkdir(exist_ok=True)

    click.echo(f"\n{'='*40}")
    click.echo("Installation complete!")
    click.echo(f"\nTo start: teredacta run")
    if deployment == "docker":
        click.echo(f"Or: cd {data_path} && docker compose up -d")
    click.echo()


def _find_or_install_unobfuscator():
    """Find existing Unobfuscator or offer to install."""
    # Check common locations
    candidates = [
        Path.cwd() / "Unobfuscator",
        Path.home() / "Unobfuscator",
        Path.home() / "Scripts" / "Unobfuscator",
    ]
    for candidate in candidates:
        if (candidate / "unobfuscator.py").exists():
            click.echo(f"Found Unobfuscator at: {candidate}")
            if click.confirm("Use this installation?", default=True):
                return str(candidate)

    # Manual path
    manual = click.prompt("Path to Unobfuscator (or 'install' to install)", default="install")
    if manual != "install":
        path = Path(manual)
        if (path / "unobfuscator.py").exists():
            return str(path)
        click.echo(f"Warning: unobfuscator.py not found at {path}")
        return str(path)

    # Install
    install_dir = click.prompt("Install directory", default=str(Path.home() / "Unobfuscator"))
    install_path = Path(install_dir)

    click.echo("Installing Unobfuscator...")
    try:
        subprocess.run(
            ["git", "clone", "https://github.com/brianhill11/Unobfuscator.git", str(install_path)],
            check=True,
        )
        # Create venv and install deps
        subprocess.run(
            [os.sys.executable, "-m", "venv", str(install_path / ".venv")],
            check=True,
        )
        pip = str(install_path / ".venv" / "bin" / "pip")
        if platform.system() == "Windows":
            pip = str(install_path / ".venv" / "Scripts" / "pip")
        req_file = install_path / "requirements.txt"
        if req_file.exists():
            subprocess.run([pip, "install", "-r", str(req_file)], check=True)
        click.echo("Unobfuscator installed successfully!")
        return str(install_path)
    except FileNotFoundError:
        click.echo("git not found. Please install git and try again, or install Unobfuscator manually.")
        return None
    except subprocess.CalledProcessError as e:
        click.echo(f"Installation failed: {e}")
        return None


def _generate_docker(env, config, data_path):
    """Generate docker-compose.yml."""
    template = env.get_template("docker-compose.yml.j2")
    content = template.render(**config, data_dir=str(data_path))
    output_file = data_path / "docker-compose.yml"
    output_file.write_text(content)

    # Generate .env
    env_file = data_path / ".env"
    env_content = f"TEREDACTA_PORT={config['port']}\n"
    if config.get("admin_password_hash"):
        env_content += "# Password hash is in config.yaml\n"
    env_file.write_text(env_content)

    click.echo(f"Docker files written to: {data_path}")


def _generate_systemd(env, config):
    """Generate systemd service file."""
    template = env.get_template("systemd.service.j2")
    content = template.render(**config, user=os.getenv("USER", "root"))
    output_file = Path.home() / ".config" / "systemd" / "user" / "teredacta.service"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(content)
    click.echo(f"Systemd service written to: {output_file}")
    click.echo("Enable with: systemctl --user enable --now teredacta")

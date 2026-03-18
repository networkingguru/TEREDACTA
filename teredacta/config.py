from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os

import bcrypt
import yaml


@dataclass
class TeredactaConfig:
    unobfuscator_path: str = ""
    unobfuscator_bin: str = ""
    db_path: str = ""
    pdf_cache_dir: str = ""
    output_dir: str = ""
    log_path: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    admin_password_hash: Optional[str] = None
    log_level: str = "info"
    session_timeout_minutes: int = 60
    sse_poll_interval_seconds: int = 2
    subprocess_timeout_seconds: int = 60
    secret_key: str = field(default_factory=lambda: os.urandom(32).hex())

    @property
    def is_local_mode(self) -> bool:
        return self.host in ("127.0.0.1", "localhost", "::1")

    @property
    def admin_enabled(self) -> bool:
        if self.is_local_mode:
            return True
        return self.admin_password_hash is not None

    @property
    def admin_requires_login(self) -> bool:
        if self.is_local_mode and self.admin_password_hash is None:
            return False
        return True

    def check_password(self, password: str) -> bool:
        if self.admin_password_hash is None:
            return False
        return bcrypt.checkpw(
            password.encode("utf-8"),
            self.admin_password_hash.encode("utf-8"),
        )


def load_config(config_path: Optional[str] = None) -> TeredactaConfig:
    """Load config from YAML file, with env var overrides."""
    if config_path is None:
        # Search default locations
        candidates = [
            Path.cwd() / "teredacta.yaml",
            Path.home() / ".teredacta" / "config.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = str(candidate)
                break

    data = {}
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    # Build config from file data
    cfg = TeredactaConfig(**{
        k: v for k, v in data.items()
        if k in TeredactaConfig.__dataclass_fields__
    })

    # Env var override for password (plaintext -> bcrypt hash)
    env_password = os.environ.get("TEREDACTA_ADMIN_PASSWORD")
    if env_password:
        cfg.admin_password_hash = bcrypt.hashpw(
            env_password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")

    return cfg

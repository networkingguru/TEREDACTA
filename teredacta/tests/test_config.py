import os
import tempfile
from pathlib import Path

import pytest
import yaml

from teredacta.config import TeredactaConfig, load_config


class TestTeredactaConfig:
    def test_default_values(self):
        cfg = TeredactaConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8000
        assert cfg.admin_password_hash is None
        assert cfg.session_timeout_minutes == 60
        assert cfg.sse_poll_interval_seconds == 2
        assert cfg.subprocess_timeout_seconds == 60

    def test_is_local_mode(self):
        cfg = TeredactaConfig(host="127.0.0.1")
        assert cfg.is_local_mode is True
        cfg2 = TeredactaConfig(host="0.0.0.0")
        assert cfg2.is_local_mode is False

    def test_admin_enabled_local_no_password(self):
        cfg = TeredactaConfig(host="127.0.0.1", admin_password_hash=None)
        assert cfg.admin_enabled is True
        assert cfg.admin_requires_login is False

    def test_admin_disabled_server_no_password(self):
        cfg = TeredactaConfig(host="0.0.0.0", admin_password_hash=None)
        assert cfg.admin_enabled is False

    def test_admin_enabled_server_with_password(self):
        cfg = TeredactaConfig(host="0.0.0.0", admin_password_hash="$2b$12$hash")
        assert cfg.admin_enabled is True
        assert cfg.admin_requires_login is True


class TestLoadConfig:
    def test_load_from_yaml(self, tmp_path):
        config_data = {
            "unobfuscator_path": "/tmp/unob",
            "db_path": "/tmp/unob.db",
            "host": "0.0.0.0",
            "port": 9000,
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        cfg = load_config(str(config_file))
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9000

    def test_env_var_password_override(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"host": "0.0.0.0"}))
        monkeypatch.setenv("TEREDACTA_ADMIN_PASSWORD", "secret123")

        cfg = load_config(str(config_file))
        assert cfg.admin_password_hash is not None
        assert cfg.admin_password_hash.startswith("$2b$")

    def test_load_default_paths(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)  # avoid picking up real teredacta.yaml from cwd
        config_dir = tmp_path / ".teredacta"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"port": 7777}))

        cfg = load_config(None)
        assert cfg.port == 7777

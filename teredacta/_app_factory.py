"""Factory module for multi-worker Uvicorn.

When Uvicorn runs with workers > 1 it needs an import string pointing to an
app object. This module creates the app using config from environment
variables set by __main__.py.

The empty-string-to-None conversion on _TEREDACTA_CONFIG_PATH is intentional:
__main__.py stores `config_path or ""` (since env vars can't be None), and
we convert "" back to None here so load_config() uses its search-path logic.
"""
import os
from teredacta.config import load_config
from teredacta.app import create_app

_config_path = os.environ.get("_TEREDACTA_CONFIG_PATH") or None
_cfg = load_config(_config_path)

_host = os.environ.get("_TEREDACTA_HOST")
_port = os.environ.get("_TEREDACTA_PORT")
if _host:
    _cfg.host = _host
if _port:
    _cfg.port = int(_port)

app = create_app(_cfg)

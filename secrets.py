"""Resolve sensitive config values from environment variables."""

import os


def resolve_secret(cfg: dict, value_key: str, env_setting_key: str, default_env: str) -> str:
    """
    Return cfg[value_key] if set, else os.environ[cfg[env_setting_key] or default_env].
    Strips surrounding quotes from values (common when copying from .env files).
    """
    if not isinstance(cfg, dict):
        return ""

    direct = cfg.get(value_key)
    if isinstance(direct, str) and direct.strip():
        return _clean(direct)

    env_name = cfg.get(env_setting_key) or default_env
    if not env_name:
        return ""
    return _clean(os.getenv(env_name, ""))


def _clean(value: str) -> str:
    return value.strip().strip('"').strip("'")

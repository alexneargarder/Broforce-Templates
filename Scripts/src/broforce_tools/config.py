"""Configuration management for broforce-tools."""
import json
import os
from pathlib import Path
from typing import Optional

from .paths import get_config_dir, get_cache_dir, is_windows, ensure_dir


CONFIG_FILE_NAME = 'broforce-tools.json' if is_windows() else 'config.json'
CACHE_FILE_NAME = 'dependency_cache.json'


def get_config_file() -> Path:
    """Get path to config file."""
    return get_config_dir() / CONFIG_FILE_NAME


def get_cache_file() -> Path:
    """Get path to cache file."""
    return get_cache_dir() / CACHE_FILE_NAME


def load_config() -> dict:
    """Load configuration from config file.

    Returns dict with 'repos' key (list of repo names) and optional keys:
    - 'defaults': dict with 'namespace' and 'website_url'
    - 'ignore': dict mapping repo names to lists of ignored projects
    - 'repos_parent': path to parent directory containing repos
    - 'release_dir': path to central directory for release zip copies
    """
    config_file = get_config_file()
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {'repos': []}


def save_config(config: dict) -> bool:
    """Save configuration to config file."""
    try:
        ensure_dir(get_config_dir())
        with open(get_config_file(), 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        return True
    except OSError:
        return False


def get_configured_repos() -> list[str]:
    """Get list of configured repos."""
    config = load_config()
    return config.get('repos', [])


def get_ignored_projects(repo_name: str) -> list[str]:
    """Get list of ignored project names for a repo."""
    config = load_config()
    ignore_config = config.get('ignore', {})
    return ignore_config.get(repo_name, [])


def get_defaults() -> dict:
    """Get default values for namespace and website_url."""
    config = load_config()
    return config.get('defaults', {})


def get_release_dir() -> Optional[str]:
    """Get the central release directory path, if configured."""
    config = load_config()
    release_dir = config.get('release_dir')
    if release_dir:
        return str(Path(release_dir).expanduser())
    return None

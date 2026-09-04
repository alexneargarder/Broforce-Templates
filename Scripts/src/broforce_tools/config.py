"""Configuration management for broforce-tools."""
import json
import shutil
from pathlib import Path
from typing import Optional

from .paths import get_config_dir, get_cache_dir, is_windows, ensure_dir


CONFIG_FILE_NAME = 'config.json'
NIX_CONFIG_FILE_NAME = 'config.nix.json'
CACHE_FILE_NAME = 'dependency_cache.json'


def get_config_file() -> Path:
    """Get path to user config file (imperative, written by bt config commands)."""
    return get_config_dir() / CONFIG_FILE_NAME


def get_nix_config_file() -> Path:
    """Get path to Nix-managed config file (declarative, written by NixOS activation)."""
    return get_config_dir() / NIX_CONFIG_FILE_NAME


def get_cache_file() -> Path:
    """Get path to cache file."""
    return get_cache_dir() / CACHE_FILE_NAME


def _migrate_old_windows_config() -> None:
    """One-time migration: copy config from old script-relative location to %APPDATA%."""
    if not is_windows():
        return
    from .paths import _get_script_dir
    old_file = _get_script_dir() / 'broforce-tools.json'
    if not old_file.exists():
        old_file = _get_script_dir() / 'config.json'
        if not old_file.exists():
            return
    new_file = get_config_file()
    if new_file.exists():
        return
    try:
        ensure_dir(new_file.parent)
        shutil.copy2(str(old_file), str(new_file))
    except OSError:
        pass


def _load_json_file(path: Path) -> Optional[dict]:
    """Load a JSON file, returning None on any error."""
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _merge_configs(base: dict, override: dict) -> dict:
    """Merge two config dicts. Override values take precedence.

    For nested dicts (defaults, ignore), merges at the nested level.
    For all other keys, override replaces base entirely.
    """
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_configs(merged[key], value)
        else:
            merged[key] = value
    return merged


NIX_OPTION_FOR_KEY = {
    'repos_parent': 'programs.broforce-tools.reposParent',
    'release_dir': 'programs.broforce-tools.releaseDir',
    'repos': 'programs.broforce-tools.repos',
    'ignore': 'programs.broforce-tools.ignore',
    'defaults.namespace': 'programs.broforce-tools.defaults.namespace',
    'defaults.website_url': 'programs.broforce-tools.defaults.websiteUrl',
}


def load_user_config() -> dict:
    """Load the imperative config written by 'bt config' commands."""
    _migrate_old_windows_config()
    return _load_json_file(get_config_file()) or {}


def load_nix_config() -> dict:
    """Load the declarative config written by the NixOS activation script."""
    return _load_json_file(get_nix_config_file()) or {}


def nix_managed_option(key: str) -> Optional[str]:
    """Return the NixOS option that owns a config key, or None if it is free to set."""
    option = NIX_OPTION_FOR_KEY.get(key)
    if not option:
        return None

    value = load_nix_config()
    for part in key.split('.'):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return option


def load_config() -> dict:
    """Load configuration, merging Nix-managed and user configs.

    On NixOS, config comes from two layers:
    - config.nix.json: Declarative, written by NixOS activation script
    - config.json: Imperative, written by 'bt config' commands

    Nix config (config.nix.json) takes precedence over user config.

    Returns dict with 'repos' key (list of repo names) and optional keys:
    - 'defaults': dict with 'namespace' and 'website_url'
    - 'ignore': dict mapping repo names to lists of ignored projects
    - 'repos_parent': path to parent directory containing repos
    - 'release_dir': path to central directory for release zip copies
    """
    user_config = load_user_config()
    nix_config = load_nix_config()

    if nix_config and user_config:
        return _merge_configs(user_config, nix_config)
    elif user_config:
        return user_config
    elif nix_config:
        return nix_config
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

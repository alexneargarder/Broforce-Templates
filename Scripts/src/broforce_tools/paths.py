"""Cross-platform path handling for broforce-tools.

On Linux: Uses XDG directories (~/.config/broforce-tools/, ~/.cache/broforce-tools/)
On Windows: Uses script directory for config (existing behavior), temp for cache
"""
import os
import sys
import tempfile
from pathlib import Path


class TemplatesDirNotFound(Exception):
    """Raised when the Broforce-Templates directory cannot be located."""
    pass


def is_windows() -> bool:
    return sys.platform == 'win32'


def is_linux() -> bool:
    return sys.platform.startswith('linux')


def get_config_dir() -> Path:
    """Get config directory.

    Checks BROFORCE_CONFIG_DIR env var first (for testing).
    Linux: XDG_CONFIG_HOME/broforce-tools or ~/.config/broforce-tools
    Windows: Same directory as the script (existing behavior)
    """
    env_path = os.environ.get('BROFORCE_CONFIG_DIR')
    if env_path:
        return Path(env_path).expanduser()

    if is_windows():
        return _get_script_dir()
    else:
        xdg_config = os.environ.get('XDG_CONFIG_HOME')
        if xdg_config:
            return Path(xdg_config) / 'broforce-tools'
        return Path.home() / '.config' / 'broforce-tools'


def get_cache_dir() -> Path:
    """Get cache directory.

    Linux: XDG_CACHE_HOME/broforce-tools or ~/.cache/broforce-tools
    Windows: System temp directory / broforce-tools
    """
    if is_windows():
        return Path(tempfile.gettempdir()) / 'broforce-tools'
    else:
        xdg_cache = os.environ.get('XDG_CACHE_HOME')
        if xdg_cache:
            return Path(xdg_cache) / 'broforce-tools'
        return Path.home() / '.cache' / 'broforce-tools'


def get_templates_dir() -> Path:
    """Get templates directory containing 'Mod Template/', 'Bro Template/', etc.

    Lookup order:
    1. BROFORCE_TEMPLATES_DIR env var (set by Nix wrapper)
    2. Script-relative path (works for in-repo execution)
    3. Config file 'templates_dir' key
    4. repos_parent / 'Broforce-Templates' (derived from env var or config)

    Raises TemplatesDirNotFound if none found.
    """
    env_path = os.environ.get('BROFORCE_TEMPLATES_DIR')
    if env_path:
        return Path(env_path)

    script_relative = _get_script_dir().parent
    if (script_relative / 'Mod Template').is_dir():
        return script_relative

    from .config import load_config
    config = load_config()
    if 'templates_dir' in config:
        config_path = Path(config['templates_dir']).expanduser()
        if config_path.is_dir():
            return config_path

    # Derive from repos_parent if available (covers NixOS module config + env var)
    repos_parent = os.environ.get('BROFORCE_REPOS_PARENT')
    if not repos_parent:
        repos_parent = config.get('repos_parent')
    if repos_parent:
        candidate = Path(repos_parent).expanduser() / 'Broforce-Templates'
        if (candidate / 'Mod Template').is_dir():
            return candidate

    raise TemplatesDirNotFound(
        "Could not find Broforce-Templates directory. "
        "Set BROFORCE_TEMPLATES_DIR or configure 'repos_parent' in config."
    )


def get_repos_parent() -> Path:
    """Get parent directory containing all repos.

    Checks BROFORCE_REPOS_PARENT env var first.
    Then checks config file for 'repos_parent' setting.
    Falls back to parent of templates directory (may raise TemplatesDirNotFound).
    """
    env_path = os.environ.get('BROFORCE_REPOS_PARENT')
    if env_path:
        return Path(env_path).expanduser()

    from .config import load_config
    config = load_config()
    if 'repos_parent' in config:
        return Path(config['repos_parent']).expanduser()

    # May raise TemplatesDirNotFound for pipx installs without config
    return get_templates_dir().parent


def _get_script_dir() -> Path:
    """Get the directory containing this script/package.

    Used for Windows config location and as fallback for templates.
    """
    return Path(__file__).parent.parent.parent


def ensure_dir(path: Path) -> None:
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)

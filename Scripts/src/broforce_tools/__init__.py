"""Broforce modding tools for creating mods and packaging for Thunderstore."""


def _resolve_version() -> str:
    try:
        from importlib.metadata import version as _pkg_version
        return _pkg_version("broforce-tools")
    except Exception:
        pass
    try:
        import tomllib
        from pathlib import Path
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with open(pyproject, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except Exception:
        return "unknown"


__version__ = _resolve_version()

from .cli import run as main

__all__ = ['main', '__version__']

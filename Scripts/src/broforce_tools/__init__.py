"""Broforce modding tools for creating mods and packaging for Thunderstore."""

try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("broforce-tools")
except Exception:
    __version__ = "1.0.0"

from .cli import run as main

__all__ = ['main', '__version__']

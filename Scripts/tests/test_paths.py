"""Tests for paths module - template and repo path resolution."""
import os
from pathlib import Path

import pytest

from broforce_tools.paths import (
    TemplatesDirNotFound,
    get_cache_dir,
    get_config_dir,
    get_repos_parent,
    get_templates_dir,
)


class TestGetTemplatesDir:
    def test_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BROFORCE_TEMPLATES_DIR", str(tmp_path))
        assert get_templates_dir() == tmp_path

    def test_config_fallback(self, tmp_path, monkeypatch, isolated_config):
        monkeypatch.delenv("BROFORCE_TEMPLATES_DIR", raising=False)
        # Patch _get_script_dir so the script-relative check fails
        monkeypatch.setattr("broforce_tools.paths._get_script_dir", lambda: tmp_path / "fake")
        templates = tmp_path / "templates"
        (templates / "Mod Template").mkdir(parents=True)
        config_file = isolated_config / "config.json"
        config_file.write_text(f'{{"templates_dir": "{templates}"}}')
        result = get_templates_dir()
        assert result == templates

    def test_raises_when_not_found(self, tmp_path, monkeypatch, isolated_config):
        monkeypatch.delenv("BROFORCE_TEMPLATES_DIR", raising=False)
        monkeypatch.setattr("broforce_tools.paths._get_script_dir", lambda: tmp_path / "fake")
        with pytest.raises(TemplatesDirNotFound):
            get_templates_dir()


class TestGetReposParent:
    def test_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BROFORCE_REPOS_PARENT", str(tmp_path))
        assert get_repos_parent() == tmp_path

    def test_config_fallback(self, tmp_path, monkeypatch, isolated_config):
        monkeypatch.delenv("BROFORCE_REPOS_PARENT", raising=False)
        monkeypatch.delenv("BROFORCE_TEMPLATES_DIR", raising=False)
        config_file = isolated_config / "config.json"
        config_file.write_text(f'{{"repos_parent": "{tmp_path}"}}')
        assert get_repos_parent() == tmp_path

    def test_raises_when_templates_not_found(self, tmp_path, monkeypatch, isolated_config):
        monkeypatch.delenv("BROFORCE_REPOS_PARENT", raising=False)
        monkeypatch.delenv("BROFORCE_TEMPLATES_DIR", raising=False)
        monkeypatch.setattr("broforce_tools.paths._get_script_dir", lambda: tmp_path / "fake")
        with pytest.raises(TemplatesDirNotFound):
            get_repos_parent()


class TestGetConfigDir:
    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BROFORCE_CONFIG_DIR", str(tmp_path))
        assert get_config_dir() == tmp_path

    def test_linux_xdg(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BROFORCE_CONFIG_DIR", raising=False)
        monkeypatch.setattr("broforce_tools.paths.is_windows", lambda: False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert get_config_dir() == tmp_path / "broforce-tools"

    def test_linux_default(self, monkeypatch):
        monkeypatch.delenv("BROFORCE_CONFIG_DIR", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setattr("broforce_tools.paths.is_windows", lambda: False)
        result = get_config_dir()
        assert str(result).endswith(".config/broforce-tools")


class TestGetCacheDir:
    def test_linux_xdg(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broforce_tools.paths.is_windows", lambda: False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert get_cache_dir() == tmp_path / "broforce-tools"

    def test_linux_default(self, monkeypatch):
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.setattr("broforce_tools.paths.is_windows", lambda: False)
        result = get_cache_dir()
        assert str(result).endswith(".cache/broforce-tools")

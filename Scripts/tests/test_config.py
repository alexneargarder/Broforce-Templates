"""Tests for config module - loading and saving configuration."""
import json

import pytest

from broforce_tools.config import (
    load_config,
    save_config,
    get_configured_repos,
    get_defaults,
    get_ignored_projects,
    get_release_dir,
)


class TestLoadConfig:
    def test_valid_config(self, isolated_config):
        config = {"repos": ["Repo1", "Repo2"], "defaults": {"namespace": "Test"}}
        (isolated_config / "config.json").write_text(json.dumps(config))
        result = load_config()
        assert result["repos"] == ["Repo1", "Repo2"]
        assert result["defaults"]["namespace"] == "Test"

    def test_missing_file(self, isolated_config):
        result = load_config()
        assert result == {"repos": []}

    def test_invalid_json(self, isolated_config):
        (isolated_config / "config.json").write_text("not json{{{")
        result = load_config()
        assert result == {"repos": []}

    def test_empty_file(self, isolated_config):
        (isolated_config / "config.json").write_text("")
        result = load_config()
        assert result == {"repos": []}


class TestSaveConfig:
    def test_round_trip(self, isolated_config):
        config = {"repos": ["A", "B"], "defaults": {"namespace": "X"}}
        assert save_config(config)
        result = load_config()
        assert result == config

    def test_creates_directory(self, tmp_path, monkeypatch):
        new_dir = tmp_path / "subdir" / "config"
        monkeypatch.setenv("BROFORCE_CONFIG_DIR", str(new_dir))
        assert save_config({"repos": ["Test"]})
        assert (new_dir / "config.json").exists()


class TestGetConfiguredRepos:
    def test_returns_repos(self, isolated_config):
        (isolated_config / "config.json").write_text('{"repos": ["A", "B"]}')
        assert get_configured_repos() == ["A", "B"]

    def test_empty_when_no_config(self, isolated_config):
        assert get_configured_repos() == []


class TestGetDefaults:
    def test_returns_defaults(self, isolated_config):
        config = {"repos": [], "defaults": {"namespace": "Test", "website_url": "http://x"}}
        (isolated_config / "config.json").write_text(json.dumps(config))
        defaults = get_defaults()
        assert defaults["namespace"] == "Test"

    def test_empty_when_no_defaults(self, isolated_config):
        assert get_defaults() == {}


class TestGetIgnoredProjects:
    def test_returns_ignored(self, isolated_config):
        config = {"repos": [], "ignore": {"MyRepo": ["IgnoredMod", "OtherMod"]}}
        (isolated_config / "config.json").write_text(json.dumps(config))
        assert get_ignored_projects("MyRepo") == ["IgnoredMod", "OtherMod"]

    def test_repo_not_in_ignore(self, isolated_config):
        config = {"repos": [], "ignore": {"OtherRepo": ["Foo"]}}
        (isolated_config / "config.json").write_text(json.dumps(config))
        assert get_ignored_projects("MyRepo") == []

    def test_no_ignore_config(self, isolated_config):
        assert get_ignored_projects("MyRepo") == []


class TestGetReleaseDir:
    def test_returns_path(self, isolated_config):
        config = {"repos": [], "release_dir": "/tmp/releases"}
        (isolated_config / "config.json").write_text(json.dumps(config))
        assert get_release_dir() == "/tmp/releases"

    def test_expands_tilde(self, isolated_config):
        config = {"repos": [], "release_dir": "~/releases"}
        (isolated_config / "config.json").write_text(json.dumps(config))
        result = get_release_dir()
        assert "~" not in result
        assert result.endswith("/releases")

    def test_returns_none_when_not_set(self, isolated_config):
        assert get_release_dir() is None

"""Tests for config module - loading and saving configuration."""
import json

import pytest
from typer.testing import CliRunner

from broforce_tools.cli import app
from broforce_tools.config import (
    get_config_file,
    load_config,
    save_config,
    get_configured_repos,
    get_defaults,
    get_ignored_projects,
    get_release_dir,
)

runner = CliRunner()


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


class TestMigration:
    def test_migration_copies_old_windows_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broforce_tools.config.is_windows", lambda: True)
        # Set up old config at script-relative location
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        old_config = old_dir / "broforce-tools.json"
        old_config.write_text('{"repos": ["OldRepo"]}')
        monkeypatch.setattr("broforce_tools.paths._get_script_dir", lambda: old_dir)
        # Set up new config location
        new_dir = tmp_path / "new"
        monkeypatch.setenv("BROFORCE_CONFIG_DIR", str(new_dir))
        config = load_config()
        assert config["repos"] == ["OldRepo"]
        assert (new_dir / "config.json").exists()

    def test_migration_skips_if_new_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broforce_tools.config.is_windows", lambda: True)
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        (old_dir / "broforce-tools.json").write_text('{"repos": ["OldRepo"]}')
        monkeypatch.setattr("broforce_tools.paths._get_script_dir", lambda: old_dir)
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        (new_dir / "config.json").write_text('{"repos": ["NewRepo"]}')
        monkeypatch.setenv("BROFORCE_CONFIG_DIR", str(new_dir))
        config = load_config()
        assert config["repos"] == ["NewRepo"]

    def test_migration_skips_on_linux(self, tmp_path, monkeypatch):
        monkeypatch.setattr("broforce_tools.config.is_windows", lambda: False)
        monkeypatch.setenv("BROFORCE_CONFIG_DIR", str(tmp_path))
        config = load_config()
        assert config == {"repos": []}


class TestConfigMerge:
    def test_nix_only(self, isolated_config):
        nix = {"repos": ["NixRepo"], "repos_parent": "~/repos"}
        (isolated_config / "config.nix.json").write_text(json.dumps(nix))
        config = load_config()
        assert config["repos"] == ["NixRepo"]
        assert config["repos_parent"] == "~/repos"

    def test_user_only(self, isolated_config):
        user = {"repos": ["UserRepo"]}
        (isolated_config / "config.json").write_text(json.dumps(user))
        config = load_config()
        assert config["repos"] == ["UserRepo"]

    def test_user_overrides_nix(self, isolated_config):
        nix = {"repos": ["NixRepo"], "repos_parent": "~/nix-repos"}
        user = {"repos": ["UserRepo"]}
        (isolated_config / "config.nix.json").write_text(json.dumps(nix))
        (isolated_config / "config.json").write_text(json.dumps(user))
        config = load_config()
        assert config["repos"] == ["UserRepo"]
        assert config["repos_parent"] == "~/nix-repos"

    def test_nested_dict_merge(self, isolated_config):
        nix = {"repos": [], "defaults": {"namespace": "NixUser", "website_url": "https://nix"}}
        user = {"repos": [], "defaults": {"namespace": "OverriddenUser"}}
        (isolated_config / "config.nix.json").write_text(json.dumps(nix))
        (isolated_config / "config.json").write_text(json.dumps(user))
        config = load_config()
        assert config["defaults"]["namespace"] == "OverriddenUser"
        assert config["defaults"]["website_url"] == "https://nix"

    def test_neither_exists(self, isolated_config):
        config = load_config()
        assert config == {"repos": []}


class TestConfigCommands:
    def test_config_path(self, isolated_config):
        result = runner.invoke(app, ["config", "path"])
        assert result.exit_code == 0
        assert str(isolated_config) in result.output

    def test_config_show_no_config(self, isolated_config):
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "does not exist" in result.output

    def test_config_show_with_config(self, isolated_config):
        (isolated_config / "config.json").write_text('{"repos": ["TestRepo"]}')
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "TestRepo" in result.output

    def test_config_set_simple(self, isolated_config):
        result = runner.invoke(app, ["config", "set", "repos_parent", "/tmp/repos"])
        assert result.exit_code == 0
        assert "repos_parent" in result.output
        config = load_config()
        assert config["repos_parent"] == "/tmp/repos"

    def test_config_set_dotted(self, isolated_config):
        result = runner.invoke(app, ["config", "set", "defaults.namespace", "TestAuthor"])
        assert result.exit_code == 0
        config = load_config()
        assert config["defaults"]["namespace"] == "TestAuthor"

    def test_config_set_clear(self, isolated_config):
        (isolated_config / "config.json").write_text('{"repos": [], "repos_parent": "/old"}')
        result = runner.invoke(app, ["config", "set", "repos_parent", ""])
        assert result.exit_code == 0
        assert "Cleared" in result.output
        config = load_config()
        assert "repos_parent" not in config

    def test_config_set_invalid_key(self, isolated_config):
        result = runner.invoke(app, ["config", "set", "invalid_key", "value"])
        assert result.exit_code == 1
        assert "Unknown config key" in result.output

    def test_config_add_repo(self, isolated_config):
        result = runner.invoke(app, ["config", "add-repo", "MyRepo"])
        assert result.exit_code == 0
        assert "Added" in result.output
        config = load_config()
        assert "MyRepo" in config["repos"]

    def test_config_add_repo_duplicate(self, isolated_config):
        (isolated_config / "config.json").write_text('{"repos": ["MyRepo"]}')
        result = runner.invoke(app, ["config", "add-repo", "MyRepo"])
        assert result.exit_code == 0
        assert "already" in result.output

    def test_config_remove_repo(self, isolated_config):
        (isolated_config / "config.json").write_text('{"repos": ["MyRepo", "OtherRepo"]}')
        result = runner.invoke(app, ["config", "remove-repo", "MyRepo"])
        assert result.exit_code == 0
        assert "Removed" in result.output
        config = load_config()
        assert "MyRepo" not in config["repos"]
        assert "OtherRepo" in config["repos"]

    def test_config_remove_repo_not_found(self, isolated_config):
        (isolated_config / "config.json").write_text('{"repos": []}')
        result = runner.invoke(app, ["config", "remove-repo", "Nope"])
        assert result.exit_code == 0
        assert "not in" in result.output

"""Tests for config module - loading and saving configuration."""
import json

import pytest
from typer.testing import CliRunner

from broforce_tools.cli import app
from broforce_tools.config import (
    get_config_file,
    load_config,
    load_nix_config,
    load_user_config,
    nix_managed_option,
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

    def test_nix_overrides_user(self, isolated_config):
        nix = {"repos": ["NixRepo"], "repos_parent": "~/nix-repos"}
        user = {"repos": ["UserRepo"], "templates_dir": "/user/templates"}
        (isolated_config / "config.nix.json").write_text(json.dumps(nix))
        (isolated_config / "config.json").write_text(json.dumps(user))
        config = load_config()
        assert config["repos"] == ["NixRepo"]
        assert config["repos_parent"] == "~/nix-repos"
        assert config["templates_dir"] == "/user/templates"

    def test_nested_dict_merge(self, isolated_config):
        nix = {"repos": [], "defaults": {"namespace": "NixUser"}}
        user = {"repos": [], "defaults": {"namespace": "UserName", "website_url": "https://user"}}
        (isolated_config / "config.nix.json").write_text(json.dumps(nix))
        (isolated_config / "config.json").write_text(json.dumps(user))
        config = load_config()
        assert config["defaults"]["namespace"] == "NixUser"
        assert config["defaults"]["website_url"] == "https://user"

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


def _write_nix_config(config_dir, data):
    (config_dir / "config.nix.json").write_text(json.dumps(data))


class TestNixManagedOption:
    def test_key_present_in_nix_config(self, isolated_config):
        _write_nix_config(isolated_config, {"repos_parent": "~/nix-repos"})
        assert nix_managed_option("repos_parent") == "programs.broforce-tools.reposParent"

    def test_key_absent_from_nix_config(self, isolated_config):
        _write_nix_config(isolated_config, {"repos": ["NixRepo"]})
        assert nix_managed_option("repos_parent") is None

    def test_dotted_key(self, isolated_config):
        _write_nix_config(isolated_config, {"defaults": {"website_url": "https://nix"}})
        assert nix_managed_option("defaults.website_url") == "programs.broforce-tools.defaults.websiteUrl"
        assert nix_managed_option("defaults.namespace") is None

    def test_key_without_nix_option(self, isolated_config):
        _write_nix_config(isolated_config, {"templates_dir": "/nix/templates"})
        assert nix_managed_option("templates_dir") is None

    def test_no_nix_config(self, isolated_config):
        assert nix_managed_option("repos_parent") is None


class TestNixManagedRefusal:
    def test_set_refuses_managed_key(self, isolated_config):
        _write_nix_config(isolated_config, {"repos_parent": "~/nix-repos"})
        result = runner.invoke(app, ["config", "set", "repos_parent", "/tmp/repos"])
        assert result.exit_code == 1
        assert "programs.broforce-tools.reposParent" in result.output
        assert not (isolated_config / "config.json").exists()

    def test_set_refuses_managed_dotted_key(self, isolated_config):
        _write_nix_config(isolated_config, {"defaults": {"namespace": "NixUser"}})
        result = runner.invoke(app, ["config", "set", "defaults.namespace", "Someone"])
        assert result.exit_code == 1
        assert "programs.broforce-tools.defaults.namespace" in result.output

    def test_add_repo_refuses_managed_repos(self, isolated_config):
        _write_nix_config(isolated_config, {"repos": ["NixRepo"]})
        result = runner.invoke(app, ["config", "add-repo", "MyRepo"])
        assert result.exit_code == 1
        assert "programs.broforce-tools.repos" in result.output

    def test_remove_repo_refuses_managed_repos(self, isolated_config):
        _write_nix_config(isolated_config, {"repos": ["NixRepo"]})
        result = runner.invoke(app, ["config", "remove-repo", "NixRepo"])
        assert result.exit_code == 1
        assert "programs.broforce-tools.repos" in result.output

    def test_set_unmanaged_key_writes_only_user_keys(self, isolated_config):
        _write_nix_config(isolated_config, {
            "repos": ["NixRepo"],
            "repos_parent": "~/nix-repos",
            "defaults": {"namespace": "NixUser"},
        })
        result = runner.invoke(app, ["config", "set", "templates_dir", "/tmp/templates"])
        assert result.exit_code == 0
        assert load_user_config() == {"templates_dir": "/tmp/templates"}
        assert load_nix_config()["repos"] == ["NixRepo"]
        assert load_config()["repos_parent"] == "~/nix-repos"

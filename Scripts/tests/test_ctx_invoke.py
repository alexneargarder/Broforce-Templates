"""Tests for ctx.invoke of changelog subcommands from main menu.

When changelog commands are invoked via ctx.invoke() without arguments,
typer's ArgumentInfo objects leak through as parameter values instead of None.
This causes TypeError when the value is used in os.path.join().
"""
import json

import click.exceptions
import pytest

from broforce_tools.cli import changelog_show, changelog_edit, changelog_add


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Set up isolated config and repos for CLI testing."""
    repos_parent = tmp_path / "repos"
    repo_dir = repos_parent / "TestRepo"
    project_dir = repo_dir / "TestMod"
    modcontent = project_dir / "_ModContent"
    modcontent.mkdir(parents=True)
    (modcontent / "Info.json").write_text(json.dumps({
        "Id": "TestMod", "Version": "1.0.0"
    }))
    (project_dir / "TestMod.csproj").write_text("<Project/>")

    releases = repo_dir / "Release"
    releases.mkdir(parents=True)
    (releases / "manifest.json").write_text(json.dumps({
        "name": "TestMod", "author": "Test", "version_number": "1.0.0",
        "website_url": "", "description": "Test",
        "dependencies": ["UMM-UMM-1.0.0"]
    }))
    (releases / "Changelog.md").write_text("## v1.0.0 (unreleased)\n- Initial\n")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({
        "repos": [str(repo_dir)]
    }))

    monkeypatch.setenv("BROFORCE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("BROFORCE_REPOS_PARENT", str(repos_parent))
    monkeypatch.setenv("BROFORCE_TEMPLATES_DIR", str(repo_dir))
    monkeypatch.setenv("EDITOR", "true")


class TestChangelogCtxInvoke:
    """Changelog commands called directly (simulating ctx.invoke) must not crash
    when project_name defaults to its ArgumentInfo instead of None."""

    def test_changelog_show_no_project_name(self, cli_env):
        """Calling changelog_show() with no args should not TypeError."""
        try:
            changelog_show()
        except (SystemExit, click.exceptions.Exit):
            pass
        except TypeError as e:
            if "ArgumentInfo" in str(e) or "join()" in str(e):
                pytest.fail(f"changelog_show raised TypeError with ArgumentInfo: {e}")

    def test_changelog_edit_no_project_name(self, cli_env):
        """Calling changelog_edit() with no args should not TypeError."""
        try:
            changelog_edit()
        except (SystemExit, click.exceptions.Exit):
            pass
        except TypeError as e:
            if "ArgumentInfo" in str(e) or "join()" in str(e):
                pytest.fail(f"changelog_edit raised TypeError with ArgumentInfo: {e}")

    def test_changelog_add_no_args(self, cli_env):
        """Calling changelog_add() with no args should not TypeError."""
        try:
            changelog_add()
        except (SystemExit, click.exceptions.Exit):
            pass  # Expected — no message provided

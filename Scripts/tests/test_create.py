"""Tests for the create command - project creation from templates."""
import json
import os

import pytest
from typer.testing import CliRunner

from broforce_tools.cli import app

runner = CliRunner()


@pytest.fixture
def create_env(tmp_path, monkeypatch):
    """Set up an environment for create command testing."""
    repos_parent = tmp_path / "repos"
    repo = repos_parent / "TestRepo"
    repo.mkdir(parents=True)

    # Point to the real Broforce-Templates for templates
    # __file__ is Scripts/tests/test_create.py, go up 2 to Scripts/, up 1 more to Broforce-Templates/
    templates_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    monkeypatch.setenv("BROFORCE_TEMPLATES_DIR", templates_dir)
    monkeypatch.setenv("BROFORCE_REPOS_PARENT", str(repos_parent))

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({
        "repos": ["TestRepo"],
        "repos_parent": str(repos_parent),
    }))
    monkeypatch.setenv("BROFORCE_CONFIG_DIR", str(config_dir))

    return {
        "repos_parent": repos_parent,
        "repo": repo,
        "templates_dir": templates_dir,
    }


class TestCreateMod:
    def test_creates_mod_project(self, create_env):
        result = runner.invoke(app, [
            "create", "-t", "mod", "-n", "TestMod", "-a", "TestAuthor",
            "-o", "TestRepo", "-y", "--no-thunderstore",
        ])
        assert result.exit_code == 0
        project_dir = create_env["repo"] / "TestMod"
        assert project_dir.is_dir()
        # Check renamed files exist
        assert (project_dir / "TestMod" / "TestMod.csproj").exists()
        assert (project_dir / "TestMod" / "Main.cs").exists()

    def test_creates_changelog(self, create_env):
        runner.invoke(app, [
            "create", "-t", "mod", "-n", "TestMod", "-a", "TestAuthor",
            "-o", "TestRepo", "-y", "--no-thunderstore",
        ])
        changelog = create_env["repo"] / "Releases" / "TestMod" / "Changelog.md"
        assert changelog.exists()
        assert "(unreleased)" in changelog.read_text()

    def test_csproj_has_correct_name(self, create_env):
        runner.invoke(app, [
            "create", "-t", "mod", "-n", "My Cool Mod", "-a", "TestAuthor",
            "-o", "TestRepo", "-y", "--no-thunderstore",
        ])
        csproj = create_env["repo"] / "My Cool Mod" / "My Cool Mod" / "My Cool Mod.csproj"
        assert csproj.exists()
        content = csproj.read_text()
        assert "My Cool Mod" in content
        assert "Mod Template" not in content

    def test_copies_build_targets(self, create_env):
        runner.invoke(app, [
            "create", "-t", "mod", "-n", "TestMod", "-a", "TestAuthor",
            "-o", "TestRepo", "-y", "--no-thunderstore",
        ])
        targets = create_env["repo"] / "Scripts" / "BroforceModBuild.targets"
        assert targets.exists()

    def test_duplicate_name_fails(self, create_env):
        runner.invoke(app, [
            "create", "-t", "mod", "-n", "TestMod", "-a", "TestAuthor",
            "-o", "TestRepo", "-y", "--no-thunderstore",
        ])
        result = runner.invoke(app, [
            "create", "-t", "mod", "-n", "TestMod", "-a", "TestAuthor",
            "-o", "TestRepo", "-y", "--no-thunderstore",
        ])
        assert result.exit_code == 1

    def test_invalid_type_fails(self, create_env):
        result = runner.invoke(app, [
            "create", "-t", "invalid", "-n", "TestMod", "-a", "TestAuthor",
            "-o", "TestRepo", "-y", "--no-thunderstore",
        ])
        assert result.exit_code == 1


class TestCreateWithRocketLib:
    def test_rocketlib_flag_adds_reference(self, create_env):
        runner.invoke(app, [
            "create", "-t", "mod", "-n", "RocketMod", "-a", "TestAuthor",
            "-o", "TestRepo", "-y", "--no-thunderstore", "--with-rocketlib",
        ])
        csproj = create_env["repo"] / "RocketMod" / "RocketMod" / "RocketMod.csproj"
        assert csproj.exists()
        content = csproj.read_text()
        assert "RocketLib" in content
        assert "$(RocketLibPath)" in content

    def test_no_rocketlib_by_default(self, create_env):
        runner.invoke(app, [
            "create", "-t", "mod", "-n", "PlainMod", "-a", "TestAuthor",
            "-o", "TestRepo", "-y", "--no-thunderstore",
        ])
        csproj = create_env["repo"] / "PlainMod" / "PlainMod" / "PlainMod.csproj"
        content = csproj.read_text()
        assert "RocketLib" not in content

    def test_rocketlib_flag_ignored_for_wardrobe(self, create_env):
        result = runner.invoke(app, [
            "create", "-t", "wardrobe", "-n", "TestWardrobe", "-a", "TestAuthor",
            "-o", "TestRepo", "-y", "--no-thunderstore", "--with-rocketlib",
        ])
        assert result.exit_code == 0
        # Wardrobes don't have code, so no csproj to check


class TestCreateBro:
    def test_creates_bro_project(self, create_env):
        result = runner.invoke(app, [
            "create", "-t", "bro", "-n", "TestBro", "-a", "TestAuthor",
            "-o", "TestRepo", "-y", "--no-thunderstore",
        ])
        assert result.exit_code == 0
        project_dir = create_env["repo"] / "TestBro"
        assert project_dir.is_dir()
        assert (project_dir / "TestBro" / "TestBro.csproj").exists()

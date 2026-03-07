"""Tests for project discovery in do_init_thunderstore and do_package.

Reproduces a bug where repos_parent falls back to the wrong directory
(e.g., a pip virtualenv) but configured repos point to the right place.
find_projects uses configured repos and works, but do_init_thunderstore
and do_package re-discover projects by listing repos_parent and fail.
"""
import json

import pytest

from broforce_tools.cli import do_init_thunderstore, do_package


@pytest.fixture
def split_layout(tmp_path, monkeypatch):
    """Layout where repos_parent differs from where repos actually live.

    Simulates a pip/pipx install where repos_parent falls back to the
    virtualenv directory, but config has repos pointing to the real location.
    """
    wrong_parent = tmp_path / "fake_venv"
    wrong_parent.mkdir()

    real_repos = tmp_path / "real_repos"
    repo_dir = real_repos / "MyRepo"
    project_dir = repo_dir / "MyMod"
    modcontent = project_dir / "_ModContent"
    modcontent.mkdir(parents=True)
    (modcontent / "Info.json").write_text(json.dumps({
        "Id": "MyMod", "Version": "1.0.0"
    }))
    (modcontent / "MyMod.dll").write_bytes(b"")
    (project_dir / "MyMod.csproj").write_text("<Project/>")

    # Single-project layout: Release/manifest.json (flat, no project subdirectory)
    releases = repo_dir / "Release"
    releases.mkdir(parents=True)
    (releases / "manifest.json").write_text(json.dumps({
        "name": "MyMod", "author": "TestAuthor", "version_number": "1.0.0",
        "website_url": "", "description": "Test",
        "dependencies": ["UMM-UMM-1.0.0"]
    }))
    (releases / "README.md").write_text("# MyMod")
    (releases / "icon.png").write_bytes(b"\x89PNG" + b"\x00" * 100)
    (releases / "Changelog.md").write_text("## v1.0.0 (unreleased)\n- Initial\n")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({
        "repos": [str(repo_dir)]
    }))
    monkeypatch.setenv("BROFORCE_CONFIG_DIR", str(config_dir))

    return {
        "wrong_parent": str(wrong_parent),
        "repo_dir": str(repo_dir),
        "project_name": "MyMod",
    }


class TestProjectDiscoveryWithConfiguredRepos:
    """Verify that project discovery uses configured repos, not just repos_parent."""

    def test_do_init_thunderstore_finds_project(self, split_layout, monkeypatch):
        """do_init_thunderstore should find project via configured repos."""
        monkeypatch.setenv("BROFORCE_TEMPLATES_DIR", split_layout["repo_dir"])
        try:
            do_init_thunderstore(
                split_layout["project_name"],
                split_layout["wrong_parent"],
                namespace="Test",
                description="Test",
                non_interactive=True,
            )
        except SystemExit as e:
            if e.code == 1:
                pytest.fail(
                    "do_init_thunderstore could not find project — "
                    "it lists repos_parent instead of using configured repos"
                )

    def test_do_package_finds_project(self, split_layout, monkeypatch):
        """do_package should find project via configured repos."""
        monkeypatch.setenv("BROFORCE_TEMPLATES_DIR", split_layout["repo_dir"])
        try:
            do_package(
                split_layout["project_name"],
                split_layout["wrong_parent"],
                non_interactive=True,
                overwrite=True,
            )
        except SystemExit as e:
            if e.code == 1:
                pytest.fail(
                    "do_package could not find project — "
                    "it lists repos_parent instead of using configured repos"
                )

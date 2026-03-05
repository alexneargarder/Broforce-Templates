"""Shared test fixtures for broforce-tools."""
import json
import os
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "test-fixtures"
FIXTURES_REPOS = FIXTURES_DIR / "repos"


@pytest.fixture
def fixtures_dir():
    """Path to the test-fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def fixtures_repos():
    """Path to the test-fixtures/repos directory."""
    return FIXTURES_REPOS


@pytest.fixture
def tmp_changelog(tmp_path):
    """Create a temporary changelog file and return a helper."""
    def _create(content):
        path = tmp_path / "Changelog.md"
        path.write_text(content, encoding="utf-8")
        return str(path)
    return _create


@pytest.fixture
def tmp_mod_project(tmp_path):
    """Create a minimal mod project structure in tmp_path."""
    project = tmp_path / "TestProject"
    modcontent = project / "_ModContent"
    modcontent.mkdir(parents=True)

    info = {"Id": "TestProject", "Version": "1.0.0", "DisplayName": "Test"}
    (modcontent / "Info.json").write_text(json.dumps(info), encoding="utf-8")
    (modcontent / "TestProject.dll").write_bytes(b"")

    return project


@pytest.fixture
def tmp_bro_project(tmp_path):
    """Create a minimal bro project structure in tmp_path."""
    project = tmp_path / "TestBro"
    modcontent = project / "_ModContent"
    modcontent.mkdir(parents=True)

    mod_json = {"Version": "1.0.0", "Name": "TestBro"}
    (modcontent / "TestBro.mod.json").write_text(json.dumps(mod_json), encoding="utf-8")
    (modcontent / "TestBro.dll").write_bytes(b"")

    return project


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Isolate config to a temp directory so tests don't touch real config."""
    monkeypatch.setenv("BROFORCE_CONFIG_DIR", str(tmp_path))
    return tmp_path

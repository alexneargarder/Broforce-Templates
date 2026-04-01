"""Tests for project module - Project dataclass, discovery, and group detection."""
import json
import os

import pytest

from broforce_tools.project import (
    Project,
    _is_direct_project,
    _normalize_wsl_path,
    count_projects_in_repo,
    detect_current_repo,
    detect_project_type,
    find_mod_metadata_dir,
    find_project_by_name,
    find_projects,
    get_releases_path,
    get_repos_to_search,
    get_source_directory,
)


# ---------------------------------------------------------------------------
# Project dataclass
# ---------------------------------------------------------------------------

class TestProject:
    def test_project_dir(self):
        p = Project("MyMod", "BroforceMods", "MyMod", "/home/user/repos")
        assert p.project_dir == os.path.join("/home/user/repos", "BroforceMods", "MyMod")

    def test_project_dir_grouped(self):
        p = Project("BroCaesar", "OverhaulProject", "BrosGroup/BroCaesar", "/home/user/repos")
        assert p.project_dir == os.path.join("/home/user/repos", "OverhaulProject", "BrosGroup/BroCaesar")

    def test_repo_dir(self):
        p = Project("MyMod", "BroforceMods", "MyMod", "/repos")
        assert p.repo_dir == os.path.join("/repos", "BroforceMods")

    def test_source_dir_with_metadata(self):
        p = Project("MyMod", "Repo", "MyMod", "/repos", metadata_dir="/repos/Repo/MyMod/_Mod")
        assert p.source_dir == "/repos/Repo/MyMod"

    def test_source_dir_without_metadata(self):
        p = Project("MyMod", "Repo", "MyMod", "/repos")
        assert p.source_dir is None

    def test_equality(self):
        a = Project("Mod", "Repo", "Mod", "/repos")
        b = Project("Mod", "Repo", "Mod", "/repos")
        assert a == b

    def test_equality_ignores_metadata(self):
        a = Project("Mod", "Repo", "Mod", "/repos", project_type="mod")
        b = Project("Mod", "Repo", "Mod", "/repos", project_type=None)
        assert a == b

    def test_get_releases_path(self, tmp_path):
        repo = tmp_path / "Repo"
        proj = repo / "OnlyProject" / "_ModContent"
        proj.mkdir(parents=True)
        (proj / "Info.json").write_text("{}")
        release = repo / "Release"
        release.mkdir()
        (release / "manifest.json").write_text("{}")
        p = Project("OnlyProject", "Repo", "OnlyProject", str(tmp_path))
        path = p.get_releases_path()
        assert path is not None
        assert path == str(release)


# ---------------------------------------------------------------------------
# Metadata detection (ported from test_templates.py)
# ---------------------------------------------------------------------------

class TestDetectProjectType:
    def test_mod_project(self, fixtures_repos):
        assert detect_project_type(str(fixtures_repos / "TestRepo" / "TestMod")) == "mod"

    def test_bro_project(self, fixtures_repos):
        assert detect_project_type(str(fixtures_repos / "TestRepo" / "TestBro")) == "bro"

    def test_nonexistent(self, tmp_path):
        assert detect_project_type(str(tmp_path / "NoProject")) is None

    def test_empty_dir(self, tmp_path):
        assert detect_project_type(str(tmp_path)) is None

    def test_wardrobe_project(self, tmp_path):
        proj = tmp_path / "Wardrobe"
        content = proj / "_ModContent"
        content.mkdir(parents=True)
        (content / "test.fa.json").write_text("{}")
        assert detect_project_type(str(proj)) == "wardrobe"


class TestFindModMetadataDir:
    def test_finds_mod_metadata(self, fixtures_repos):
        result = find_mod_metadata_dir(str(fixtures_repos / "TestRepo" / "TestMod"))
        assert result is not None
        assert result.endswith("_ModContent")

    def test_finds_bro_metadata(self, fixtures_repos):
        result = find_mod_metadata_dir(str(fixtures_repos / "TestRepo" / "TestBro"))
        assert result is not None
        assert result.endswith("_ModContent")

    def test_returns_none_for_empty(self, tmp_path):
        assert find_mod_metadata_dir(str(tmp_path)) is None

    def test_metadata_at_project_root(self, tmp_path):
        (tmp_path / "Info.json").write_text("{}")
        result = find_mod_metadata_dir(str(tmp_path))
        assert result == str(tmp_path)

    def test_skips_build_dirs(self, tmp_path):
        bin_dir = tmp_path / "bin" / "Debug"
        bin_dir.mkdir(parents=True)
        (bin_dir / "Info.json").write_text("{}")
        assert find_mod_metadata_dir(str(tmp_path)) is None


class TestGetSourceDirectory:
    def test_returns_parent_of_metadata(self, fixtures_repos):
        result = get_source_directory(str(fixtures_repos / "TestRepo" / "TestMod"))
        assert result is not None
        assert result.endswith("TestMod")

    def test_returns_none_when_no_metadata(self, tmp_path):
        assert get_source_directory(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# Direct project detection and group detection
# ---------------------------------------------------------------------------

class TestIsDirectProject:
    def test_project_with_csproj(self, tmp_path):
        proj = tmp_path / "MyMod"
        proj.mkdir()
        (proj / "MyMod.csproj").write_text("<Project/>")
        assert _is_direct_project(str(proj))

    def test_standard_nested_layout(self, tmp_path):
        outer = tmp_path / "MyMod"
        inner = outer / "MyMod"
        inner.mkdir(parents=True)
        (inner / "MyMod.csproj").write_text("<Project/>")
        assert _is_direct_project(str(outer))

    def test_project_with_metadata(self, tmp_path):
        proj = tmp_path / "MyMod"
        mod = proj / "_ModContent"
        mod.mkdir(parents=True)
        (mod / "Info.json").write_text("{}")
        assert _is_direct_project(str(proj))

    def test_group_folder_is_not_direct_nested(self, tmp_path):
        """Group with children using standard ProjectName/ProjectName/*.csproj layout."""
        group = tmp_path / "GroupFolder"
        child = group / "ChildProject"
        inner = child / "ChildProject"
        inner.mkdir(parents=True)
        (inner / "ChildProject.csproj").write_text("<Project/>")
        assert not _is_direct_project(str(group))

    def test_group_folder_is_not_direct_flat(self, tmp_path):
        """Group with children that have .csproj directly in their root."""
        group = tmp_path / "GroupFolder"
        child = group / "ChildProject"
        child.mkdir(parents=True)
        (child / "ChildProject.csproj").write_text("<Project/>")
        assert not _is_direct_project(str(group))

    def test_empty_dir(self, tmp_path):
        empty = tmp_path / "Empty"
        empty.mkdir()
        assert not _is_direct_project(str(empty))


# ---------------------------------------------------------------------------
# Project discovery (ported + extended)
# ---------------------------------------------------------------------------

class TestFindProjects:
    def test_finds_all_in_repo(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["TestRepo"])
        names = [p.name for p in projects]
        assert "TestMod" in names
        assert "TestBro" in names
        assert "NewMod" in names

    def test_returns_project_objects(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["TestRepo"])
        for p in projects:
            assert isinstance(p, Project)
            assert p.repos_parent == str(fixtures_repos)
            assert p.repo == "TestRepo"

    def test_require_metadata(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["TestRepo"], require_metadata=True)
        names = [p.name for p in projects]
        assert "TestMod" in names
        assert "TestBro" in names
        assert "NewMod" not in names

    def test_exclude_with_metadata(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["TestRepo"], exclude_with_metadata=True)
        names = [p.name for p in projects]
        assert "NewMod" in names
        assert "TestMod" not in names

    def test_multiple_repos(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["TestRepo", "AnotherRepo"])
        names = [p.name for p in projects]
        assert "TestMod" in names
        assert "OtherMod" in names

    def test_nonexistent_repo(self, fixtures_repos):
        assert find_projects(str(fixtures_repos), ["NonExistent"]) == []

    def test_skips_dotfiles_and_underscored(self, tmp_path):
        repo = tmp_path / "Repo"
        repo.mkdir()
        hidden = repo / ".hidden"
        hidden.mkdir()
        (hidden / "Info.json").write_text("{}")
        underscored = repo / "_private"
        underscored.mkdir()
        (underscored / "Info.json").write_text("{}")
        projects = find_projects(str(tmp_path), ["Repo"])
        names = [p.name for p in projects]
        assert ".hidden" not in names
        assert "_private" not in names

    def test_results_sorted(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["TestRepo", "AnotherRepo"])
        names = [p.name for p in projects]
        assert names == sorted(names)

    def test_ignores_configured_projects(self, fixtures_repos, isolated_config):
        config = {"repos": ["TestRepo"], "ignore": {"TestRepo": ["TestMod"]}}
        (isolated_config / "config.json").write_text(json.dumps(config))
        projects = find_projects(str(fixtures_repos), ["TestRepo"])
        names = [p.name for p in projects]
        assert "TestMod" not in names
        assert "TestBro" in names


class TestGroupDetection:
    """Tests for nested project group discovery."""

    @pytest.fixture
    def grouped_repo(self, tmp_path):
        """Create a repo with a group folder containing multiple projects."""
        repo = tmp_path / "GroupedRepo"
        repo.mkdir()

        # Group folder with 2 child projects
        group = repo / "MyGroup"
        for name in ["ProjectA", "ProjectB"]:
            inner = group / name / name
            inner.mkdir(parents=True)
            (inner / f"{name}.csproj").write_text("<Project/>")
            mod = group / name / "_ModContent"
            mod.mkdir(exist_ok=True)
            (mod / "Info.json").write_text(json.dumps({"Id": name, "Version": "1.0.0"}))

        # Standard flat project alongside the group
        flat = repo / "FlatProject" / "FlatProject"
        flat.mkdir(parents=True)
        (flat / "FlatProject.csproj").write_text("<Project/>")
        flat_mod = repo / "FlatProject" / "_ModContent"
        flat_mod.mkdir()
        (flat_mod / "Info.json").write_text(json.dumps({"Id": "FlatProject", "Version": "1.0.0"}))

        return tmp_path

    def test_discovers_grouped_projects(self, grouped_repo):
        projects = find_projects(str(grouped_repo), ["GroupedRepo"])
        names = [p.name for p in projects]
        assert "ProjectA" in names
        assert "ProjectB" in names
        assert "MyGroup" not in names

    def test_discovers_flat_alongside_group(self, grouped_repo):
        projects = find_projects(str(grouped_repo), ["GroupedRepo"])
        names = [p.name for p in projects]
        assert "FlatProject" in names

    def test_grouped_subdir_includes_group_name(self, grouped_repo):
        projects = find_projects(str(grouped_repo), ["GroupedRepo"])
        by_name = {p.name: p for p in projects}
        assert by_name["ProjectA"].subdir == os.path.join("MyGroup", "ProjectA")
        assert by_name["ProjectB"].subdir == os.path.join("MyGroup", "ProjectB")
        assert by_name["FlatProject"].subdir == "FlatProject"

    def test_grouped_project_dir(self, grouped_repo):
        projects = find_projects(str(grouped_repo), ["GroupedRepo"])
        by_name = {p.name: p for p in projects}
        expected = os.path.join(str(grouped_repo), "GroupedRepo", "MyGroup", "ProjectA")
        assert by_name["ProjectA"].project_dir == expected

    def test_total_project_count(self, grouped_repo):
        projects = find_projects(str(grouped_repo), ["GroupedRepo"])
        assert len(projects) == 3

    def test_count_includes_grouped(self, grouped_repo):
        count = count_projects_in_repo(str(grouped_repo), "GroupedRepo")
        assert count == 3

    def test_no_duplicates_when_group_also_listed_as_repo(self, tmp_path):
        """If a group folder is also symlinked/listed as a separate repo,
        projects should not appear twice."""
        repo = tmp_path / "ParentRepo"
        group = repo / "MyGroup"
        for name in ["ProjectA", "ProjectB"]:
            inner = group / name / name
            inner.mkdir(parents=True)
            (inner / f"{name}.csproj").write_text("<Project/>")
            mod = group / name / "_ModContent"
            mod.mkdir(exist_ok=True)
            (mod / "Info.json").write_text(json.dumps({"Id": name, "Version": "1.0.0"}))

        # MyGroup also appears as a top-level "repo" (e.g., user added it separately)
        # Create a symlink so it resolves as a real directory
        (tmp_path / "MyGroup").symlink_to(group)

        projects = find_projects(str(tmp_path), ["ParentRepo", "MyGroup"])
        names = [p.name for p in projects]
        assert names.count("ProjectA") == 1
        assert names.count("ProjectB") == 1


# ---------------------------------------------------------------------------
# find_project_by_name
# ---------------------------------------------------------------------------

class TestFindProjectByName:
    def test_finds_existing(self, fixtures_repos, isolated_config):
        config = {"repos": ["TestRepo"]}
        (isolated_config / "config.json").write_text(json.dumps(config))
        project = find_project_by_name(str(fixtures_repos), "TestMod")
        assert project is not None
        assert project.name == "TestMod"
        assert project.repo == "TestRepo"

    def test_returns_none_for_missing(self, fixtures_repos, isolated_config):
        config = {"repos": ["TestRepo"]}
        (isolated_config / "config.json").write_text(json.dumps(config))
        assert find_project_by_name(str(fixtures_repos), "NonExistent") is None

    def test_with_explicit_repos(self, fixtures_repos):
        project = find_project_by_name(str(fixtures_repos), "TestMod", repos=["TestRepo"])
        assert project is not None

    def test_require_metadata(self, fixtures_repos):
        project = find_project_by_name(
            str(fixtures_repos), "NewMod", repos=["TestRepo"], require_metadata=True
        )
        assert project is None


# ---------------------------------------------------------------------------
# Release paths (ported from test_templates.py)
# ---------------------------------------------------------------------------

class TestGetReleasesPath:
    def test_multi_project_existing(self, fixtures_repos):
        path = get_releases_path(str(fixtures_repos), "TestRepo", "TestMod", create=False)
        assert path is not None
        assert path.endswith(os.path.join("Releases", "TestMod"))

    def test_no_metadata_returns_none(self, fixtures_repos):
        path = get_releases_path(str(fixtures_repos), "TestRepo", "NewMod", create=False)
        assert path is None

    def test_create_multi_project(self, fixtures_repos):
        path = get_releases_path(str(fixtures_repos), "TestRepo", "NewMod", create=True)
        assert path is not None
        assert "NewMod" in path

    def test_single_project_flat(self, tmp_path):
        repo = tmp_path / "SingleRepo"
        proj = repo / "OnlyProject" / "_ModContent"
        proj.mkdir(parents=True)
        (proj / "Info.json").write_text("{}")
        release = repo / "Release"
        release.mkdir()
        (release / "manifest.json").write_text("{}")
        path = get_releases_path(str(tmp_path), "SingleRepo", "OnlyProject", create=False)
        assert path is not None
        assert path == str(release)

    def test_uses_existing_release_folder(self, tmp_path):
        repo = tmp_path / "Repo"
        repo.mkdir()
        (repo / "Release").mkdir()
        path = get_releases_path(str(tmp_path), "Repo", "Proj", create=True)
        assert "Release" in path


class TestCountProjectsInRepo:
    def test_testrepo(self, fixtures_repos):
        count = count_projects_in_repo(str(fixtures_repos), "TestRepo")
        assert count == 3

    def test_anotherrepo(self, fixtures_repos):
        count = count_projects_in_repo(str(fixtures_repos), "AnotherRepo")
        assert count == 2

    def test_nonexistent(self, fixtures_repos):
        assert count_projects_in_repo(str(fixtures_repos), "NoRepo") == 0


# ---------------------------------------------------------------------------
# Repo detection (ported from test_templates.py)
# ---------------------------------------------------------------------------

class TestNormalizeWslPath:
    def test_windows_c_drive(self):
        path, alt = _normalize_wsl_path("c:/users/foo")
        assert path == "/mnt/c/users/foo"
        assert alt is None

    def test_wsl_c_drive(self):
        path, alt = _normalize_wsl_path("/mnt/c/users/foo")
        assert path == "/mnt/c/users/foo"
        assert alt == "c:/users/foo"

    def test_windows_d_drive(self):
        path, alt = _normalize_wsl_path("d:/repos")
        assert path == "/mnt/d/repos"
        assert alt is None

    def test_wsl_d_drive(self):
        path, alt = _normalize_wsl_path("/mnt/d/repos")
        assert path == "/mnt/d/repos"
        assert alt == "d:/repos"

    def test_linux_path_unchanged(self):
        path, alt = _normalize_wsl_path("/home/user/repos")
        assert path == "/home/user/repos"
        assert alt is None

    def test_empty_after_drive(self):
        path, alt = _normalize_wsl_path("c:/")
        assert path == "/mnt/c/"

    def test_uppercase_not_matched(self):
        path, alt = _normalize_wsl_path("C:/users/foo")
        assert path == "C:/users/foo"
        assert alt is None


class TestDetectCurrentRepo:
    def test_detects_from_cwd(self, fixtures_repos, monkeypatch):
        monkeypatch.chdir(str(fixtures_repos / "TestRepo"))
        result = detect_current_repo(str(fixtures_repos))
        assert result == "TestRepo"

    def test_detects_from_subdirectory(self, fixtures_repos, monkeypatch):
        monkeypatch.chdir(str(fixtures_repos / "TestRepo" / "TestMod"))
        result = detect_current_repo(str(fixtures_repos))
        assert result == "TestRepo"

    def test_returns_none_outside(self, tmp_path, monkeypatch):
        monkeypatch.chdir(str(tmp_path))
        result = detect_current_repo(str(tmp_path / "repos"))
        assert result is None

    def test_case_insensitive(self, tmp_path, monkeypatch):
        repo = tmp_path / "MyRepo"
        repo.mkdir()
        monkeypatch.chdir(str(repo))
        result = detect_current_repo(str(tmp_path))
        assert result == "MyRepo"


class TestGetReposToSearch:
    def test_all_repos(self, isolated_config):
        config = {"repos": ["RepoA", "RepoB"]}
        (isolated_config / "config.json").write_text(json.dumps(config))
        repos, is_single = get_repos_to_search(str(isolated_config), use_all_repos=True)
        assert repos == ["RepoA", "RepoB"]
        assert not is_single

    def test_all_repos_empty(self, isolated_config):
        repos, _ = get_repos_to_search(str(isolated_config), use_all_repos=True)
        assert repos is None

    def test_current_repo(self, fixtures_repos, monkeypatch):
        monkeypatch.chdir(str(fixtures_repos / "TestRepo"))
        repos, is_single = get_repos_to_search(str(fixtures_repos))
        assert repos == ["TestRepo"]
        assert is_single

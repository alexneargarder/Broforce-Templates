"""Tests for templates module - path normalization, project discovery, file operations."""
import json
import os
import stat
import xml.etree.ElementTree as ET

import pytest

from broforce_tools.templates import (
    _normalize_wsl_path,
    copyanything,
    count_projects_in_repo,
    detect_current_repo,
    detect_project_type,
    find_mod_metadata_dir,
    find_projects,
    find_props_file,
    find_replace,
    get_releases_path,
    get_repos_to_search,
    get_source_directory,
    parse_props_file,
    rename_files,
)


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
        """Uppercase drive letters don't match (input should be lowered first)."""
        path, alt = _normalize_wsl_path("C:/users/foo")
        assert path == "C:/users/foo"
        assert alt is None


class TestFindReplace:
    def test_replaces_in_matching_files(self, tmp_path):
        (tmp_path / "test.txt").write_text("Hello World")
        find_replace(str(tmp_path), "World", "Python", "*.txt")
        assert (tmp_path / "test.txt").read_text() == "Hello Python"

    def test_skips_non_matching_patterns(self, tmp_path):
        (tmp_path / "test.cs").write_text("Hello World")
        find_replace(str(tmp_path), "World", "Python", "*.txt")
        assert (tmp_path / "test.cs").read_text() == "Hello World"

    def test_recurses_into_subdirs(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "test.txt").write_text("Hello World")
        find_replace(str(tmp_path), "World", "Python", "*.txt")
        assert (sub / "test.txt").read_text() == "Hello Python"

    def test_no_double_processing(self, tmp_path):
        """Verify files aren't processed multiple times (regression test for removed recursive call)."""
        sub = tmp_path / "sub1" / "sub2"
        sub.mkdir(parents=True)
        (sub / "test.txt").write_text("AAA")
        find_replace(str(tmp_path), "A", "AB", "*.txt")
        content = (sub / "test.txt").read_text()
        assert content == "ABABAB"

    def test_multiple_files(self, tmp_path):
        (tmp_path / "a.txt").write_text("old")
        (tmp_path / "b.txt").write_text("old value")
        find_replace(str(tmp_path), "old", "new", "*.txt")
        assert (tmp_path / "a.txt").read_text() == "new"
        assert (tmp_path / "b.txt").read_text() == "new value"


class TestRenameFiles:
    def test_renames_files(self, tmp_path):
        (tmp_path / "OldName.cs").write_text("code")
        (tmp_path / "OldName.csproj").write_text("project")
        rename_files(str(tmp_path), "OldName", "NewName")
        assert (tmp_path / "NewName.cs").exists()
        assert (tmp_path / "NewName.csproj").exists()
        assert not (tmp_path / "OldName.cs").exists()

    def test_renames_directories(self, tmp_path):
        sub = tmp_path / "OldName"
        sub.mkdir()
        (sub / "file.txt").write_text("content")
        rename_files(str(tmp_path), "OldName", "NewName")
        assert (tmp_path / "NewName").is_dir()
        assert (tmp_path / "NewName" / "file.txt").exists()

    def test_recursive_rename(self, tmp_path):
        outer = tmp_path / "OldName"
        inner = outer / "OldName"
        inner.mkdir(parents=True)
        (inner / "OldName.txt").write_text("data")
        rename_files(str(tmp_path), "OldName", "NewName")
        assert (tmp_path / "NewName" / "NewName" / "NewName.txt").exists()


class TestCopyanything:
    def test_copies_directory(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("hello")
        dst = tmp_path / "dst"
        copyanything(str(src), str(dst))
        assert (dst / "file.txt").read_text() == "hello"

    def test_ignores_vs_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("keep")
        (src / "file.suo").write_text("ignore")
        (src / "file.user").write_text("ignore")
        vs_dir = src / ".vs"
        vs_dir.mkdir()
        (vs_dir / "settings.json").write_text("ignore")
        dst = tmp_path / "dst"
        copyanything(str(src), str(dst))
        assert (dst / "file.txt").exists()
        assert not (dst / "file.suo").exists()
        assert not (dst / "file.user").exists()
        assert not (dst / ".vs").exists()

    def test_makes_writable(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        f = src / "readonly.txt"
        f.write_text("data")
        f.chmod(stat.S_IRUSR)
        dst = tmp_path / "dst"
        copyanything(str(src), str(dst))
        dst_file = dst / "readonly.txt"
        assert dst_file.stat().st_mode & stat.S_IWUSR


class TestFindPropsFile:
    def test_finds_in_current_dir(self, tmp_path):
        (tmp_path / "Test.props").write_text("<Project/>")
        assert find_props_file(str(tmp_path), "Test.props") is not None

    def test_finds_in_parent(self, tmp_path):
        (tmp_path / "Test.props").write_text("<Project/>")
        child = tmp_path / "child"
        child.mkdir()
        result = find_props_file(str(child), "Test.props")
        assert result is not None
        assert "Test.props" in result

    def test_returns_none_when_not_found(self, tmp_path):
        assert find_props_file(str(tmp_path), "NonExistent.props") is None


class TestParsePropsFile:
    def test_extracts_namespaced_property(self, tmp_path):
        props = tmp_path / "test.props"
        props.write_text(
            '<?xml version="1.0"?>\n'
            '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">\n'
            '  <PropertyGroup><BroforcePath>C:\\Games\\Broforce</BroforcePath></PropertyGroup>\n'
            '</Project>'
        )
        assert parse_props_file(str(props), "BroforcePath") == "C:\\Games\\Broforce"

    def test_extracts_non_namespaced_property(self, tmp_path):
        props = tmp_path / "test.props"
        props.write_text(
            '<Project>\n'
            '  <PropertyGroup><MyProp>value</MyProp></PropertyGroup>\n'
            '</Project>'
        )
        assert parse_props_file(str(props), "MyProp") == "value"

    def test_returns_none_for_missing_property(self, tmp_path):
        props = tmp_path / "test.props"
        props.write_text('<Project><PropertyGroup></PropertyGroup></Project>')
        assert parse_props_file(str(props), "Missing") is None

    def test_handles_malformed_xml(self, tmp_path):
        props = tmp_path / "bad.props"
        props.write_text("not xml at all")
        assert parse_props_file(str(props), "Anything") is None


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
        """Metadata files directly in the project directory (no subdirectory)."""
        (tmp_path / "Info.json").write_text("{}")
        result = find_mod_metadata_dir(str(tmp_path))
        assert result == str(tmp_path)

    def test_skips_build_dirs(self, tmp_path):
        """Metadata in bin/obj should be ignored."""
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


class TestFindProjects:
    def test_finds_all_in_repo(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["TestRepo"])
        names = [p[0] for p in projects]
        assert "TestMod" in names
        assert "TestBro" in names
        assert "NewMod" in names

    def test_require_metadata(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["TestRepo"], require_metadata=True)
        names = [p[0] for p in projects]
        assert "TestMod" in names
        assert "TestBro" in names
        assert "NewMod" not in names

    def test_exclude_with_metadata(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["TestRepo"], exclude_with_metadata=True)
        names = [p[0] for p in projects]
        assert "NewMod" in names
        assert "TestMod" not in names

    def test_multiple_repos(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["TestRepo", "AnotherRepo"])
        names = [p[0] for p in projects]
        assert "TestMod" in names
        assert "OtherMod" in names

    def test_nonexistent_repo(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["NonExistent"])
        assert projects == []

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
        names = [p[0] for p in projects]
        assert ".hidden" not in names
        assert "_private" not in names

    def test_results_sorted(self, fixtures_repos):
        projects = find_projects(str(fixtures_repos), ["TestRepo", "AnotherRepo"])
        names = [p[0] for p in projects]
        assert names == sorted(names)

    def test_ignores_configured_projects(self, fixtures_repos, isolated_config):
        import json as json_mod
        config = {"repos": ["TestRepo"], "ignore": {"TestRepo": ["TestMod"]}}
        (isolated_config / "config.json").write_text(json_mod.dumps(config))
        projects = find_projects(str(fixtures_repos), ["TestRepo"])
        names = [p[0] for p in projects]
        assert "TestMod" not in names
        assert "TestBro" in names


class TestCountProjectsInRepo:
    def test_testrepo(self, fixtures_repos):
        count = count_projects_in_repo(str(fixtures_repos), "TestRepo")
        assert count == 3

    def test_anotherrepo(self, fixtures_repos):
        count = count_projects_in_repo(str(fixtures_repos), "AnotherRepo")
        assert count == 2

    def test_nonexistent(self, fixtures_repos):
        assert count_projects_in_repo(str(fixtures_repos), "NoRepo") == 0


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
        """Single-project repo uses flat Release/ layout."""
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
        """Prefers existing Release/ or Releases/ folder."""
        repo = tmp_path / "Repo"
        repo.mkdir()
        (repo / "Release").mkdir()
        path = get_releases_path(str(tmp_path), "Repo", "Proj", create=True)
        assert "Release" in path


class TestGetReposToSearch:
    def test_all_repos(self, isolated_config):
        import json as json_mod
        config = {"repos": ["RepoA", "RepoB"]}
        (isolated_config / "config.json").write_text(json_mod.dumps(config))
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
        """Repo detection preserves actual casing even if cwd casing differs."""
        repo = tmp_path / "MyRepo"
        repo.mkdir()
        monkeypatch.chdir(str(repo))
        result = detect_current_repo(str(tmp_path))
        assert result == "MyRepo"

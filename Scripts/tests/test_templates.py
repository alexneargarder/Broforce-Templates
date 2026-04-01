"""Tests for templates module - file operations and props parsing."""
import stat

import pytest

from broforce_tools.templates import (
    copyanything,
    find_props_file,
    find_replace,
    parse_props_file,
    rename_files,
)


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

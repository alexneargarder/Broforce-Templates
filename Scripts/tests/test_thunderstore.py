"""Tests for thunderstore module - version parsing, validation, dependencies."""
import json
import os

import pytest

from broforce_tools.thunderstore import (
    add_changelog_entry,
    clear_cache,
    compare_versions,
    detect_dependencies_from_csproj,
    find_changelog,
    find_dll_in_modcontent,
    get_dependencies,
    get_latest_version_entries,
    get_unreleased_entries,
    get_version_from_changelog,
    get_version_from_info_json,
    has_unreleased_version,
    sanitize_package_name,
    sync_version_file,
    validate_package_name,
)


class TestValidatePackageName:
    def test_valid_alphanumeric(self):
        assert validate_package_name("MyMod123") == (True, "OK")

    def test_valid_underscores(self):
        assert validate_package_name("My_Mod") == (True, "OK")

    def test_invalid_spaces(self):
        valid, _ = validate_package_name("My Mod")
        assert not valid

    def test_invalid_special_chars(self):
        valid, _ = validate_package_name("My-Mod!")
        assert not valid

    def test_invalid_hyphens(self):
        valid, _ = validate_package_name("My-Mod")
        assert not valid

    def test_too_long(self):
        valid, msg = validate_package_name("A" * 129)
        assert not valid
        assert "128" in msg

    def test_max_length(self):
        assert validate_package_name("A" * 128) == (True, "OK")


class TestSanitizePackageName:
    def test_spaces_to_underscores(self):
        assert sanitize_package_name("My Mod") == "My_Mod"

    def test_special_chars_removed(self):
        assert sanitize_package_name("My-Mod!") == "MyMod"

    def test_already_valid(self):
        assert sanitize_package_name("MyMod") == "MyMod"

    def test_mixed(self):
        assert sanitize_package_name("My Cool Mod!") == "My_Cool_Mod"


class TestCompareVersions:
    def test_equal(self):
        assert compare_versions("1.0.0", "1.0.0") == 0

    def test_greater_major(self):
        assert compare_versions("2.0.0", "1.0.0") == 1

    def test_lesser_minor(self):
        assert compare_versions("1.0.0", "1.1.0") == -1

    def test_greater_patch(self):
        assert compare_versions("1.0.1", "1.0.0") == 1

    def test_different_length(self):
        assert compare_versions("1.0", "1.0.0") == 0

    def test_none_first(self):
        assert compare_versions(None, "1.0.0") == -1

    def test_none_second(self):
        assert compare_versions("1.0.0", None) == 1

    def test_both_none(self):
        assert compare_versions(None, None) == -1


class TestGetLatestVersionEntries:
    def test_standard_version(self, tmp_changelog):
        path = tmp_changelog("## v1.0.0\n- Initial release\n")
        version, is_unreleased, entries = get_latest_version_entries(path)
        assert version == "1.0.0"
        assert not is_unreleased
        assert entries == ["- Initial release"]

    def test_unreleased_version(self, tmp_changelog):
        path = tmp_changelog("## v2.0.0 (unreleased)\n- New feature\n- Bug fix\n")
        version, is_unreleased, entries = get_latest_version_entries(path)
        assert version == "2.0.0"
        assert is_unreleased
        assert len(entries) == 2

    def test_multiple_versions_returns_first(self, tmp_changelog):
        path = tmp_changelog("## v2.0.0\n- New\n\n## v1.0.0\n- Old\n")
        version, _, entries = get_latest_version_entries(path)
        assert version == "2.0.0"
        assert entries == ["- New"]

    def test_without_v_prefix(self, tmp_changelog):
        path = tmp_changelog("## 1.5.0\n- Something\n")
        version, _, _ = get_latest_version_entries(path)
        assert version == "1.5.0"

    def test_empty_file(self, tmp_changelog):
        path = tmp_changelog("")
        version, _, entries = get_latest_version_entries(path)
        assert version is None
        assert entries == []

    def test_missing_file(self):
        version, _, entries = get_latest_version_entries("/nonexistent/path")
        assert version is None
        assert entries == []

    def test_no_entries(self, tmp_changelog):
        path = tmp_changelog("## v1.0.0\n\n## v0.9.0\n- old\n")
        version, _, entries = get_latest_version_entries(path)
        assert version == "1.0.0"
        assert entries == []


class TestHasUnreleasedVersion:
    def test_unreleased(self, tmp_changelog):
        path = tmp_changelog("## v1.0.0 (unreleased)\n- Stuff\n")
        is_unreleased, version = has_unreleased_version(path)
        assert is_unreleased
        assert version == "1.0.0"

    def test_released(self, tmp_changelog):
        path = tmp_changelog("## v1.0.0\n- Stuff\n")
        is_unreleased, version = has_unreleased_version(path)
        assert not is_unreleased
        assert version is None


class TestAddChangelogEntry:
    def test_adds_entry(self, tmp_changelog):
        path = tmp_changelog("## v1.0.0 (unreleased)\n- Existing\n")
        result = add_changelog_entry(path, "New feature")
        assert result
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "- New feature" in content
        assert content.index("- New feature") < content.index("- Existing")

    def test_fails_on_released(self, tmp_changelog):
        path = tmp_changelog("## v1.0.0\n- Released\n")
        assert not add_changelog_entry(path, "New feature")

    def test_fails_on_missing_file(self):
        assert not add_changelog_entry("/nonexistent/path", "Entry")


class TestFindChangelog:
    def test_finds_changelog_md(self, tmp_path):
        (tmp_path / "Changelog.md").write_text("# Changelog")
        assert find_changelog(str(tmp_path)) is not None

    def test_finds_uppercase(self, tmp_path):
        (tmp_path / "CHANGELOG.md").write_text("# Changelog")
        assert find_changelog(str(tmp_path)) is not None

    def test_returns_none(self, tmp_path):
        assert find_changelog(str(tmp_path)) is None


class TestDetectDependenciesFromCsproj:
    def test_mod_with_rocketlib(self, fixtures_repos):
        project_path = str(fixtures_repos / "TestRepo" / "TestMod")
        deps = detect_dependencies_from_csproj(project_path)
        assert any("UMM" in d for d in deps)
        assert any("RocketLib" in d for d in deps)

    def test_bro_with_bromaker(self, fixtures_repos):
        project_path = str(fixtures_repos / "TestRepo" / "TestBro")
        deps = detect_dependencies_from_csproj(project_path)
        assert any("UMM" in d for d in deps)
        assert any("BroMaker" in d for d in deps)

    def test_no_csproj(self, tmp_path):
        deps = detect_dependencies_from_csproj(str(tmp_path))
        assert len(deps) == 1
        assert "UMM" in deps[0]


class TestFindDllInModcontent:
    def test_finds_dll(self, tmp_mod_project):
        modcontent = str(tmp_mod_project / "_ModContent")
        assert find_dll_in_modcontent(modcontent) is not None
        assert find_dll_in_modcontent(modcontent).endswith(".dll")

    def test_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert find_dll_in_modcontent(str(empty)) is None

    def test_missing_dir(self):
        assert find_dll_in_modcontent("/nonexistent") is None


class TestSyncVersionFile:
    def test_updates_info_json(self, tmp_mod_project):
        modcontent = str(tmp_mod_project / "_ModContent")
        updated, path = sync_version_file(modcontent, "mod", "2.0.0")
        assert updated
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["Version"] == "2.0.0"

    def test_already_correct(self, tmp_mod_project):
        modcontent = str(tmp_mod_project / "_ModContent")
        updated, path = sync_version_file(modcontent, "mod", "1.0.0")
        assert not updated
        assert path is not None

    def test_updates_mod_json(self, tmp_bro_project):
        modcontent = str(tmp_bro_project / "_ModContent")
        updated, path = sync_version_file(modcontent, "bro", "2.0.0")
        assert updated

    def test_missing_dir(self):
        updated, path = sync_version_file("/nonexistent", "mod", "1.0.0")
        assert not updated
        assert path is None

    def test_wardrobe_no_version_file(self, tmp_path):
        """Wardrobe type has no version_file_label, so sync should return (False, None)."""
        updated, path = sync_version_file(str(tmp_path), "wardrobe", "1.0.0")
        assert not updated
        assert path is None

    def test_unknown_type(self, tmp_path):
        updated, path = sync_version_file(str(tmp_path), "unknown", "1.0.0")
        assert not updated
        assert path is None


class TestGetVersionFromChangelog:
    def test_returns_version(self, tmp_changelog):
        path = tmp_changelog("## v1.2.3\n- stuff\n")
        assert get_version_from_changelog(path) == "1.2.3"

    def test_returns_none_for_empty(self, tmp_changelog):
        path = tmp_changelog("")
        assert get_version_from_changelog(path) is None


class TestGetUnreleasedEntries:
    def test_unreleased(self, tmp_changelog):
        path = tmp_changelog("## v1.0.0 (unreleased)\n- Feature A\n- Feature B\n")
        version, entries = get_unreleased_entries(path)
        assert version == "1.0.0"
        assert len(entries) == 2

    def test_released_returns_empty(self, tmp_changelog):
        path = tmp_changelog("## v1.0.0\n- Released\n")
        version, entries = get_unreleased_entries(path)
        assert version is None
        assert entries == []


class TestGetVersionFromInfoJson:
    def test_mod_version(self, tmp_mod_project):
        modcontent = str(tmp_mod_project / "_ModContent")
        assert get_version_from_info_json(modcontent, "mod") == "1.0.0"

    def test_bro_version(self, tmp_bro_project):
        modcontent = str(tmp_bro_project / "_ModContent")
        assert get_version_from_info_json(modcontent, "bro") == "1.0.0"

    def test_missing_dir(self):
        assert get_version_from_info_json("/nonexistent", "mod") is None

    def test_wardrobe_no_version(self, tmp_path):
        assert get_version_from_info_json(str(tmp_path), "wardrobe") is None


class TestGetDependencies:
    def test_returns_formatted_strings(self):
        deps = get_dependencies()
        assert isinstance(deps, dict)
        for key, value in deps.items():
            assert "-" in value
            parts = value.split("-")
            assert len(parts) >= 3


class TestClearCache:
    def test_clears_existing(self, isolated_config):
        from broforce_tools.config import get_cache_file
        cache_file = get_cache_file()
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text('{"test": true}')
        assert clear_cache()
        assert not cache_file.exists()

    def test_no_file(self, isolated_config):
        assert not clear_cache()


class TestCompareVersionsEdgeCases:
    def test_malformed_version(self):
        """Malformed versions should return 0 (no crash)."""
        assert compare_versions("abc", "def") == 0

    def test_partially_malformed(self):
        assert compare_versions("1.0.abc", "1.0.0") == 0


class TestDetectDependenciesEdgeCases:
    def test_non_namespaced_csproj(self, tmp_path):
        """Test .csproj without XML namespace (fallback path)."""
        proj = tmp_path / "Proj"
        proj.mkdir()
        csproj = proj / "Proj.csproj"
        csproj.write_text(
            '<Project>\n'
            '  <ItemGroup>\n'
            '    <Reference Include="RocketLib" />\n'
            '  </ItemGroup>\n'
            '</Project>'
        )
        deps = detect_dependencies_from_csproj(str(proj))
        assert any("RocketLib" in d for d in deps)

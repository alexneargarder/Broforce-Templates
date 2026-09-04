"""Tests for thunderstore module - version parsing, validation, dependencies."""
import http.client
import json
import os
import time
import zipfile

import pytest
import typer

from broforce_tools import thunderstore
from broforce_tools.config import get_cache_file
from broforce_tools.project import Project
from broforce_tools.thunderstore import (
    CACHE_DURATION,
    CACHE_SCHEMA,
    DependencyVersionsUnavailable,
    FETCH_RETRY_INTERVAL,
    THUNDERSTORE_PACKAGES,
    add_changelog_entry,
    clear_cache,
    compare_versions,
    detect_dependencies_from_csproj,
    do_package,
    fetch_thunderstore_version,
    find_changelog,
    find_dll_in_modcontent,
    get_dependencies,
    get_dependency_versions,
    get_latest_version_entries,
    get_unreleased_entries,
    get_version_from_changelog,
    get_version_from_info_json,
    has_unreleased_version,
    parse_version,
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
        from broforce_tools.config import get_cache_file
        get_cache_file().unlink()
        assert not clear_cache()


class TestParseVersion:
    def test_parses_dotted(self):
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_parses_short(self):
        assert parse_version("1.2") == (1, 2)

    def test_none(self):
        assert parse_version(None) is None

    def test_empty(self):
        assert parse_version("") is None

    def test_unparsable(self):
        assert parse_version("1.0.abc") is None

    def test_not_a_version(self):
        assert parse_version("abc") is None


class TestCompareVersionsEdgeCases:
    def test_both_malformed(self):
        assert compare_versions("abc", "def") == 0

    def test_malformed_sorts_below_parsable(self):
        assert compare_versions("1.0.abc", "1.0.0") == -1

    def test_parsable_sorts_above_malformed(self):
        assert compare_versions("1.0.0", "1.0.abc") == 1


class TestDetectDependenciesEdgeCases:
    @pytest.fixture
    def deps_map(self, monkeypatch):
        mapping = {
            "UMM": "UMM-UMM-1.0.0",
            "RocketLib": "RocketLib-RocketLib-2.0.0",
            "BroMaker": "BroMaker-BroMaker-3.0.0",
            "DresserMod": "Gorzontrok-DresserMod-4.0.0",
        }
        monkeypatch.setattr(thunderstore, "get_dependencies", lambda: mapping)
        return mapping

    @staticmethod
    def _write_csproj(path, include, namespaced):
        path.parent.mkdir(parents=True, exist_ok=True)
        attrs = ' xmlns="http://schemas.microsoft.com/developer/msbuild/2003"' if namespaced else ''
        refs = f'    <Reference Include="{include}" />\n' if include else ''
        path.write_text(
            f'<Project{attrs}>\n  <ItemGroup>\n{refs}  </ItemGroup>\n</Project>'
        )

    def test_namespaced_csproj(self, tmp_path, deps_map):
        self._write_csproj(tmp_path / "Proj.csproj", "RocketLib", namespaced=True)
        deps = detect_dependencies_from_csproj(str(tmp_path))
        assert deps == [deps_map["UMM"], deps_map["RocketLib"]]

    def test_non_namespaced_csproj(self, tmp_path, deps_map):
        self._write_csproj(tmp_path / "Proj.csproj", "RocketLib", namespaced=False)
        deps = detect_dependencies_from_csproj(str(tmp_path))
        assert deps == [deps_map["UMM"], deps_map["RocketLib"]]

    def test_reference_in_second_csproj(self, tmp_path, deps_map):
        self._write_csproj(tmp_path / "A.csproj", None, namespaced=True)
        self._write_csproj(tmp_path / "Sub" / "B.csproj", "BroMakerLib", namespaced=True)
        deps = detect_dependencies_from_csproj(str(tmp_path))
        assert deps == [deps_map["UMM"], deps_map["BroMaker"]]

    def test_no_references_found(self, tmp_path, deps_map):
        self._write_csproj(tmp_path / "Proj.csproj", "Assembly-CSharp", namespaced=True)
        assert detect_dependencies_from_csproj(str(tmp_path)) == [deps_map["UMM"]]

    def test_ignores_csproj_deeper_than_two_levels(self, tmp_path, deps_map):
        self._write_csproj(tmp_path / "a" / "b" / "c" / "Deep.csproj", "RocketLib", namespaced=True)
        assert detect_dependencies_from_csproj(str(tmp_path)) == [deps_map["UMM"]]

    def test_finds_csproj_two_levels_down(self, tmp_path, deps_map):
        self._write_csproj(tmp_path / "a" / "b" / "Deep.csproj", "RocketLib", namespaced=True)
        deps = detect_dependencies_from_csproj(str(tmp_path))
        assert deps == [deps_map["UMM"], deps_map["RocketLib"]]

    def test_both_libraries_no_duplicates(self, tmp_path, deps_map):
        self._write_csproj(tmp_path / "A.csproj", "RocketLib", namespaced=True)
        self._write_csproj(tmp_path / "B.csproj", "RocketLib", namespaced=False)
        self._write_csproj(tmp_path / "Sub" / "C.csproj", "BroMakerLib", namespaced=True)
        deps = detect_dependencies_from_csproj(str(tmp_path))
        assert deps == [deps_map["UMM"], deps_map["RocketLib"], deps_map["BroMaker"]]


def _write_cache(versions, fallbacks, age_seconds=0, schema=CACHE_SCHEMA):
    cache_file = get_cache_file()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": time.time() - age_seconds,
        "versions": versions,
        "fallbacks": fallbacks,
    }
    if schema is not None:
        payload["schema"] = schema
    cache_file.write_text(json.dumps(payload), encoding="utf-8")
    return cache_file


def _read_cache():
    with open(get_cache_file(), encoding="utf-8") as f:
        return json.load(f)


ALL_PACKAGES = sorted(THUNDERSTORE_PACKAGES.keys())


class TestGetDependencyVersions:
    @pytest.fixture
    def fetch_calls(self, monkeypatch):
        """Record fetch calls; the returned dict maps package -> version to serve."""
        calls = []
        results = {}

        def fake_fetch(namespace, package):
            calls.append(package)
            return results.get(package)

        monkeypatch.setattr(thunderstore, "fetch_thunderstore_version", fake_fetch)
        return calls, results

    def test_fresh_cache_without_fallbacks_skips_fetch(self, fetch_calls):
        calls, _ = fetch_calls
        cached = {name: "9.9.9" for name in ALL_PACKAGES}
        _write_cache(cached, [])

        assert get_dependency_versions() == cached
        assert calls == []

    def test_recent_cache_with_fallbacks_skips_fetch(self, fetch_calls):
        calls, results = fetch_calls
        cached = {name: "9.9.9" for name in ALL_PACKAGES}
        results.update({THUNDERSTORE_PACKAGES[n][1]: "1.2.3" for n in ALL_PACKAGES})
        _write_cache(cached, ["RocketLib"], age_seconds=60)

        assert get_dependency_versions() == cached
        assert calls == []

    def test_partial_cache_never_short_circuits(self, fetch_calls):
        calls, results = fetch_calls
        partial = {name: "9.9.9" for name in ALL_PACKAGES if name != "RocketLib"}
        results.update({THUNDERSTORE_PACKAGES[n][1]: "1.2.3" for n in ALL_PACKAGES})
        _write_cache(partial, [], age_seconds=0)

        assert get_dependency_versions() == {name: "1.2.3" for name in ALL_PACKAGES}
        assert len(calls) == len(ALL_PACKAGES)

        _write_cache(partial, ["UMM"], age_seconds=0)
        calls.clear()
        assert get_dependency_versions() == {name: "1.2.3" for name in ALL_PACKAGES}
        assert len(calls) == len(ALL_PACKAGES)

    def test_cache_with_fallbacks_refetches_after_retry_interval(self, fetch_calls):
        calls, results = fetch_calls
        cached = {name: "9.9.9" for name in ALL_PACKAGES}
        results.update({THUNDERSTORE_PACKAGES[n][1]: "1.2.3" for n in ALL_PACKAGES})
        _write_cache(cached, ["RocketLib"], age_seconds=FETCH_RETRY_INTERVAL + 60)

        versions = get_dependency_versions()
        assert sorted(calls) == sorted(THUNDERSTORE_PACKAGES[n][1] for n in ALL_PACKAGES)
        assert versions == {name: "1.2.3" for name in ALL_PACKAGES}

    def test_stale_cache_refetches(self, fetch_calls):
        calls, results = fetch_calls
        results.update({THUNDERSTORE_PACKAGES[n][1]: "1.2.3" for n in ALL_PACKAGES})
        _write_cache({name: "9.9.9" for name in ALL_PACKAGES}, [], age_seconds=CACHE_DURATION + 1)

        assert get_dependency_versions() == {name: "1.2.3" for name in ALL_PACKAGES}
        assert calls

    def test_failed_fetch_prefers_prior_live_values(self, fetch_calls):
        cached = {name: "9.9.9" for name in ALL_PACKAGES}
        _write_cache(cached, [], age_seconds=CACHE_DURATION + 1)

        assert get_dependency_versions() == cached
        cache_data = _read_cache()
        assert cache_data["versions"] == cached
        assert sorted(cache_data["fallbacks"]) == ALL_PACKAGES

    def test_failed_fetch_reuses_values_carried_forward_as_fallbacks(self, fetch_calls):
        cached = {name: "9.9.9" for name in ALL_PACKAGES}
        _write_cache(cached, ["RocketLib"], age_seconds=FETCH_RETRY_INTERVAL + 60)

        assert get_dependency_versions() == cached
        assert sorted(_read_cache()["fallbacks"]) == ALL_PACKAGES

    def test_failed_fetch_without_cache_raises(self, fetch_calls):
        get_cache_file().unlink()

        with pytest.raises(DependencyVersionsUnavailable) as excinfo:
            get_dependency_versions()
        assert "bt deps --refresh" in str(excinfo.value)
        assert not get_cache_file().exists()

    def test_partial_fetch_failure_without_cached_value_raises(self, fetch_calls):
        _, results = fetch_calls
        get_cache_file().unlink()
        results.update({
            THUNDERSTORE_PACKAGES[n][1]: "5.0.0" for n in ALL_PACKAGES if n != "RocketLib"
        })

        with pytest.raises(DependencyVersionsUnavailable) as excinfo:
            get_dependency_versions()
        assert excinfo.value.packages == ["RocketLib"]

    def test_cache_without_current_schema_is_ignored(self, fetch_calls):
        _write_cache({name: "9.9.9" for name in ALL_PACKAGES}, [], schema=None)

        with pytest.raises(DependencyVersionsUnavailable):
            get_dependency_versions()

    def test_force_refresh_refetches_fresh_cache(self, fetch_calls):
        calls, results = fetch_calls
        _write_cache({name: "9.9.9" for name in ALL_PACKAGES}, [])
        results.update({THUNDERSTORE_PACKAGES[n][1]: "7.0.0" for n in ALL_PACKAGES})

        assert get_dependency_versions(force_refresh=True) == {name: "7.0.0" for name in ALL_PACKAGES}
        assert calls

    def test_successful_fetch_writes_live_versions(self, fetch_calls):
        _, results = fetch_calls
        get_cache_file().unlink()
        results.update({THUNDERSTORE_PACKAGES[n][1]: "5.0.0" for n in ALL_PACKAGES})

        assert get_dependency_versions() == {name: "5.0.0" for name in ALL_PACKAGES}
        cache_data = _read_cache()
        assert cache_data["versions"] == {name: "5.0.0" for name in ALL_PACKAGES}
        assert cache_data["fallbacks"] == []


class TestFetchThunderstoreVersion:
    def test_returns_none_on_http_exception(self, monkeypatch):
        def boom(*args, **kwargs):
            raise http.client.IncompleteRead(b"")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        assert fetch_thunderstore_version("UMM", "UMM") is None

    def test_returns_none_on_os_error(self, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("connection reset")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        assert fetch_thunderstore_version("UMM", "UMM") is None


@pytest.fixture
def packageable_project(tmp_path, monkeypatch):
    """Build a self-contained mod project ready for do_package()."""
    monkeypatch.setenv("BROFORCE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BROFORCE_TEMPLATES_DIR", str(tmp_path / "templates"))
    monkeypatch.setenv("BROFORCE_REPOS_PARENT", str(tmp_path / "repos"))

    repos_parent = tmp_path / "repos"
    project_dir = repos_parent / "TestRepo" / "MyMod"
    modcontent = project_dir / "_ModContent"
    modcontent.mkdir(parents=True)
    (modcontent / "Info.json").write_text(
        json.dumps({"Id": "MyMod", "Version": "1.0.0"}), encoding="utf-8"
    )
    (modcontent / "MyMod.dll").write_bytes(b"")

    releases = repos_parent / "TestRepo" / "Release"
    releases.mkdir(parents=True)
    (releases / "manifest.json").write_text(json.dumps({
        "name": "MyMod",
        "author": "Tester",
        "version_number": "1.0.0",
        "website_url": "",
        "description": "Test",
        "dependencies": [get_dependencies()["UMM"]],
    }), encoding="utf-8")
    (releases / "README.md").write_text("# MyMod", encoding="utf-8")
    (releases / "icon.png").write_bytes(b"png")
    changelog = releases / "Changelog.md"
    changelog.write_text("## v1.0.0 (unreleased)\n- Initial release\n", encoding="utf-8")

    project = Project(
        name="MyMod",
        repo="TestRepo",
        subdir="MyMod",
        repos_parent=str(repos_parent),
    )
    return project, changelog


class TestPackageChangelogMarker:
    def test_marker_stripped_after_successful_package(self, packageable_project):
        project, changelog = packageable_project
        do_package(project, non_interactive=True)

        content = changelog.read_text(encoding="utf-8")
        assert "(unreleased)" not in content
        assert "## v1.0.0" in content

        zip_path = os.path.join(project.get_releases_path(), "Tester-MyMod-1.0.0.zip")
        assert os.path.exists(zip_path)

    def test_marker_kept_when_zip_fails(self, packageable_project, monkeypatch):
        project, changelog = packageable_project
        original = changelog.read_text(encoding="utf-8")

        def boom(*args, **kwargs):
            raise RuntimeError("zip failed")

        monkeypatch.setattr(zipfile, "ZipFile", boom)

        with pytest.raises(RuntimeError):
            do_package(project, non_interactive=True)

        assert changelog.read_text(encoding="utf-8") == original

    def test_keep_unreleased_preserves_marker(self, packageable_project):
        project, changelog = packageable_project
        do_package(project, non_interactive=True, keep_unreleased=True)

        assert "(unreleased)" in changelog.read_text(encoding="utf-8")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class TestPackageVersionAuthority:
    def test_changelog_wins_over_lower_versions(self, packageable_project):
        project, changelog = packageable_project
        changelog.write_text("## v1.2.0 (unreleased)\n- Feature\n", encoding="utf-8")
        releases = project.get_releases_path()
        info_path = os.path.join(project.project_dir, "_ModContent", "Info.json")

        do_package(project, non_interactive=True)

        assert _read_json(os.path.join(releases, "manifest.json"))["version_number"] == "1.2.0"
        assert _read_json(info_path)["Version"] == "1.2.0"
        assert os.path.exists(os.path.join(releases, "Tester-MyMod-1.2.0.zip"))

    def test_highest_version_wins_with_allow_outdated(self, packageable_project, capsys):
        project, changelog = packageable_project
        changelog.write_text("## v1.0.0 (unreleased)\n- Fix\n", encoding="utf-8")
        releases = project.get_releases_path()
        manifest_path = os.path.join(releases, "manifest.json")
        info_path = os.path.join(project.project_dir, "_ModContent", "Info.json")
        _write_json(manifest_path, dict(_read_json(manifest_path), version_number="2.0.0"))
        _write_json(info_path, dict(_read_json(info_path), Version="3.0.0"))

        do_package(project, non_interactive=True, allow_outdated_changelog=True)

        output = capsys.readouterr().out
        assert "Changelog.md is out of date" in output
        assert "Highest version found: 3.0.0 (from Info.json)" in output
        assert _read_json(manifest_path)["version_number"] == "3.0.0"
        assert _read_json(info_path)["Version"] == "3.0.0"
        assert os.path.exists(os.path.join(releases, "Tester-MyMod-3.0.0.zip"))

    def test_outdated_changelog_errors_without_flag(self, packageable_project, capsys):
        project, changelog = packageable_project
        changelog.write_text("## v1.0.0 (unreleased)\n- Fix\n", encoding="utf-8")
        manifest_path = os.path.join(project.get_releases_path(), "manifest.json")
        _write_json(manifest_path, dict(_read_json(manifest_path), version_number="2.0.0"))

        with pytest.raises(typer.Exit) as excinfo:
            do_package(project, non_interactive=True)
        assert excinfo.value.exit_code == 1

        output = capsys.readouterr().out
        assert "Changelog.md is out of date" in output
        assert "Changelog version: 1.0.0" in output
        assert "Highest version found: 2.0.0 (from manifest.json)" in output
        assert "--allow-outdated-changelog" in output
        assert _read_json(manifest_path)["version_number"] == "2.0.0"

    def test_version_override_wins(self, packageable_project, capsys):
        project, changelog = packageable_project
        changelog.write_text("## v1.0.0 (unreleased)\n- Fix\n", encoding="utf-8")
        releases = project.get_releases_path()
        manifest_path = os.path.join(releases, "manifest.json")
        info_path = os.path.join(project.project_dir, "_ModContent", "Info.json")
        _write_json(manifest_path, dict(_read_json(manifest_path), version_number="2.0.0"))
        _write_json(info_path, dict(_read_json(info_path), Version="3.0.0"))

        do_package(project, version_override="1.1.0", non_interactive=True)

        output = capsys.readouterr().out
        assert "Using version override: 1.1.0" in output
        assert "out of date" not in output
        assert _read_json(manifest_path)["version_number"] == "1.1.0"
        assert _read_json(info_path)["Version"] == "1.1.0"
        assert os.path.exists(os.path.join(releases, "Tester-MyMod-1.1.0.zip"))

    def test_unparsable_manifest_version_warns_and_is_ignored(self, packageable_project, capsys):
        project, changelog = packageable_project
        changelog.write_text("## v1.5.0 (unreleased)\n- Fix\n", encoding="utf-8")
        releases = project.get_releases_path()
        manifest_path = os.path.join(releases, "manifest.json")
        _write_json(manifest_path, dict(_read_json(manifest_path), version_number="not-a-version"))

        do_package(project, non_interactive=True)

        output = capsys.readouterr().out
        assert "manifest.json version 'not-a-version' is not a numeric version" in output
        assert "out of date" not in output
        assert _read_json(manifest_path)["version_number"] == "1.5.0"
        assert os.path.exists(os.path.join(releases, "Tester-MyMod-1.5.0.zip"))


@pytest.fixture
def packageable_bro(tmp_path, monkeypatch):
    """Build a self-contained bro project ready for do_package()."""
    monkeypatch.setenv("BROFORCE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BROFORCE_TEMPLATES_DIR", str(tmp_path / "templates"))
    monkeypatch.setenv("BROFORCE_REPOS_PARENT", str(tmp_path / "repos"))

    repos_parent = tmp_path / "repos"
    project_dir = repos_parent / "TestRepo" / "MyBro"
    modcontent = project_dir / "_ModContent"
    modcontent.mkdir(parents=True)
    mod_json = modcontent / "MyBro.mod.json"
    mod_json.write_text(
        json.dumps({"Name": "MyBro", "Version": "1.0.0", "BroMakerVersion": "2.6.1"}),
        encoding="utf-8",
    )
    (modcontent / "MyBro.dll").write_bytes(b"")

    releases = repos_parent / "TestRepo" / "Release"
    releases.mkdir(parents=True)
    (releases / "manifest.json").write_text(json.dumps({
        "name": "MyBro",
        "author": "Tester",
        "version_number": "1.0.0",
        "website_url": "",
        "description": "Test",
        "dependencies": [get_dependencies()["UMM"]],
    }), encoding="utf-8")
    (releases / "README.md").write_text("# MyBro", encoding="utf-8")
    (releases / "icon.png").write_bytes(b"png")
    (releases / "Changelog.md").write_text(
        "## v1.0.0 (unreleased)\n- Initial release\n", encoding="utf-8"
    )

    project = Project(
        name="MyBro",
        repo="TestRepo",
        subdir="MyBro",
        repos_parent=str(repos_parent),
    )
    return project, mod_json


class TestPackageBroMakerVersion:
    def test_outdated_bromaker_version_warns_without_rewriting(self, packageable_bro, capsys):
        project, mod_json = packageable_bro
        latest = get_dependency_versions()["BroMaker"]

        do_package(project, non_interactive=True)

        output = capsys.readouterr().out
        assert "BroMakerVersion" in output
        assert "2.6.1" in output
        assert latest in output
        assert _read_json(mod_json)["BroMakerVersion"] == "2.6.1"

    def test_matching_bromaker_version_is_silent(self, packageable_bro, capsys):
        project, mod_json = packageable_bro
        data = _read_json(mod_json)
        data["BroMakerVersion"] = get_dependency_versions()["BroMaker"]
        mod_json.write_text(json.dumps(data), encoding="utf-8")

        do_package(project, non_interactive=True)

        assert "BroMakerVersion" not in capsys.readouterr().out

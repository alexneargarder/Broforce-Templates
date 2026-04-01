"""Thunderstore API integration and packaging."""
import filecmp
import fnmatch
import json
import os
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional

import questionary
import typer

from .colors import Colors, CHECK, WARNING_ICON, ARROW
from .config import get_cache_file, get_defaults, get_release_dir
from .paths import ensure_dir, get_cache_dir, get_templates_dir
from .project import Project, detect_project_type, find_mod_metadata_dir
from .project_types import PROJECT_TYPES
from .templates import copyanything

try:
    import urllib.request
    import urllib.error
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

FALLBACK_DEPENDENCY_VERSIONS = {
    'UMM': '1.1.0',
    'RocketLib': '2.4.2',
    'BroMaker': '2.6.1',
    'DresserMod': '1.2.1',
}

THUNDERSTORE_PACKAGES = {
    'UMM': ('UMM', 'UMM'),
    'RocketLib': ('RocketLib', 'RocketLib'),
    'BroMaker': ('BroMaker', 'BroMaker'),
    'DresserMod': ('Gorzontrok', 'DresserMod'),
}

CACHE_DURATION = 24 * 60 * 60


def fetch_thunderstore_version(namespace: str, package_name: str) -> Optional[str]:
    """Fetch latest version from Thunderstore API."""
    if not HAS_URLLIB:
        return None

    url = f"https://thunderstore.io/api/experimental/package/{namespace}/{package_name}/"

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'broforce-tools/1.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('latest', {}).get('version_number', None)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return None


def get_dependency_versions() -> dict[str, str]:
    """Get dependency versions, fetching from Thunderstore API with caching."""
    cache_file = get_cache_file()

    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            cache_time = cache_data.get('timestamp', 0)
            if time.time() - cache_time < CACHE_DURATION:
                versions = cache_data.get('versions', {})
                if versions and set(versions.keys()) == set(THUNDERSTORE_PACKAGES.keys()):
                    return versions
        except (json.JSONDecodeError, OSError):
            pass

    versions = {}
    fallbacks = []
    for dep_name, (namespace, package) in THUNDERSTORE_PACKAGES.items():
        version = fetch_thunderstore_version(namespace, package)
        if version:
            versions[dep_name] = version
        else:
            versions[dep_name] = FALLBACK_DEPENDENCY_VERSIONS[dep_name]
            fallbacks.append(dep_name)

    try:
        ensure_dir(get_cache_dir())
        cache_data = {
            'timestamp': time.time(),
            'versions': versions,
            'fallbacks': fallbacks,
        }
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)
    except OSError:
        pass

    return versions


def get_dependencies() -> dict[str, str]:
    """Get dependency strings in Thunderstore format."""
    versions = get_dependency_versions()
    return {
        name: f"{namespace}-{package}-{versions[name]}"
        for name, (namespace, package) in THUNDERSTORE_PACKAGES.items()
    }


def validate_package_name(name: str) -> tuple[bool, str]:
    """Validate package name against Thunderstore rules."""
    if len(name) > 128:
        return False, f"Name too long ({len(name)} chars, max 128)"

    if not re.match(r'^[a-zA-Z0-9_]+$', name):
        return False, "Name must contain only alphanumeric characters and underscores"

    return True, "OK"


def sanitize_package_name(name: str) -> str:
    """Convert project name to valid package name."""
    sanitized = name.replace(' ', '_')
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '', sanitized)
    return sanitized


def detect_dependencies_from_csproj(project_path: str) -> list[str]:
    """Detect RocketLib and BroMaker dependencies from .csproj file."""
    dependencies_map = get_dependencies()
    dependencies = [dependencies_map['UMM']]

    csproj_files = []
    for root, dirs, files in os.walk(project_path):
        depth = root[len(project_path):].count(os.sep)
        if depth > 2:
            continue
        for file in files:
            if file.endswith('.csproj'):
                csproj_files.append(os.path.join(root, file))

    if not csproj_files:
        return dependencies

    csproj_path = csproj_files[0]

    try:
        tree = ET.parse(csproj_path)
        root = tree.getroot()

        ns = {'msbuild': 'http://schemas.microsoft.com/developer/msbuild/2003'}

        for ref in root.findall('.//msbuild:Reference', ns):
            include = ref.get('Include', '')
            if 'RocketLib' in include:
                dependencies.append(dependencies_map['RocketLib'])
                break

        if dependencies_map['RocketLib'] not in dependencies:
            for ref in root.findall('.//Reference'):
                include = ref.get('Include', '')
                if 'RocketLib' in include:
                    dependencies.append(dependencies_map['RocketLib'])
                    break

        for ref in root.findall('.//msbuild:Reference', ns):
            include = ref.get('Include', '')
            if 'BroMakerLib' in include:
                dependencies.append(dependencies_map['BroMaker'])
                break

        if dependencies_map['BroMaker'] not in dependencies:
            for ref in root.findall('.//Reference'):
                include = ref.get('Include', '')
                if 'BroMakerLib' in include:
                    dependencies.append(dependencies_map['BroMaker'])
                    break

    except Exception as e:
        print(f"{Colors.WARNING}Warning: Could not parse .csproj: {e}{Colors.ENDC}")

    return dependencies


def find_changelog(releases_path: str) -> Optional[str]:
    """Find changelog file, checking both Changelog.md and CHANGELOG.md."""
    for name in ['Changelog.md', 'CHANGELOG.md']:
        path = os.path.join(releases_path, name)
        if os.path.exists(path):
            return path
    return None


def get_version_from_changelog(changelog_path: str) -> Optional[str]:
    """Parse version from Changelog.md or CHANGELOG.md."""
    version, _, _ = get_latest_version_entries(changelog_path)
    return version


def has_unreleased_version(changelog_path: str) -> tuple[bool, Optional[str]]:
    """Check if changelog has (unreleased) marker on first version.

    Returns:
        Tuple of (is_unreleased, version_string or None)
    """
    version, is_unreleased, _ = get_latest_version_entries(changelog_path)
    if is_unreleased:
        return (True, version)
    return (False, None)


def get_unreleased_entries(changelog_path: str) -> tuple[Optional[str], list[str]]:
    """Get the unreleased version and its entries.

    Returns:
        Tuple of (version or None, list of entry lines)
    """
    version, is_unreleased, entries = get_latest_version_entries(changelog_path)
    if is_unreleased:
        return (version, entries)
    return (None, [])


def get_latest_version_entries(changelog_path: str) -> tuple[Optional[str], bool, list[str]]:
    """Get the latest version (released or unreleased) and its entries.

    Returns:
        Tuple of (version or None, is_unreleased, list of entry lines)
    """
    if not os.path.exists(changelog_path):
        return (None, False, [])

    try:
        with open(changelog_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Match first version header (with optional unreleased marker)
        match = re.search(
            r'##\s*v?(\d+\.\d+\.\d+)(.*?)\n(.*?)(?=\n##\s|$)',
            content,
            re.DOTALL
        )
        if not match:
            return (None, False, [])

        version = match.group(1)
        header_rest = match.group(2).lower()
        is_unreleased = 'unreleased' in header_rest
        entries_text = match.group(3).strip()

        entries = []
        for line in entries_text.split('\n'):
            line = line.strip()
            if line and line.startswith('-'):
                entries.append(line)

        return (version, is_unreleased, entries)
    except Exception:
        return (None, False, [])


def add_changelog_entry(changelog_path: str, entry: str) -> bool:
    """Add a bullet point entry to the unreleased section.

    Inserts '- {entry}' after the '## vX.X.X (unreleased)' header.
    Returns True on success.
    """
    is_unreleased, _ = has_unreleased_version(changelog_path)
    if not is_unreleased:
        return False

    try:
        with open(changelog_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if line.startswith('##') and 'unreleased' in line.lower():
                lines.insert(i + 1, f"- {entry}\n")
                break
        else:
            return False

        with open(changelog_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

        return True
    except Exception:
        return False


def find_dll_in_modcontent(modcontent_path: str) -> Optional[str]:
    """Find DLL file in mod metadata folder (_Mod or _ModContent)."""
    if not os.path.exists(modcontent_path):
        return None

    for file in os.listdir(modcontent_path):
        if file.endswith('.dll'):
            return os.path.join(modcontent_path, file)

    return None


def _find_metadata_file(dir_path: str, patterns: list[str]) -> Optional[str]:
    """Find first file matching any of the metadata patterns in a directory."""
    try:
        for f in os.listdir(dir_path):
            for pattern in patterns:
                if fnmatch.fnmatch(f, pattern):
                    return os.path.join(dir_path, f)
    except (OSError, FileNotFoundError):
        pass
    return None


def get_version_from_info_json(modcontent_path: str, project_type: str) -> Optional[str]:
    """Get version from project metadata file (Info.json, .mod.json, etc.)."""
    if not os.path.exists(modcontent_path):
        return None

    type_info = PROJECT_TYPES.get(project_type)
    if not type_info or not type_info["version_file_label"]:
        return None

    version_file = _find_metadata_file(modcontent_path, type_info["metadata_patterns"])
    if not version_file:
        return None

    try:
        with open(version_file, 'r', encoding='utf-8') as f:
            version_data = json.load(f)
        return version_data.get('Version', None)
    except Exception:
        return None


def compare_versions(v1: Optional[str], v2: Optional[str]) -> int:
    """Compare semantic versions. Returns 1 if v1 > v2, -1 if v1 < v2, 0 if equal."""
    if not v1:
        return -1
    if not v2:
        return 1

    try:
        parts1 = [int(x) for x in v1.split('.')]
        parts2 = [int(x) for x in v2.split('.')]

        while len(parts1) < len(parts2):
            parts1.append(0)
        while len(parts2) < len(parts1):
            parts2.append(0)

        for p1, p2 in zip(parts1, parts2):
            if p1 > p2:
                return 1
            elif p1 < p2:
                return -1
        return 0
    except (ValueError, AttributeError):
        return 0


def sync_version_file(modcontent_path: str, project_type: str, target_version: str) -> tuple[bool, Optional[str]]:
    """Sync version in metadata file (Info.json, .mod.json, etc.) with target version."""
    if not os.path.exists(modcontent_path):
        return (False, None)

    type_info = PROJECT_TYPES.get(project_type)
    if not type_info or not type_info["version_file_label"]:
        return (False, None)

    version_file = _find_metadata_file(modcontent_path, type_info["metadata_patterns"])
    if not version_file:
        return (False, None)

    try:
        with open(version_file, 'r', encoding='utf-8') as f:
            version_data = json.load(f)

        current_version = version_data.get('Version', '')

        if current_version == target_version:
            return (False, version_file)

        version_data['Version'] = target_version

        with open(version_file, 'w', encoding='utf-8') as f:
            json.dump(version_data, f, indent=2)

        return (True, version_file)

    except Exception as e:
        print(f"{Colors.WARNING}Warning: Could not sync version file: {e}{Colors.ENDC}")
        return (False, version_file)


def clear_cache() -> bool:
    """Clear the dependency cache file."""
    cache_file = get_cache_file()
    if cache_file.exists():
        try:
            cache_file.unlink()
            return True
        except OSError:
            return False
    return False


def check_missing_required(missing: list[tuple[str, str]]) -> None:
    """Error if any required values are missing in non-interactive mode."""
    if missing:
        print(f"{Colors.FAIL}Error: Non-interactive mode requires the following:{Colors.ENDC}")
        for flag, desc in missing:
            print(f"  {flag}: {desc}")
        print(f"\nRun without --non-interactive for interactive prompts, or provide the missing options.")
        raise typer.Exit(1)


def do_init_thunderstore(
    project: Project,
    namespace: Optional[str] = None,
    description: Optional[str] = None,
    website_url: Optional[str] = None,
    package_name_override: Optional[str] = None,
    non_interactive: bool = False,
) -> None:
    """Initialize Thunderstore metadata for an existing project."""
    project_name = project.name
    print(f"{Colors.HEADER}Initializing Thunderstore metadata for '{project_name}'{Colors.ENDC}")

    template_dir = get_templates_dir()

    project_path = project.project_dir
    releases_path = project.get_releases_path(create=True)

    if not releases_path:
        print(f"{Colors.FAIL}Error: Could not find releases path for '{project_name}'{Colors.ENDC}")
        raise typer.Exit(1)

    print(f"{Colors.BLUE}Found project in: {project.repo}{Colors.ENDC}")

    project_type = detect_project_type(project_path)
    if not project_type:
        print(f"{Colors.FAIL}Error: Could not detect project type (no metadata folder or missing Info.json/*.mod.json){Colors.ENDC}")
        raise typer.Exit(1)

    print(f"{Colors.BLUE}Detected project type: {project_type}{Colors.ENDC}")

    defaults = get_defaults()
    default_namespace = defaults.get('namespace', '')
    default_website = defaults.get('website_url', '')

    missing: list[tuple[str, str]] = []

    if namespace is not None:
        final_namespace = namespace
    elif non_interactive:
        if default_namespace:
            final_namespace = default_namespace
        else:
            missing.append(("--namespace / -n", "Thunderstore namespace/author"))
            final_namespace = ""
    else:
        print(f"\n{Colors.HEADER}Enter Thunderstore package information:{Colors.ENDC}")
        if default_namespace:
            final_namespace = questionary.text(
                f"Namespace/Author [{default_namespace}]:",
                default=default_namespace,
                validate=lambda text: validate_package_name(text)[0] if text else True
            ).ask()
            if final_namespace is None:
                raise typer.Exit()
            if not final_namespace:
                final_namespace = default_namespace
        else:
            final_namespace = questionary.text(
                "Namespace/Author (e.g., AlexNeargarder):",
                validate=lambda text: validate_package_name(text)[0]
            ).ask()
            if final_namespace is None or not final_namespace:
                raise typer.Exit()

    suggested_name = sanitize_package_name(project_name)
    if package_name_override is not None:
        final_package_name = package_name_override
    elif non_interactive:
        final_package_name = suggested_name
    else:
        final_package_name = questionary.text(
            f"Package name [{suggested_name}]:",
            default=suggested_name,
            validate=lambda text: validate_package_name(text)[0] if text else True
        ).ask()
        if final_package_name is None:
            raise typer.Exit()
        if not final_package_name:
            final_package_name = suggested_name

    if description is not None:
        final_description = description
    elif non_interactive:
        missing.append(("--description / -d", "Package description (max 250 chars)"))
        final_description = ""
    else:
        final_description = questionary.text("Description (max 250 chars):").ask()
        if final_description is None:
            raise typer.Exit()

    if len(final_description) > 250:
        print(f"{Colors.WARNING}Warning: Description truncated to 250 characters{Colors.ENDC}")
        final_description = final_description[:250]

    if website_url is not None:
        final_website_url = website_url
    elif non_interactive:
        final_website_url = default_website
    else:
        if default_website:
            final_website_url = questionary.text(
                f"Website/GitHub URL [{default_website}]:",
                default=default_website
            ).ask()
            if final_website_url is None:
                raise typer.Exit()
            if not final_website_url:
                final_website_url = default_website
        else:
            final_website_url = questionary.text("Website/GitHub URL:").ask()
            if final_website_url is None:
                raise typer.Exit()
            final_website_url = final_website_url or ""

    check_missing_required(missing)

    os.makedirs(releases_path, exist_ok=True)

    changelog_path = find_changelog(releases_path)
    if not changelog_path:
        changelog_path = os.path.join(releases_path, 'Changelog.md')
        print(f"{Colors.WARNING}Changelog not found, creating default{Colors.ENDC}")
        with open(changelog_path, 'w', encoding='utf-8') as f:
            f.write('## v1.0.0 (unreleased)\n- Initial release\n')

    detected_deps = detect_dependencies_from_csproj(project_path)
    dependencies = get_dependencies()

    type_info = PROJECT_TYPES.get(project_type, {})
    for dep_key in type_info.get("extra_dependencies", []):
        dep_str = dependencies.get(dep_key)
        if dep_str and dep_str not in detected_deps:
            detected_deps.append(dep_str)

    if len(detected_deps) > 1:
        print(f"{Colors.BLUE}Detected dependencies:{Colors.ENDC}")
        for dep in detected_deps:
            if dep != dependencies['UMM']:
                print(f"  - {dep}")

    manifest_path = os.path.join(releases_path, 'manifest.json')
    manifest_data = {
        "name": final_package_name,
        "author": final_namespace,
        "version_number": "1.0.0",
        "website_url": final_website_url,
        "description": final_description,
        "dependencies": detected_deps
    }

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f, indent=2)

    print(f"{Colors.GREEN}Created manifest.json{Colors.ENDC}")

    readme_template = os.path.join(template_dir, 'ThunderstorePackage', 'README.md')
    readme_dest = os.path.join(releases_path, 'README.md')

    if os.path.exists(readme_dest):
        print(f"{Colors.BLUE}README.md already exists, skipping{Colors.ENDC}")
    elif os.path.exists(readme_template):
        with open(readme_template, 'r', encoding='utf-8') as f:
            readme_content = f.read()

        readme_content = readme_content.replace('PROJECT_NAME', project_name)
        readme_content = readme_content.replace('DESCRIPTION_PLACEHOLDER', final_description)
        readme_content = readme_content.replace('FEATURES_PLACEHOLDER', '*Describe your mod\'s features here*')
        readme_content = readme_content.replace('WEBSITE_URL', final_website_url)

        with open(readme_dest, 'w', encoding='utf-8') as f:
            f.write(readme_content)

        print(f"{Colors.GREEN}Created README.md{Colors.ENDC}")
    else:
        print(f"{Colors.WARNING}Warning: README template not found at {readme_template}{Colors.ENDC}")

    icon_template = os.path.join(template_dir, 'ThunderstorePackage', 'icon.png')
    icon_dest = os.path.join(releases_path, 'icon.png')

    if os.path.exists(icon_dest):
        print(f"{Colors.BLUE}icon.png already exists, skipping{Colors.ENDC}")
    elif os.path.exists(icon_template):
        shutil.copy(icon_template, icon_dest)
        print(f"{Colors.GREEN}Created icon.png{Colors.ENDC}")
        print(f"{Colors.WARNING}{WARNING_ICON}Replace icon.png with a custom 256x256 image!{Colors.ENDC}")
    else:
        print(f"{Colors.WARNING}Warning: Icon template not found at {icon_template}{Colors.ENDC}")

    print(f"\n{Colors.GREEN}{Colors.BOLD}{CHECK} Thunderstore metadata initialized!{Colors.ENDC}")
    print(f"{Colors.CYAN}Location:{Colors.ENDC} {releases_path}")
    print(f"\n{Colors.CYAN}Files created:{Colors.ENDC}")
    print(f"  - manifest.json")
    print(f"  - README.md (customize for Thunderstore)")
    print(f"  - icon.png ({WARNING_ICON}placeholder - replace with 256x256 custom icon!)")
    print(f"\n{Colors.CYAN}Next steps:{Colors.ENDC}")
    print(f"  1. Edit {releases_path}/README.md")
    print(f"  2. Replace icon.png with custom icon")
    print(f"  3. Review manifest.json dependencies")
    print(f"  4. Run: bt package \"{project_name}\"")


def _copy_to_release_dir(zip_path: str, namespace: str, package_name: str) -> None:
    """Copy a packaged zip to the central release directory, if configured."""
    release_dir = get_release_dir()
    if not release_dir:
        return

    try:
        os.makedirs(release_dir, exist_ok=True)

        prefix = f"{namespace}-{package_name}-"
        for existing in os.listdir(release_dir):
            if existing.startswith(prefix) and existing.endswith('.zip'):
                os.remove(os.path.join(release_dir, existing))

        dest_path = os.path.join(release_dir, os.path.basename(zip_path))
        shutil.copy2(zip_path, dest_path)
        print(f"{Colors.GREEN}Copied to release dir:{Colors.ENDC} {dest_path}")
    except OSError as e:
        print(f"{Colors.WARNING}Warning: Could not copy to release dir: {e}{Colors.ENDC}")


def do_package(
    project: Project,
    version_override: Optional[str] = None,
    non_interactive: bool = False,
    allow_outdated_changelog: bool = False,
    overwrite: bool = False,
    update_deps: Optional[bool] = None,
    add_missing_deps: Optional[bool] = None,
    keep_unreleased: bool = False,
) -> None:
    """Create Thunderstore package for an existing project."""
    template_dir = get_templates_dir()
    project_name = project.name
    project_path = project.project_dir
    releases_path = project.get_releases_path(create=False)

    if not releases_path:
        print(f"{Colors.FAIL}Error: Could not find releases path for '{project_name}'{Colors.ENDC}")
        raise typer.Exit(1)

    manifest_path = os.path.join(releases_path, 'manifest.json')
    readme_path = os.path.join(releases_path, 'README.md')
    icon_path = os.path.join(releases_path, 'icon.png')
    changelog_path = find_changelog(releases_path)

    if not os.path.exists(manifest_path):
        print(f"{Colors.FAIL}Error: manifest.json not found{Colors.ENDC}")
        print(f"Run: bt init-thunderstore \"{project_name}\"")
        raise typer.Exit(1)

    if not os.path.exists(readme_path):
        print(f"{Colors.FAIL}Error: README.md not found{Colors.ENDC}")
        raise typer.Exit(1)

    if not os.path.exists(icon_path):
        print(f"{Colors.FAIL}Error: icon.png not found{Colors.ENDC}")
        raise typer.Exit(1)

    if not changelog_path:
        print(f"{Colors.FAIL}Error: Changelog.md or CHANGELOG.md not found{Colors.ENDC}")
        raise typer.Exit(1)

    project_type = detect_project_type(project_path)
    if not project_type:
        print(f"{Colors.FAIL}Error: Could not detect project type{Colors.ENDC}")
        raise typer.Exit(1)

    metadata_dir = find_mod_metadata_dir(project_path)
    if not metadata_dir:
        print(f"{Colors.FAIL}Error: Could not find metadata folder{Colors.ENDC}")
        raise typer.Exit(1)

    type_info = PROJECT_TYPES.get(project_type, {})
    if type_info.get("has_code", True):
        dll_path = find_dll_in_modcontent(metadata_dir)

        if not dll_path:
            print(f"{Colors.FAIL}Error: No DLL found in metadata folder{Colors.ENDC}")
            print(f"Build the project first")
            raise typer.Exit(1)

    icon_template = os.path.join(template_dir, 'ThunderstorePackage', 'icon.png')
    if os.path.exists(icon_template) and filecmp.cmp(icon_path, icon_template, shallow=False):
        print(f"{Colors.WARNING}{WARNING_ICON}Warning: Using placeholder icon{Colors.ENDC}")

    changelog_name = os.path.basename(changelog_path)

    if version_override:
        version = version_override
        print(f"{Colors.CYAN}Using version override: {version}{Colors.ENDC}")
    else:
        changelog_version = get_version_from_changelog(changelog_path)
        manifest_version = None
        info_version = None

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data_temp = json.load(f)
            manifest_version = manifest_data_temp.get('version_number', None)
        except Exception:
            pass

        info_version = get_version_from_info_json(metadata_dir, project_type)

        versions = {
            changelog_name: changelog_version,
            'manifest.json': manifest_version,
            (type_info.get("version_file_label") or "metadata"): info_version
        }

        valid_versions = {k: v for k, v in versions.items() if v is not None}

        if not valid_versions:
            print(f"{Colors.FAIL}Error: Could not find version in any file{Colors.ENDC}")
            print(f"Expected version in {changelog_name}, manifest.json, or Info.json/.mod.json")
            raise typer.Exit(1)

        highest_version = None
        highest_source = None
        for source, ver in valid_versions.items():
            if highest_version is None or compare_versions(ver, highest_version) > 0:
                highest_version = ver
                highest_source = source

        version = highest_version

        print(f"{Colors.CYAN}Package version: {version}{Colors.ENDC}")

        if changelog_version and compare_versions(changelog_version, version) < 0:
            print(f"\n{Colors.WARNING}Warning: {changelog_name} is out of date!{Colors.ENDC}")
            print(f"{Colors.CYAN}Changelog version: {changelog_version}{Colors.ENDC}")
            print(f"{Colors.CYAN}Highest version found: {version} (from {highest_source}){Colors.ENDC}")
            print(f"\n{Colors.WARNING}Did you forget to update {changelog_name}?{Colors.ENDC}")

            if non_interactive:
                if not allow_outdated_changelog:
                    print(f"\n{Colors.FAIL}Error: Changelog is outdated. Use --allow-outdated-changelog to package anyway.{Colors.ENDC}")
                    raise typer.Exit(1)
            else:
                continue_package = questionary.confirm(
                    f"Continue packaging with version {version}?",
                    default=False
                ).ask()

                if continue_package is None or not continue_package:
                    print(f"\n{Colors.CYAN}Packaging cancelled.{Colors.ENDC}")
                    print(f"Update {changelog_name} to version {version} before packaging.")
                    raise typer.Exit()

    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest_data = json.load(f)

    namespace = manifest_data.get('author', 'Unknown')
    package_name = manifest_data.get('name', project_name.replace(' ', '_'))

    if namespace == 'Unknown' or not namespace:
        print(f"\n{Colors.WARNING}Warning: No author/namespace set in manifest.json{Colors.ENDC}")
        print(f"{Colors.CYAN}The author field is used for the package filename and Thunderstore namespace.{Colors.ENDC}")

        if non_interactive:
            print(f"\n{Colors.FAIL}Error: No author set in manifest.json. Edit manifest.json to add an author.{Colors.ENDC}")
            raise typer.Exit(1)

        set_author = questionary.confirm(
            "Set author name now?",
            default=True
        ).ask()

        if set_author is None:
            raise typer.Exit()
        elif set_author:
            namespace = questionary.text(
                "Enter namespace/author (alphanumeric + underscores only):",
                validate=lambda text: validate_package_name(text)[0]
            ).ask()

            if namespace is None:
                raise typer.Exit()

            manifest_data['author'] = namespace
            print(f"{Colors.GREEN}Author set to: {namespace}{Colors.ENDC}")
        else:
            print(f"{Colors.WARNING}Continuing with 'Unknown' as author (package will be named Unknown-{package_name}-{version}.zip){Colors.ENDC}")

    dependencies = get_dependencies()
    current_deps = manifest_data.get('dependencies', [])
    outdated_deps = []
    updated_deps = []

    for dep in current_deps:
        parts = dep.rsplit('-', 1)
        if len(parts) == 2:
            dep_name_part, dep_version = parts
            for dep_key, current_dep_string in dependencies.items():
                if current_dep_string.startswith(dep_name_part + '-'):
                    if dep != current_dep_string:
                        outdated_deps.append((dep, current_dep_string))
                        updated_deps.append(current_dep_string)
                    else:
                        updated_deps.append(dep)
                    break
            else:
                updated_deps.append(dep)
        else:
            updated_deps.append(dep)

    if outdated_deps:
        print(f"\n{Colors.WARNING}Outdated dependencies detected:{Colors.ENDC}")
        for old_dep, new_dep in outdated_deps:
            print(f"  {old_dep} {ARROW} {new_dep}")

        if non_interactive:
            should_update = update_deps if update_deps is not None else True
        else:
            update = questionary.confirm(
                "Update dependencies to latest versions?",
                default=True
            ).ask()

            if update is None:
                raise typer.Exit()
            should_update = update

        if should_update:
            manifest_data['dependencies'] = updated_deps
            print(f"{Colors.GREEN}Dependencies updated{Colors.ENDC}")
        else:
            print(f"{Colors.CYAN}Keeping existing dependency versions{Colors.ENDC}")
    else:
        updated_deps = current_deps

    detected_deps = detect_dependencies_from_csproj(project_path)
    current_dep_set = set(updated_deps if updated_deps else current_deps)
    missing_deps = []

    for dep in detected_deps:
        if dep not in current_dep_set:
            missing_deps.append(dep)

    if missing_deps:
        print(f"\n{Colors.WARNING}Warning: Dependencies detected in .csproj but not in manifest.json:{Colors.ENDC}")
        for dep in missing_deps:
            print(f"  + {dep}")

        if non_interactive:
            should_add = add_missing_deps if add_missing_deps is not None else True
        else:
            add_deps_prompt = questionary.confirm(
                "Add missing dependencies to manifest?",
                default=True
            ).ask()

            if add_deps_prompt is None:
                raise typer.Exit()
            should_add = add_deps_prompt

        if should_add:
            if updated_deps:
                updated_deps.extend(missing_deps)
            else:
                updated_deps = list(current_dep_set) + missing_deps
            manifest_data['dependencies'] = updated_deps
            print(f"{Colors.GREEN}Missing dependencies added{Colors.ENDC}")
        else:
            print(f"{Colors.CYAN}Continuing without adding missing dependencies{Colors.ENDC}")

    old_manifest_version = manifest_data.get('version_number', None)
    manifest_data['version_number'] = version

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f, indent=2)

    if old_manifest_version != version:
        print(f"{Colors.GREEN}Updated manifest.json version to {version}{Colors.ENDC}")
    else:
        print(f"{Colors.BLUE}manifest.json already at version {version}{Colors.ENDC}")

    updated, version_file_path = sync_version_file(metadata_dir, project_type, version)
    if updated:
        version_file_name = os.path.basename(version_file_path)
        print(f"{Colors.GREEN}Updated {version_file_name} version to {version}{Colors.ENDC}")
    elif version_file_path:
        version_file_name = os.path.basename(version_file_path)
        print(f"{Colors.BLUE}{version_file_name} already at version {version}{Colors.ENDC}")
    else:
        label = type_info.get("version_file_label")
        if label:
            print(f"{Colors.WARNING}Warning: Could not find {label} to sync version{Colors.ENDC}")

    if project_type == 'bro' and version_file_path:
        try:
            with open(version_file_path, 'r', encoding='utf-8') as f:
                mod_json_data = json.load(f)

            current_bromaker_version = mod_json_data.get('BroMakerVersion', None)
            if current_bromaker_version:
                dep_versions = get_dependency_versions()
                latest_bromaker_version = dep_versions.get('BroMaker', current_bromaker_version)

                if current_bromaker_version != latest_bromaker_version:
                    print(f"\n{Colors.WARNING}Outdated BroMakerVersion in {os.path.basename(version_file_path)}:{Colors.ENDC}")
                    print(f"  {current_bromaker_version} {ARROW} {latest_bromaker_version}")

                    if non_interactive:
                        should_update_bromaker = True
                    else:
                        update_bromaker = questionary.confirm(
                            "Update BroMakerVersion to latest?",
                            default=True
                        ).ask()

                        if update_bromaker is None:
                            raise typer.Exit()
                        should_update_bromaker = update_bromaker

                    if should_update_bromaker:
                        mod_json_data['BroMakerVersion'] = latest_bromaker_version
                        with open(version_file_path, 'w', encoding='utf-8') as f:
                            json.dump(mod_json_data, f, indent=2)
                        print(f"{Colors.GREEN}Updated BroMakerVersion to {latest_bromaker_version}{Colors.ENDC}")
        except (json.JSONDecodeError, OSError):
            pass

    zip_filename = f"{namespace}-{package_name}-{version}.zip"
    zip_path = os.path.join(releases_path, zip_filename)

    if os.path.exists(zip_path):
        print(f"\n{Colors.WARNING}Package {zip_filename} already exists{Colors.ENDC}")

        if non_interactive:
            if not overwrite:
                print(f"\n{Colors.FAIL}Error: Package already exists. Use --overwrite to replace it.{Colors.ENDC}")
                raise typer.Exit(1)
            should_overwrite = True
        else:
            overwrite_prompt = questionary.confirm(
                "Overwrite existing package?",
                default=True
            ).ask()

            if overwrite_prompt is None:
                raise typer.Exit()
            should_overwrite = overwrite_prompt

        if not should_overwrite:
            print(f"\n{Colors.CYAN}Packaging cancelled.{Colors.ENDC}")
            print(f"To create a new package, update the version in {changelog_name}")
            raise typer.Exit()

        os.remove(zip_path)
        print(f"{Colors.BLUE}Removed existing package{Colors.ENDC}")
    else:
        old_zips = [f for f in os.listdir(releases_path) if f.endswith('.zip')]
        if old_zips:
            prev_versions_dir = os.path.join(releases_path, 'Previous Versions')
            if not os.path.exists(prev_versions_dir):
                os.makedirs(prev_versions_dir)

            for old_zip in old_zips:
                old_zip_path = os.path.join(releases_path, old_zip)
                new_zip_path = os.path.join(prev_versions_dir, old_zip)
                shutil.move(old_zip_path, new_zip_path)
                print(f"{Colors.BLUE}Archived: {old_zip}{Colors.ENDC}")

    print(f"{Colors.CYAN}Creating package: {zip_filename}{Colors.ENDC}")

    with tempfile.TemporaryDirectory() as temp_dir:
        shutil.copy2(manifest_path, os.path.join(temp_dir, 'manifest.json'))
        shutil.copy2(readme_path, os.path.join(temp_dir, 'README.md'))
        shutil.copy2(icon_path, os.path.join(temp_dir, 'icon.png'))

        with open(changelog_path, 'r', encoding='utf-8') as f:
            changelog_content = f.read()

        changelog_cleaned = re.sub(
            r'(##\s*v?\d+\.\d+\.\d+:?)\s*\(unreleased\)',
            r'\1',
            changelog_content,
            flags=re.IGNORECASE
        )

        if not keep_unreleased and changelog_cleaned != changelog_content:
            with open(changelog_path, 'w', encoding='utf-8') as f:
                f.write(changelog_cleaned)
            print(f"{Colors.GREEN}Removed (unreleased) tag from {changelog_name}{Colors.ENDC}")

        with open(os.path.join(temp_dir, 'CHANGELOG.md'), 'w', encoding='utf-8') as f:
            f.write(changelog_cleaned)

        umm_base = os.path.join(temp_dir, 'UMM')
        target_dir = os.path.join(umm_base, type_info.get("install_subdir", "Mods"), project_name)

        os.makedirs(target_dir, exist_ok=True)

        copyanything(metadata_dir, target_dir)

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, strict_timestamps=False) as zipf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)

    zip_size = os.path.getsize(zip_path) / 1024

    print(f"\n{Colors.GREEN}{Colors.BOLD}{CHECK} Package created!{Colors.ENDC}")
    print(f"{Colors.CYAN}Version:{Colors.ENDC} {version}")
    print(f"{Colors.CYAN}File:{Colors.ENDC} {zip_path}")
    print(f"{Colors.CYAN}Size:{Colors.ENDC} {zip_size:.1f} KB")
    print(f"\n{Colors.CYAN}Package ready for Thunderstore upload!{Colors.ENDC}")

    _copy_to_release_dir(zip_path, namespace, package_name)

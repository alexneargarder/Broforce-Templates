"""Thunderstore API integration and packaging."""
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Optional

from .colors import Colors
from .config import get_cache_file
from .paths import ensure_dir, get_cache_dir

try:
    import urllib.request
    import urllib.error
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

FALLBACK_DEPENDENCY_VERSIONS = {
    'UMM': '1.0.2',
    'RocketLib': '2.4.0',
    'BroMaker': '2.6.0',
}

THUNDERSTORE_PACKAGES = {
    'UMM': ('UMM', 'UMM'),
    'RocketLib': ('RocketLib', 'RocketLib'),
    'BroMaker': ('BroMaker', 'BroMaker'),
}

CACHE_DURATION = 24 * 60 * 60


def fetch_thunderstore_version(namespace: str, package_name: str) -> Optional[str]:
    """Fetch latest version from Thunderstore API."""
    if not HAS_URLLIB:
        return None

    url = f"https://thunderstore.io/api/experimental/package/{namespace}/{package_name}/"

    try:
        with urllib.request.urlopen(url, timeout=5) as response:
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
                if versions:
                    return versions
        except (json.JSONDecodeError, OSError):
            pass

    versions = {}
    for dep_name, (namespace, package) in THUNDERSTORE_PACKAGES.items():
        version = fetch_thunderstore_version(namespace, package)
        if version:
            versions[dep_name] = version
        else:
            versions[dep_name] = FALLBACK_DEPENDENCY_VERSIONS[dep_name]

    try:
        ensure_dir(get_cache_dir())
        cache_data = {
            'timestamp': time.time(),
            'versions': versions
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
        'UMM': f"UMM-UMM-{versions['UMM']}",
        'RocketLib': f"RocketLib-RocketLib-{versions['RocketLib']}",
        'BroMaker': f"BroMaker-BroMaker-{versions['BroMaker']}",
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
        depth = root.replace(project_path, '').count(os.sep)
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


def get_version_from_info_json(modcontent_path: str, project_type: str) -> Optional[str]:
    """Get version from Info.json (mods) or .mod.json (bros)."""
    if not os.path.exists(modcontent_path):
        return None

    version_file = None
    if project_type == 'mod':
        info_path = os.path.join(modcontent_path, 'Info.json')
        if os.path.exists(info_path):
            version_file = info_path
    else:
        for file in os.listdir(modcontent_path):
            if file.endswith('.mod.json'):
                version_file = os.path.join(modcontent_path, file)
                break

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
    """Sync version in Info.json (mods) or .mod.json (bros) with target version."""
    if not os.path.exists(modcontent_path):
        return (False, None)

    version_file = None
    if project_type == 'mod':
        info_path = os.path.join(modcontent_path, 'Info.json')
        if os.path.exists(info_path):
            version_file = info_path
    else:
        for file in os.listdir(modcontent_path):
            if file.endswith('.mod.json'):
                version_file = os.path.join(modcontent_path, file)
                break

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

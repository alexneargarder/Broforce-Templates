import shutil, errno
import os, fnmatch
import sys
import re
import json
import xml.etree.ElementTree as ET
import time
import tempfile
from typing import Optional

import typer
import questionary

try:
    import urllib.request
    import urllib.error
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

# Fallback dependency versions (used if Thunderstore API is unavailable)
FALLBACK_DEPENDENCY_VERSIONS = {
    'UMM': '1.0.2',
    'RocketLib': '2.4.0',
    'BroMaker': '2.6.0',
}

# Thunderstore package info (namespace/package name)
THUNDERSTORE_PACKAGES = {
    'UMM': ('UMM', 'UMM'),
    'RocketLib': ('RocketLib', 'RocketLib'),
    'BroMaker': ('BroMaker', 'BroMaker'),
}

# Cache duration: 24 hours (in seconds)
CACHE_DURATION = 24 * 60 * 60

# Cache file location
CACHE_FILE = os.path.join(tempfile.gettempdir(), 'broforce_tools_dependency_cache.json')

# Config file location (in same directory as script)
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'broforce-tools.json')

def load_config():
    """Load configuration from config file

    Returns dict with 'repos' key (list of repo names)
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {'repos': []}

def save_config(config):
    """Save configuration to config file"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        return True
    except OSError:
        return False

def get_configured_repos():
    """Get list of configured repos"""
    config = load_config()
    return config.get('repos', [])


def get_ignored_projects(repo_name):
    """Get list of ignored project names for a repo"""
    config = load_config()
    ignore_config = config.get('ignore', {})
    return ignore_config.get(repo_name, [])


def get_repos_to_search(repos_parent, use_all_repos=False):
    """Get list of repos to search for projects.

    Args:
        repos_parent: Parent directory containing all repos
        use_all_repos: If True, always use configured repos

    Returns:
        Tuple of (repos_list, is_single_repo) where is_single_repo indicates
        if we're searching just the current repo (affects display formatting)
    """
    if use_all_repos:
        repos = get_configured_repos()
        if not repos:
            return None, False
        return repos, False

    # Try current repo first
    current_repo = detect_current_repo(repos_parent)
    if current_repo:
        return [current_repo], True

    # Fall back to configured repos
    repos = get_configured_repos()
    if repos:
        return repos, False

    return None, False


def fetch_thunderstore_version(namespace, package_name):
    """Fetch latest version from Thunderstore API

    Returns version string or None if fetch fails
    """
    if not HAS_URLLIB:
        return None

    url = f"https://thunderstore.io/api/experimental/package/{namespace}/{package_name}/"

    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('latest', {}).get('version_number', None)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return None

def get_dependency_versions():
    """Get dependency versions, fetching from Thunderstore API with caching

    Returns dict of {dep_name: version_string}
    """
    # Try to load from cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # Check if cache is still valid
            cache_time = cache_data.get('timestamp', 0)
            if time.time() - cache_time < CACHE_DURATION:
                versions = cache_data.get('versions', {})
                if versions:
                    return versions
        except (json.JSONDecodeError, OSError):
            pass

    # Cache is invalid or doesn't exist, fetch from API
    versions = {}
    for dep_name, (namespace, package) in THUNDERSTORE_PACKAGES.items():
        version = fetch_thunderstore_version(namespace, package)
        if version:
            versions[dep_name] = version
        else:
            # Fall back to hardcoded version
            versions[dep_name] = FALLBACK_DEPENDENCY_VERSIONS[dep_name]

    # Save to cache
    try:
        cache_data = {
            'timestamp': time.time(),
            'versions': versions
        }
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)
    except OSError:
        pass  # Cache save failed, not critical

    return versions

# Get dependency versions (from API or fallback)
DEPENDENCY_VERSIONS = get_dependency_versions()

# Dependency string format: "Namespace-PackageName-Version"
DEPENDENCIES = {
    'UMM': f"UMM-UMM-{DEPENDENCY_VERSIONS['UMM']}",
    'RocketLib': f"RocketLib-RocketLib-{DEPENDENCY_VERSIONS['RocketLib']}",
    'BroMaker': f"BroMaker-BroMaker-{DEPENDENCY_VERSIONS['BroMaker']}",
}

# Color codes for terminal output
# Color scheme:
#   GREEN - Actions taken (files created/modified)
#   CYAN - Key information (version, package name, selected project)
#   BLUE - Status info (already correct, no change needed)
#   WARNING (yellow) - Warnings and prompts
#   FAIL (red) - Errors
class Colors:
    # Check if we're on Windows and colors are supported
    if sys.platform == 'win32':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except:
            pass

    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def copyanything(src, dst):
    def ignore_patterns(path, names):
        # Ignore Visual Studio user-specific files and folders
        ignored = []
        for name in names:
            if name == '.vs' or name.endswith('.suo') or name.endswith('.user'):
                ignored.append(name)
        return ignored

    try:
        shutil.copytree(src, dst, ignore=ignore_patterns, dirs_exist_ok=True)
    except OSError as exc: # python >2.5
        if exc.errno in (errno.ENOTDIR, errno.EINVAL):
            shutil.copy(src, dst)
        else: raise

def findReplace(directory, find, replace, filePattern):
    for path, dirs, files in os.walk(os.path.abspath(directory)):
        for filename in fnmatch.filter(files, filePattern):
            filepath = os.path.join(path, filename)
            with open(filepath, encoding='utf-8') as f:
                s = f.read()
            s = s.replace(find, replace)
            with open(filepath, "w", encoding='utf-8') as f:
                f.write(s)
        for dir in dirs:
            findReplace(os.path.join(path, dir), find, replace, filePattern)

def renameFiles(directory, find, replace):
    for path, dirs, files in os.walk(os.path.abspath(directory)):
        for filename in fnmatch.filter(files, find + '.*'):
            filepath = os.path.join(path, filename)
            os.rename(filepath, os.path.join(path, replace) + '.' + filename.partition('.')[2])
        for dir in dirs:
            filepath = os.path.join(path, dir)
            if dir == find:
                os.rename(filepath, os.path.join(path, replace))
                renameFiles(os.path.join(path, replace), find, replace)
            else:
                renameFiles(filepath, find, replace)

def find_props_file(start_dir, filename):
    """Search for a props file in current dir and parents"""
    search_dir = os.path.abspath(start_dir)
    while True:
        props_path = os.path.join(search_dir, filename)
        if os.path.exists(props_path):
            return props_path
        parent = os.path.dirname(search_dir)
        if parent == search_dir:  # Reached root
            return None
        search_dir = parent

def parse_props_file(props_file, property_name):
    """Extract a property value from props file"""
    try:
        tree = ET.parse(props_file)
        root = tree.getroot()

        # Handle namespace
        ns = {'msbuild': 'http://schemas.microsoft.com/developer/msbuild/2003'}

        # Find PropertyGroup/PropertyName
        for prop_group in root.findall('.//msbuild:PropertyGroup', ns):
            prop = prop_group.find(f'.//msbuild:{property_name}', ns)
            if prop is not None and prop.text:
                return prop.text.strip()

        # Try without namespace (for files that might not have it)
        for prop_group in root.findall('.//PropertyGroup'):
            prop = prop_group.find(f'.//{property_name}')
            if prop is not None and prop.text:
                return prop.text.strip()

        return None
    except Exception as e:
        print(f"{Colors.WARNING}Warning: Could not parse {props_file}: {e}{Colors.ENDC}")
        return None

def get_broforce_path(repos_parent):
    """Get Broforce path from props files or prompt"""
    # Try LocalBroforcePath.props in repos parent
    local_props = find_props_file(repos_parent, 'LocalBroforcePath.props')
    if local_props:
        path = parse_props_file(local_props, 'BroforcePath')
        if path:
            print(f"{Colors.GREEN}Found Broforce path from LocalBroforcePath.props: {path}{Colors.ENDC}")
            return path

    # Try BroforceGlobal.props in repos parent
    global_props = os.path.join(repos_parent, 'BroforceGlobal.props')
    if os.path.exists(global_props):
        path = parse_props_file(global_props, 'BroforcePath')
        if path:
            print(f"{Colors.GREEN}Found Broforce path from BroforceGlobal.props: {path}{Colors.ENDC}")
            return path

    # Fallback: prompt user
    print(f"{Colors.WARNING}Could not find BroforcePath in props files.{Colors.ENDC}")
    print(f"{Colors.CYAN}Searched for:{Colors.ENDC}")
    print(f"  - LocalBroforcePath.props in: {repos_parent}")
    print(f"  - BroforceGlobal.props in: {repos_parent}")
    print()
    path = questionary.text("Enter Broforce installation path:").ask()
    if not path:
        raise typer.Exit()
    if not os.path.exists(path):
        print(f"{Colors.FAIL}Error: Path does not exist: {path}{Colors.ENDC}")
        raise typer.Exit(1)
    return path

def get_bromaker_lib_path(repos_parent, broforce_path):
    """Get BroMakerLib path from props files or auto-detect"""
    # Try LocalBroforcePath.props
    local_props = find_props_file(repos_parent, 'LocalBroforcePath.props')
    if local_props:
        path = parse_props_file(local_props, 'BroMakerLibPath')
        if path and os.path.exists(path):
            print(f"{Colors.GREEN}Found BroMakerLib path from LocalBroforcePath.props{Colors.ENDC}")
            return path

    # Auto-detect: try local Bro-Maker repo first
    local_bromaker = os.path.join(repos_parent, "Bro-Maker", "BroMakerLib", "bin", "Debug", "BroMakerLib.dll")
    if os.path.exists(local_bromaker):
        print(f"{Colors.GREEN}Found local BroMakerLib at: {local_bromaker}{Colors.ENDC}")
        return local_bromaker

    # Fall back to installed version
    installed_bromaker = os.path.join(broforce_path, "Mods", "BroMaker", "BroMakerLib.dll")
    if os.path.exists(installed_bromaker):
        print(f"{Colors.GREEN}Found installed BroMakerLib in Mods folder{Colors.ENDC}")
        return installed_bromaker

    print(f"{Colors.WARNING}Warning: Could not find BroMakerLib.dll{Colors.ENDC}")
    print(f"  Tried: {local_bromaker}")
    print(f"  Tried: {installed_bromaker}")
    return None

def validate_package_name(name):
    """Validate package name against Thunderstore rules"""
    if len(name) > 128:
        return False, f"Name too long ({len(name)} chars, max 128)"

    if not re.match(r'^[a-zA-Z0-9_]+$', name):
        return False, "Name must contain only alphanumeric characters and underscores"

    return True, "OK"

def sanitize_package_name(name):
    """Convert project name to valid package name"""
    # Replace spaces with underscores
    sanitized = name.replace(' ', '_')
    # Remove any other invalid characters
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '', sanitized)
    return sanitized

def detect_dependencies_from_csproj(project_path):
    """Detect RocketLib and BroMaker dependencies from .csproj file

    Returns list of dependency strings (e.g., ["RocketLib-RocketLib-2.4.0"])
    """
    dependencies = [DEPENDENCIES['UMM']]  # Always include UMM

    # Find .csproj file (check up to 2 levels deep)
    csproj_files = []
    for root, dirs, files in os.walk(project_path):
        # Calculate depth from project_path
        depth = root.replace(project_path, '').count(os.sep)
        if depth > 1:
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

        # Handle namespace
        ns = {'msbuild': 'http://schemas.microsoft.com/developer/msbuild/2003'}

        # Check for RocketLib reference
        for ref in root.findall('.//msbuild:Reference', ns):
            include = ref.get('Include', '')
            if 'RocketLib' in include:
                dependencies.append(DEPENDENCIES['RocketLib'])
                break

        # Try without namespace
        if DEPENDENCIES['RocketLib'] not in dependencies:
            for ref in root.findall('.//Reference'):
                include = ref.get('Include', '')
                if 'RocketLib' in include:
                    dependencies.append(DEPENDENCIES['RocketLib'])
                    break

        # Check for BroMakerLib reference
        for ref in root.findall('.//msbuild:Reference', ns):
            include = ref.get('Include', '')
            if 'BroMakerLib' in include:
                dependencies.append(DEPENDENCIES['BroMaker'])
                break

        # Try without namespace
        if DEPENDENCIES['BroMaker'] not in dependencies:
            for ref in root.findall('.//Reference'):
                include = ref.get('Include', '')
                if 'BroMakerLib' in include:
                    dependencies.append(DEPENDENCIES['BroMaker'])
                    break

    except Exception as e:
        print(f"{Colors.WARNING}Warning: Could not parse .csproj: {e}{Colors.ENDC}")

    return dependencies

def get_source_directory(project_path):
    """Get the actual source directory containing _ModContent

    Handles both flat and nested project structures:
    - Flat: ProjectName/_ModContent/ → returns ProjectName/
    - Nested: ProjectName/ProjectName/_ModContent/ → returns ProjectName/ProjectName/

    Returns None if _ModContent not found in either location.
    """
    # First try flat structure
    if os.path.exists(os.path.join(project_path, '_ModContent')):
        return project_path

    # Try nested structure (ProjectName/ProjectName/)
    project_name = os.path.basename(project_path)
    nested_path = os.path.join(project_path, project_name)
    if os.path.exists(os.path.join(nested_path, '_ModContent')):
        return nested_path

    return None

def detect_project_type(project_path):
    """Detect if project is a mod or bro"""
    source_dir = get_source_directory(project_path)
    if not source_dir:
        return None

    mod_content_path = os.path.join(source_dir, '_ModContent')

    # Check for Info.json (mod)
    if os.path.exists(os.path.join(mod_content_path, 'Info.json')):
        return 'mod'

    # Check for .mod.json files (bro)
    try:
        for file in os.listdir(mod_content_path):
            if file.endswith('.mod.json'):
                return 'bro'
    except (OSError, FileNotFoundError):
        return None

    return None

def find_changelog(releases_path):
    """Find changelog file, checking both Changelog.md and CHANGELOG.md"""
    for name in ['Changelog.md', 'CHANGELOG.md']:
        path = os.path.join(releases_path, name)
        if os.path.exists(path):
            return path
    return None


def get_version_from_changelog(changelog_path):
    """Parse version from Changelog.md or CHANGELOG.md"""
    if not os.path.exists(changelog_path):
        return None

    try:
        with open(changelog_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Try patterns in order of preference
        patterns = [
            r'##\s*v?(\d+\.\d+\.\d+):?\s*\(unreleased\)',  # ## v1.0.0 (unreleased) or ## v1.0.0: (unreleased)
            r'##\s*v?(\d+\.\d+\.\d+):?',  # ## v1.0.0 or ## v1.0.0:
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)

        return None
    except Exception as e:
        print(f"{Colors.WARNING}Warning: Could not parse changelog: {e}{Colors.ENDC}")
        return None

def find_dll_in_modcontent(modcontent_path):
    """Find DLL file in _ModContent folder"""
    if not os.path.exists(modcontent_path):
        return None

    for file in os.listdir(modcontent_path):
        if file.endswith('.dll'):
            return os.path.join(modcontent_path, file)

    return None

def get_version_from_info_json(modcontent_path, project_type):
    """Get version from Info.json (mods) or .mod.json (bros)

    Returns version string or None if not found
    """
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

def compare_versions(v1, v2):
    """Compare semantic versions. Returns 1 if v1 > v2, -1 if v1 < v2, 0 if equal"""
    if not v1:
        return -1
    if not v2:
        return 1

    try:
        parts1 = [int(x) for x in v1.split('.')]
        parts2 = [int(x) for x in v2.split('.')]

        # Pad to same length
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

def sync_version_file(modcontent_path, project_type, target_version):
    """Sync version in Info.json (mods) or .mod.json (bros) with target version

    Returns: (updated, version_file_path) tuple
        - updated: True if version was updated, False if already correct
        - version_file_path: Path to the version file that was checked/updated
    """
    if not os.path.exists(modcontent_path):
        return (False, None)

    # Find the appropriate version file
    version_file = None
    if project_type == 'mod':
        # For mods: Info.json
        info_path = os.path.join(modcontent_path, 'Info.json')
        if os.path.exists(info_path):
            version_file = info_path
    else:
        # For bros: {BroName}.mod.json
        for file in os.listdir(modcontent_path):
            if file.endswith('.mod.json'):
                version_file = os.path.join(modcontent_path, file)
                break

    if not version_file:
        return (False, None)

    # Read current version
    try:
        with open(version_file, 'r', encoding='utf-8') as f:
            version_data = json.load(f)

        current_version = version_data.get('Version', '')

        # Check if update needed
        if current_version == target_version:
            return (False, version_file)

        # Update version
        version_data['Version'] = target_version

        # Write back to file
        with open(version_file, 'w', encoding='utf-8') as f:
            json.dump(version_data, f, indent=2)

        return (True, version_file)

    except Exception as e:
        print(f"{Colors.WARNING}Warning: Could not sync version file: {e}{Colors.ENDC}")
        return (False, version_file)

def detect_current_repo(repos_parent):
    """Detect which repo we're currently in based on cwd

    Returns repo name (e.g., 'RocketLib') or None if not in a repo
    """
    cwd = os.getcwd()

    # Convert both to absolute paths with normalized separators (keep original for later)
    cwd_original = os.path.abspath(cwd).replace('\\', '/')
    repos_original = os.path.abspath(repos_parent).replace('\\', '/')

    # Lowercase versions for comparison
    cwd_abs = cwd_original.lower()
    repos_abs = repos_original.lower()

    # Handle WSL/Windows path conversion for comparison
    # Convert C:/... to /mnt/c/... or vice versa
    cwd_abs_alt = None
    repos_abs_alt = None

    if cwd_abs.startswith('c:/'):
        cwd_abs = '/mnt/c/' + cwd_abs[3:]
    elif cwd_abs.startswith('/mnt/c/'):
        cwd_abs_alt = 'c:/' + cwd_abs[7:]

    if repos_abs.startswith('c:/'):
        repos_abs = '/mnt/c/' + repos_abs[3:]
    elif repos_abs.startswith('/mnt/c/'):
        repos_abs_alt = 'c:/' + repos_abs[7:]

    # Also convert original paths
    cwd_orig_normalized = cwd_original.lower()
    if cwd_orig_normalized.startswith('c:/'):
        cwd_orig_normalized = '/mnt/c/' + cwd_orig_normalized[3:]

    repos_orig_normalized = repos_original.lower()
    if repos_orig_normalized.startswith('c:/'):
        repos_orig_normalized = '/mnt/c/' + repos_orig_normalized[3:]

    # Check if cwd is within repos_parent (try both formats)
    try:
        is_inside = False
        rel_path_lower = None
        rel_path_original = None

        if cwd_abs.startswith(repos_abs):
            is_inside = True
            rel_path_lower = cwd_abs[len(repos_abs):].lstrip('/')
            # Get relative path from original (non-lowercased) paths
            if cwd_orig_normalized.startswith(repos_orig_normalized):
                rel_path_original = cwd_original[len(repos_original):].lstrip('/')
        elif cwd_abs_alt and repos_abs_alt and cwd_abs_alt.startswith(repos_abs_alt):
            is_inside = True
            rel_path_lower = cwd_abs_alt[len(repos_abs_alt):].lstrip('/')
            rel_path_original = cwd_original[len(repos_original):].lstrip('/')

        if not is_inside or not rel_path_lower:
            return None

        # Get the first component from original path (preserves casing)
        if rel_path_original:
            repo_name = rel_path_original.split('/')[0]
        else:
            repo_name = rel_path_lower.split('/')[0]

        if not repo_name:
            return None

        # Verify it's actually a directory in repos_parent
        # List directories and find case-insensitive match
        try:
            actual_dirs = os.listdir(repos_parent)
            for dir_name in actual_dirs:
                if dir_name.lower() == repo_name.lower():
                    repo_path = os.path.join(repos_parent, dir_name)
                    if os.path.isdir(repo_path):
                        return dir_name  # Return with actual casing
        except (OSError, FileNotFoundError):
            pass

        return None
    except (ValueError, OSError):
        return None

    return None

def find_projects(repos_parent, repos, require_metadata=False, exclude_with_metadata=False):
    """Find projects in the given repos.

    Args:
        repos_parent: Parent directory containing all repos
        repos: List of repo names to search
        require_metadata: If True, only return projects WITH Thunderstore metadata
        exclude_with_metadata: If True, only return projects WITHOUT Thunderstore metadata

    Returns:
        List of (project_name, repo_name) tuples, sorted by project name
    """
    skip_dirs = {'bin', 'obj', 'packages', 'Releases', 'Release', 'libs', '.vs', '.git'}
    projects = []

    for repo in repos:
        ignored_projects = get_ignored_projects(repo)
        repo_path = os.path.join(repos_parent, repo)
        if not os.path.exists(repo_path):
            continue

        try:
            for item in os.listdir(repo_path):
                # Skip hidden/system directories
                if item.startswith('.') or item.startswith('_') or item in skip_dirs:
                    continue

                item_path = os.path.join(repo_path, item)
                if not os.path.isdir(item_path):
                    continue

                # Check for .csproj in project dir or one level down
                has_csproj = False
                try:
                    for f in os.listdir(item_path):
                        if f.endswith('.csproj'):
                            has_csproj = True
                            break
                        subpath = os.path.join(item_path, f)
                        if os.path.isdir(subpath):
                            try:
                                for sf in os.listdir(subpath):
                                    if sf.endswith('.csproj'):
                                        has_csproj = True
                                        break
                            except (OSError, FileNotFoundError):
                                pass
                        if has_csproj:
                            break
                except (OSError, FileNotFoundError):
                    continue

                if not has_csproj:
                    continue

                # Check for Thunderstore metadata
                has_metadata = _project_has_metadata(repos_parent, repo, item)

                # Apply filters
                if item in ignored_projects:
                    continue
                if require_metadata and not has_metadata:
                    continue
                if exclude_with_metadata and has_metadata:
                    continue

                projects.append((item, repo))
        except (OSError, FileNotFoundError):
            continue

    return sorted(projects, key=lambda x: x[0])


def _project_has_metadata(repos_parent, repo, project_name):
    """Check if a project has Thunderstore metadata (manifest.json).

    Handles both repo structures:
    - Multi-project: {repo}/Releases/{project}/manifest.json
    - Single-project: {repo}/Release/manifest.json (any project in repo uses this)
    """
    repo_path = os.path.join(repos_parent, repo)

    # Check multi-project structure
    multi_manifest = os.path.join(repo_path, 'Releases', project_name, 'manifest.json')
    if os.path.exists(multi_manifest):
        return True

    # Check single-project structure - if Release/ exists with manifest, any project has metadata
    single_manifest = os.path.join(repo_path, 'Release', 'manifest.json')
    if os.path.exists(single_manifest):
        return True

    return False


def select_projects_interactive(repos_parent, mode, use_all_repos=False, allow_batch=True):
    """Interactive project selection for commands.

    Args:
        repos_parent: Parent directory containing all repos
        mode: 'package' (require metadata) or 'init' (exclude metadata)
        use_all_repos: If True, search all configured repos
        allow_batch: If True, show "all" option for batch operations

    Returns:
        List of (project_name, repo_name) tuples (single item if not batch)
        Returns empty list if user cancels
    """
    # Get repos to search
    repos, is_single_repo = get_repos_to_search(repos_parent, use_all_repos)
    if not repos:
        print(f"{Colors.FAIL}Error: No repos configured. Use --add-repo to add repos.{Colors.ENDC}")
        return []

    # Find projects based on mode
    if mode == 'package':
        projects = find_projects(repos_parent, repos, require_metadata=True)
        no_projects_msg = "No projects with Thunderstore metadata found"
        no_projects_hint = "Run: broforce-tools init-thunderstore"
        batch_label = "Package all"
    else:  # init
        projects = find_projects(repos_parent, repos, exclude_with_metadata=True)
        no_projects_msg = "No projects needing Thunderstore initialization found"
        no_projects_hint = "All projects already have metadata"
        batch_label = "Initialize all"

    if not projects:
        print(f"{Colors.FAIL}Error: {no_projects_msg}{Colors.ENDC}")
        print(no_projects_hint)
        return []

    # Auto-select if only one project
    if len(projects) == 1:
        project_name, repo = projects[0]
        print(f"{Colors.CYAN}Using project: {project_name}{Colors.ENDC}")
        return [projects[0]]

    # Build choices
    if allow_batch:
        choices = [f"{batch_label} ({len(projects)} projects)"]
    else:
        choices = []

    if is_single_repo:
        choices.extend([name for name, repo in projects])
    else:
        choices.extend([f"{name} ({repo})" for name, repo in projects])

    # Show menu
    prompt = f"Select project:" if not is_single_repo else f"Select project from {repos[0]}:"
    selection = questionary.select(prompt, choices=choices).ask()

    if not selection:  # User cancelled
        return []

    # Handle batch selection
    if allow_batch and selection.startswith(batch_label.split()[0]):
        return projects

    # Extract project from selection
    if is_single_repo:
        return [(selection, repos[0])]
    else:
        project_name = selection.rsplit(' (', 1)[0]
        # Find the matching project tuple
        for p in projects:
            if p[0] == project_name:
                return [p]
        return []


def do_init_thunderstore(project_name, script_dir, repos_parent):
    """Initialize Thunderstore metadata for an existing project"""
    print(f"{Colors.HEADER}Initializing Thunderstore metadata for '{project_name}'{Colors.ENDC}")

    template_repo_dir = os.path.dirname(script_dir)

    # Find all repos in parent directory
    repos = [d for d in os.listdir(repos_parent) if os.path.isdir(os.path.join(repos_parent, d))]

    # Search for project in all repos
    project_path = None
    releases_path = None
    output_repo = None

    for repo in repos:
        repo_path = os.path.join(repos_parent, repo)
        potential_project = os.path.join(repo_path, project_name)

        if not os.path.exists(potential_project):
            continue

        # Check for single-project repo: {repo}/Release/
        potential_release_single = os.path.join(repo_path, 'Release')
        if os.path.exists(potential_release_single) and os.path.isdir(potential_release_single):
            # For single-project repos, the Release directory exists
            # Check if the project we found is the actual project in this repo
            # (could be repo name matches project name, or project is subdirectory)
            if os.path.exists(potential_project) and os.path.isdir(potential_project):
                project_path = potential_project
                releases_path = potential_release_single
                output_repo = repo
                break

        # Check for multi-project repo: {repo}/Releases/{project}/
        potential_releases_multi = os.path.join(repo_path, 'Releases', project_name)
        if os.path.exists(potential_releases_multi):
            project_path = potential_project
            releases_path = potential_releases_multi
            output_repo = repo
            break

    if not project_path or not releases_path:
        print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
        print(f"Searched in: {repos_parent}")
        raise typer.Exit(1)

    print(f"{Colors.BLUE}Found project in: {output_repo}{Colors.ENDC}")

    # Detect project type
    project_type = detect_project_type(project_path)
    if not project_type:
        print(f"{Colors.FAIL}Error: Could not detect project type (no _ModContent or missing detection files){Colors.ENDC}")
        raise typer.Exit(1)

    print(f"{Colors.BLUE}Detected project type: {project_type}{Colors.ENDC}")

    # Prompt for Thunderstore metadata
    print(f"\n{Colors.HEADER}Enter Thunderstore package information:{Colors.ENDC}")

    # Load defaults from config
    config = load_config()
    defaults = config.get('defaults', {})
    default_namespace = defaults.get('namespace', '')
    default_website = defaults.get('website_url', '')

    # Namespace
    if default_namespace:
        namespace = questionary.text(
            f"Namespace/Author [{default_namespace}]:",
            default=default_namespace,
            validate=lambda text: validate_package_name(text)[0] if text else True
        ).ask()
        if namespace is None:
            raise typer.Exit()
        if not namespace:
            namespace = default_namespace
    else:
        namespace = questionary.text(
            "Namespace/Author (e.g., AlexNeargarder):",
            validate=lambda text: validate_package_name(text)[0]
        ).ask()
        if namespace is None or not namespace:
            raise typer.Exit()

    # Package name
    suggested_name = sanitize_package_name(project_name)
    package_name = questionary.text(
        f"Package name [{suggested_name}]:",
        default=suggested_name,
        validate=lambda text: validate_package_name(text)[0] if text else True
    ).ask()
    if package_name is None:
        raise typer.Exit()
    if not package_name:
        package_name = suggested_name

    # Description
    description = questionary.text("Description (max 250 chars):").ask()
    if description is None:
        raise typer.Exit()
    if len(description) > 250:
        print(f"{Colors.WARNING}Warning: Description truncated to 250 characters{Colors.ENDC}")
        description = description[:250]

    # Website URL
    if default_website:
        website_url = questionary.text(
            f"Website/GitHub URL [{default_website}]:",
            default=default_website
        ).ask()
        if website_url is None:
            raise typer.Exit()
        if not website_url:
            website_url = default_website
    else:
        website_url = questionary.text("Website/GitHub URL:").ask()
        if website_url is None:
            raise typer.Exit()
        website_url = website_url or ""

    # Check if changelog exists (either Changelog.md or CHANGELOG.md), create if missing
    changelog_path = find_changelog(releases_path)
    if not changelog_path:
        changelog_path = os.path.join(releases_path, 'Changelog.md')
        print(f"{Colors.WARNING}Changelog not found, creating default{Colors.ENDC}")
        with open(changelog_path, 'w', encoding='utf-8') as f:
            f.write('## v1.0.0 (unreleased)\n- Initial release\n')

    # Detect dependencies from .csproj
    detected_deps = detect_dependencies_from_csproj(project_path)
    if len(detected_deps) > 1:  # More than just UMM
        print(f"{Colors.BLUE}Detected dependencies:{Colors.ENDC}")
        for dep in detected_deps:
            if dep != DEPENDENCIES['UMM']:
                print(f"  - {dep}")

    # Create manifest.json
    manifest_path = os.path.join(releases_path, 'manifest.json')
    manifest_data = {
        "name": package_name,
        "author": namespace,
        "version_number": "1.0.0",
        "website_url": website_url,
        "description": description,
        "dependencies": detected_deps
    }

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f, indent=2)

    print(f"{Colors.GREEN}Created manifest.json{Colors.ENDC}")

    # Copy README template (skip if already exists)
    readme_template = os.path.join(template_repo_dir, 'ThunderstorePackage', 'README.md')
    readme_dest = os.path.join(releases_path, 'README.md')

    if os.path.exists(readme_dest):
        print(f"{Colors.BLUE}README.md already exists, skipping{Colors.ENDC}")
    elif os.path.exists(readme_template):
        with open(readme_template, 'r', encoding='utf-8') as f:
            readme_content = f.read()

        # Replace placeholders
        readme_content = readme_content.replace('PROJECT_NAME', project_name)
        readme_content = readme_content.replace('DESCRIPTION_PLACEHOLDER', description)
        readme_content = readme_content.replace('FEATURES_PLACEHOLDER', '*Describe your mod\'s features here*')
        readme_content = readme_content.replace('AUTHOR_NAME', namespace)
        readme_content = readme_content.replace('REPO_NAME', output_repo)

        with open(readme_dest, 'w', encoding='utf-8') as f:
            f.write(readme_content)

        print(f"{Colors.GREEN}Created README.md{Colors.ENDC}")
    else:
        print(f"{Colors.WARNING}Warning: README template not found at {readme_template}{Colors.ENDC}")

    # Copy icon placeholder (skip if already exists)
    icon_template = os.path.join(template_repo_dir, 'ThunderstorePackage', 'icon.png')
    icon_dest = os.path.join(releases_path, 'icon.png')

    if os.path.exists(icon_dest):
        print(f"{Colors.BLUE}icon.png already exists, skipping{Colors.ENDC}")
    elif os.path.exists(icon_template):
        shutil.copy2(icon_template, icon_dest)
        print(f"{Colors.GREEN}Created icon.png{Colors.ENDC}")
        print(f"{Colors.WARNING}⚠️  Replace icon.png with a custom 256x256 image!{Colors.ENDC}")
    else:
        print(f"{Colors.WARNING}Warning: Icon template not found at {icon_template}{Colors.ENDC}")

    # Success summary
    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Thunderstore metadata initialized!{Colors.ENDC}")
    print(f"{Colors.CYAN}Location:{Colors.ENDC} {releases_path}")
    print(f"\n{Colors.CYAN}Files created:{Colors.ENDC}")
    print(f"  - manifest.json")
    print(f"  - README.md (customize for Thunderstore)")
    print(f"  - icon.png (⚠️  placeholder - replace with 256x256 custom icon!)")
    print(f"\n{Colors.CYAN}Next steps:{Colors.ENDC}")
    print(f"  1. Edit {releases_path}/README.md")
    print(f"  2. Replace icon.png with custom icon")
    print(f"  3. Review manifest.json dependencies")
    print(f"  4. Run: bt package \"{project_name}\"")

def do_package(project_name, script_dir, repos_parent, version_override=None):
    """Create Thunderstore package for an existing project"""
    import zipfile
    import tempfile
    import filecmp

    template_repo_dir = os.path.dirname(script_dir)

    # Find project (same logic as init-thunderstore)
    repos = [d for d in os.listdir(repos_parent) if os.path.isdir(os.path.join(repos_parent, d))]
    project_path = None
    releases_path = None
    output_repo = None

    for repo in repos:
        repo_path = os.path.join(repos_parent, repo)
        potential_project = os.path.join(repo_path, project_name)

        if not os.path.exists(potential_project):
            continue

        # Check for single-project repo: {repo}/Release/
        potential_release_single = os.path.join(repo_path, 'Release')
        if os.path.exists(potential_release_single) and os.path.isdir(potential_release_single):
            # For single-project repos, the Release directory exists
            # Check if the project we found is the actual project in this repo
            # (could be repo name matches project name, or project is subdirectory)
            if os.path.exists(potential_project) and os.path.isdir(potential_project):
                project_path = potential_project
                releases_path = potential_release_single
                output_repo = repo
                break

        # Check for multi-project repo: {repo}/Releases/{project}/
        potential_releases_multi = os.path.join(repo_path, 'Releases', project_name)
        if os.path.exists(potential_releases_multi):
            project_path = potential_project
            releases_path = potential_releases_multi
            output_repo = repo
            break

    if not project_path or not releases_path:
        print(f"{Colors.FAIL}Error: Could not find project '{project_name}'{Colors.ENDC}")
        raise typer.Exit(1)

    # Validate metadata exists
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

    # Detect project type
    project_type = detect_project_type(project_path)
    if not project_type:
        print(f"{Colors.FAIL}Error: Could not detect project type{Colors.ENDC}")
        raise typer.Exit(1)

    # Validate DLL exists
    source_dir = get_source_directory(project_path)
    if not source_dir:
        print(f"{Colors.FAIL}Error: Could not find source directory with _ModContent{Colors.ENDC}")
        raise typer.Exit(1)

    modcontent_path = os.path.join(source_dir, '_ModContent')
    dll_path = find_dll_in_modcontent(modcontent_path)

    if not dll_path:
        print(f"{Colors.FAIL}Error: No DLL found in _ModContent{Colors.ENDC}")
        print(f"Build the project first")
        raise typer.Exit(1)

    # Check if icon is placeholder
    icon_template = os.path.join(template_repo_dir, 'ThunderstorePackage', 'icon.png')
    if os.path.exists(icon_template) and filecmp.cmp(icon_path, icon_template, shallow=False):
        print(f"{Colors.WARNING}⚠️  Warning: Using placeholder icon{Colors.ENDC}")

    # Get version from all sources and find the highest
    changelog_name = os.path.basename(changelog_path)

    if version_override:
        version = version_override
        print(f"{Colors.CYAN}Using version override: {version}{Colors.ENDC}")
    else:
        # Check all version sources
        changelog_version = get_version_from_changelog(changelog_path)
        manifest_version = None
        info_version = None

        # Try to read manifest version (may not exist yet on first init)
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data_temp = json.load(f)
            manifest_version = manifest_data_temp.get('version_number', None)
        except Exception:
            pass

        # Get version from Info.json or .mod.json
        info_version = get_version_from_info_json(modcontent_path, project_type)

        # Find highest version
        versions = {
            changelog_name: changelog_version,
            'manifest.json': manifest_version,
            'Info.json/.mod.json': info_version
        }

        # Filter out None values
        valid_versions = {k: v for k, v in versions.items() if v is not None}

        if not valid_versions:
            print(f"{Colors.FAIL}Error: Could not find version in any file{Colors.ENDC}")
            print(f"Expected version in {changelog_name}, manifest.json, or Info.json/.mod.json")
            raise typer.Exit(1)

        # Find the highest version
        highest_version = None
        highest_source = None
        for source, ver in valid_versions.items():
            if highest_version is None or compare_versions(ver, highest_version) > 0:
                highest_version = ver
                highest_source = source

        version = highest_version

        # Show version info
        print(f"{Colors.CYAN}Package version: {version}{Colors.ENDC}")

        # Only warn if Changelog is behind (user forgot to update it)
        if changelog_version and compare_versions(changelog_version, version) < 0:
            print(f"\n{Colors.WARNING}Warning: {changelog_name} is out of date!{Colors.ENDC}")
            print(f"{Colors.CYAN}Changelog version: {changelog_version}{Colors.ENDC}")
            print(f"{Colors.CYAN}Highest version found: {version} (from {highest_source}){Colors.ENDC}")
            print(f"\n{Colors.WARNING}Did you forget to update {changelog_name}?{Colors.ENDC}")

            continue_package = questionary.confirm(
                f"Continue packaging with version {version}?",
                default=False
            ).ask()

            if continue_package is None or not continue_package:
                print(f"\n{Colors.CYAN}Packaging cancelled.{Colors.ENDC}")
                print(f"Update {changelog_name} to version {version} before packaging.")
                raise typer.Exit()

    # Load and update manifest
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest_data = json.load(f)

    namespace = manifest_data.get('author', 'Unknown')
    package_name = manifest_data.get('name', project_name.replace(' ', '_'))

    # Check for missing author
    if namespace == 'Unknown' or not namespace:
        print(f"\n{Colors.WARNING}Warning: No author/namespace set in manifest.json{Colors.ENDC}")
        print(f"{Colors.CYAN}The author field is used for the package filename and Thunderstore namespace.{Colors.ENDC}")

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

    # Check for outdated dependencies
    current_deps = manifest_data.get('dependencies', [])
    outdated_deps = []
    updated_deps = []

    for dep in current_deps:
        # Parse dependency string: "Namespace-PackageName-Version"
        parts = dep.rsplit('-', 1)
        if len(parts) == 2:
            dep_name_part, dep_version = parts
            # Check against known dependencies
            for dep_key, current_dep_string in DEPENDENCIES.items():
                if current_dep_string.startswith(dep_name_part + '-'):
                    # This is a known dependency, check version
                    if dep != current_dep_string:
                        outdated_deps.append((dep, current_dep_string))
                        updated_deps.append(current_dep_string)
                    else:
                        updated_deps.append(dep)
                    break
            else:
                # Unknown dependency, keep as-is
                updated_deps.append(dep)
        else:
            # Malformed dependency string, keep as-is
            updated_deps.append(dep)

    # Prompt to update if outdated dependencies found
    if outdated_deps:
        print(f"\n{Colors.WARNING}Outdated dependencies detected:{Colors.ENDC}")
        for old_dep, new_dep in outdated_deps:
            print(f"  {old_dep} → {new_dep}")

        update = questionary.confirm(
            "Update dependencies to latest versions?",
            default=True
        ).ask()

        if update is None:
            raise typer.Exit()
        elif update:
            manifest_data['dependencies'] = updated_deps
            print(f"{Colors.GREEN}Dependencies updated{Colors.ENDC}")
        else:
            print(f"{Colors.CYAN}Keeping existing dependency versions{Colors.ENDC}")
    else:
        # No outdated deps, use current deps for further checks
        updated_deps = current_deps

    # Check for missing dependencies (detected in .csproj but not in manifest)
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

        add_deps = questionary.confirm(
            "Add missing dependencies to manifest?",
            default=True
        ).ask()

        if add_deps is None:
            raise typer.Exit()
        elif add_deps:
            # Add missing dependencies to the list
            if updated_deps:
                updated_deps.extend(missing_deps)
            else:
                updated_deps = list(current_dep_set) + missing_deps
            manifest_data['dependencies'] = updated_deps
            print(f"{Colors.GREEN}Missing dependencies added{Colors.ENDC}")
        else:
            print(f"{Colors.CYAN}Continuing without adding missing dependencies{Colors.ENDC}")

    # Update manifest version
    old_manifest_version = manifest_data.get('version_number', None)
    manifest_data['version_number'] = version

    # Write updated manifest back to file
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f, indent=2)

    # Only show message if version actually changed
    if old_manifest_version != version:
        print(f"{Colors.GREEN}Updated manifest.json version to {version}{Colors.ENDC}")
    else:
        print(f"{Colors.BLUE}manifest.json already at version {version}{Colors.ENDC}")

    # Sync version in Info.json (mods) or .mod.json (bros)
    updated, version_file_path = sync_version_file(modcontent_path, project_type, version)
    if updated:
        version_file_name = os.path.basename(version_file_path)
        print(f"{Colors.GREEN}Updated {version_file_name} version to {version}{Colors.ENDC}")
    elif version_file_path:
        version_file_name = os.path.basename(version_file_path)
        print(f"{Colors.BLUE}{version_file_name} already at version {version}{Colors.ENDC}")
    else:
        # Couldn't find version file - warn but continue
        version_file_name = 'Info.json' if project_type == 'mod' else '.mod.json'
        print(f"{Colors.WARNING}Warning: Could not find {version_file_name} to sync version{Colors.ENDC}")

    # For bros, check if BroMakerVersion is outdated
    if project_type == 'bro' and version_file_path:
        try:
            with open(version_file_path, 'r', encoding='utf-8') as f:
                mod_json_data = json.load(f)

            current_bromaker_version = mod_json_data.get('BroMakerVersion', None)
            if current_bromaker_version:
                latest_bromaker_version = DEPENDENCY_VERSIONS.get('BroMaker', current_bromaker_version)

                if current_bromaker_version != latest_bromaker_version:
                    print(f"\n{Colors.WARNING}Outdated BroMakerVersion in {os.path.basename(version_file_path)}:{Colors.ENDC}")
                    print(f"  {current_bromaker_version} → {latest_bromaker_version}")

                    update_bromaker = questionary.confirm(
                        "Update BroMakerVersion to latest?",
                        default=True
                    ).ask()

                    if update_bromaker is None:
                        raise typer.Exit()
                    elif update_bromaker:
                        mod_json_data['BroMakerVersion'] = latest_bromaker_version
                        with open(version_file_path, 'w', encoding='utf-8') as f:
                            json.dump(mod_json_data, f, indent=2)
                        print(f"{Colors.GREEN}Updated BroMakerVersion to {latest_bromaker_version}{Colors.ENDC}")
        except (json.JSONDecodeError, OSError):
            pass  # Silently continue if we can't read/parse the file

    # Create package filename
    zip_filename = f"{namespace}-{package_name}-{version}.zip"
    zip_path = os.path.join(releases_path, zip_filename)

    # Check if package with this exact version already exists
    if os.path.exists(zip_path):
        print(f"\n{Colors.WARNING}Package {zip_filename} already exists{Colors.ENDC}")

        # Prompt user to confirm overwrite
        overwrite = questionary.confirm(
            "Overwrite existing package?",
            default=True
        ).ask()

        if overwrite is None:
            raise typer.Exit()
        elif not overwrite:
            print(f"\n{Colors.CYAN}Packaging cancelled.{Colors.ENDC}")
            print(f"To create a new package, update the version in {changelog_name}")
            raise typer.Exit()

        # User confirmed - delete old package (don't archive it)
        os.remove(zip_path)
        print(f"{Colors.BLUE}Removed existing package{Colors.ENDC}")
    else:
        # New version - archive old packages
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

    # Create temporary directory for package structure
    with tempfile.TemporaryDirectory() as temp_dir:
        # Copy metadata files to root
        shutil.copy2(manifest_path, os.path.join(temp_dir, 'manifest.json'))
        shutil.copy2(readme_path, os.path.join(temp_dir, 'README.md'))
        shutil.copy2(icon_path, os.path.join(temp_dir, 'icon.png'))

        # Strip (unreleased) tag from Changelog
        with open(changelog_path, 'r', encoding='utf-8') as f:
            changelog_content = f.read()

        # Strip (unreleased) from version headers
        changelog_cleaned = re.sub(
            r'(##\s*v?\d+\.\d+\.\d+:?)\s*\(unreleased\)',
            r'\1',
            changelog_content,
            flags=re.IGNORECASE
        )

        # Update source changelog if it was modified
        if changelog_cleaned != changelog_content:
            with open(changelog_path, 'w', encoding='utf-8') as f:
                f.write(changelog_cleaned)
            print(f"{Colors.GREEN}Removed (unreleased) tag from {changelog_name}{Colors.ENDC}")

        # Copy cleaned changelog to package
        with open(os.path.join(temp_dir, 'CHANGELOG.md'), 'w', encoding='utf-8') as f:
            f.write(changelog_cleaned)

        # Create UMM structure
        umm_base = os.path.join(temp_dir, 'UMM')
        if project_type == 'mod':
            target_dir = os.path.join(umm_base, 'Mods', project_name)
        else:  # bro
            target_dir = os.path.join(umm_base, 'BroMaker_Storage', project_name)

        os.makedirs(target_dir, exist_ok=True)

        # Copy _ModContent contents
        copyanything(modcontent_path, target_dir)

        # Create ZIP
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arcname)

    # Get ZIP size
    zip_size = os.path.getsize(zip_path) / 1024  # KB

    # Success summary
    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ Package created!{Colors.ENDC}")
    print(f"{Colors.CYAN}Version:{Colors.ENDC} {version}")
    print(f"{Colors.CYAN}File:{Colors.ENDC} {zip_path}")
    print(f"{Colors.CYAN}Size:{Colors.ENDC} {zip_size:.1f} KB")
    print(f"\n{Colors.CYAN}Package ready for Thunderstore upload!{Colors.ENDC}")

def do_create_project(template_type: Optional[str], name: Optional[str], author: Optional[str], output_repo: Optional[str]):
    """Create a new mod or bro project from templates"""
    import filecmp

    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_repo_dir = os.path.dirname(script_dir)
    repos_parent = os.path.dirname(template_repo_dir)

    # Determine output repository
    if output_repo:
        output_repo_name = output_repo
        print(f"{Colors.BLUE}Using output repository: {output_repo_name}{Colors.ENDC}")
    else:
        # Build repo choices
        current_repo = detect_current_repo(repos_parent)
        configured_repos = get_configured_repos()

        choices = []

        # Add current repo first if we're in one
        if current_repo:
            choices.append(f"{current_repo} (current directory)")

        # Add other configured repos (excluding current if already added)
        for repo in configured_repos:
            if repo != current_repo:
                choices.append(repo)

        # Always add manual entry option
        choices.append("Enter another repository name...")

        selection = questionary.select(
            "Select output repository:",
            choices=choices
        ).ask()

        if not selection:  # User cancelled
            raise typer.Exit()

        if selection == "Enter another repository name...":
            output_repo_name = questionary.text(
                "Enter repository name:"
            ).ask()
            if not output_repo_name:
                print(f"{Colors.FAIL}Error: Repository name cannot be empty.{Colors.ENDC}")
                raise typer.Exit(1)
        elif selection.endswith(" (current directory)"):
            output_repo_name = current_repo
        else:
            output_repo_name = selection

        print(f"{Colors.BLUE}Using output repository: {output_repo_name}{Colors.ENDC}")

    # Get project type
    if template_type:
        pass  # Already have it
    else:
        choice = questionary.select(
            "What would you like to create?",
            choices=["Mod", "Bro"]
        ).ask()

        if not choice:  # User cancelled
            raise typer.Exit()

        template_type = choice.lower()

    # Set template parameters based on type
    if template_type == "mod":
        source_template_name = "Mod Template"
    else:
        source_template_name = "Bro Template"

    # Get the name for the new template
    if name:
        newName = name
    else:
        newName = questionary.text(f"Enter {template_type} name:").ask()
        if not newName:
            print(f"{Colors.FAIL}Error: Name cannot be empty.{Colors.ENDC}")
            raise typer.Exit(1)

    newNameWithUnderscore = newName.replace(' ', '_')
    newNameNoSpaces = newName.replace(' ', '')

    # Get the author name
    if author:
        authorName = author
    else:
        authorName = questionary.text("Enter author name (e.g., YourName):").ask()
        if not authorName:
            print(f"{Colors.FAIL}Error: Author name cannot be empty.{Colors.ENDC}")
            raise typer.Exit(1)

    # Define paths
    templatePath = os.path.join(template_repo_dir, source_template_name)
    output_repo_path = os.path.join(repos_parent, output_repo_name)

    # Check if output repository exists
    if not os.path.exists(output_repo_path):
        print(f"{Colors.FAIL}Error: Output repository does not exist: {output_repo_path}{Colors.ENDC}")
        print(f"{Colors.WARNING}Please ensure the repository '{output_repo_name}' exists in: {repos_parent}{Colors.ENDC}")
        raise typer.Exit(1)

    # Copy BroforceModBuild.targets to output repo Scripts folder (if different repo)
    if output_repo_path != template_repo_dir:
        output_scripts_dir = os.path.join(output_repo_path, 'Scripts')
        if not os.path.exists(output_scripts_dir):
            os.makedirs(output_scripts_dir)
            print(f"{Colors.GREEN}Created Scripts directory: {output_scripts_dir}{Colors.ENDC}")

        targets_source = os.path.join(script_dir, 'BroforceModBuild.targets')
        targets_dest = os.path.join(output_scripts_dir, 'BroforceModBuild.targets')

        if os.path.exists(targets_source):
            try:
                # Only copy if destination doesn't exist or is different
                if not os.path.exists(targets_dest):
                    shutil.copy2(targets_source, targets_dest)
                    print(f"{Colors.GREEN}Copied BroforceModBuild.targets to output repository{Colors.ENDC}")
                else:
                    # Check if files are identical
                    if not filecmp.cmp(targets_source, targets_dest, shallow=False):
                        try:
                            shutil.copy2(targets_source, targets_dest)
                            print(f"{Colors.GREEN}Updated BroforceModBuild.targets in output repository{Colors.ENDC}")
                        except PermissionError:
                            print(f"{Colors.WARNING}Warning: Could not update BroforceModBuild.targets (file in use){Colors.ENDC}")
                    else:
                        print(f"{Colors.BLUE}BroforceModBuild.targets already up-to-date{Colors.ENDC}")
            except PermissionError:
                print(f"{Colors.WARNING}Warning: Could not copy BroforceModBuild.targets (file in use){Colors.ENDC}")
        else:
            print(f"{Colors.WARNING}Warning: BroforceModBuild.targets not found in template repo{Colors.ENDC}")

    # Create the release folder structure in output repo
    releasesPath = os.path.join(output_repo_path, 'Releases')
    newReleaseFolder = os.path.join(releasesPath, newName)
    newRepoPath = os.path.join(output_repo_path, newName)

    # Check if template directory exists
    if not os.path.exists(templatePath):
        print(f"{Colors.FAIL}Error: Template directory not found: {templatePath}{Colors.ENDC}")
        print(f"Please ensure the '{source_template_name}' directory exists in your repository.")
        raise typer.Exit(1)

    # Create Releases directory if it doesn't exist
    if not os.path.exists(releasesPath):
        try:
            os.makedirs(releasesPath)
            print(f"{Colors.GREEN}Created Releases directory: {releasesPath}{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.FAIL}Error: Failed to create Releases directory: {e}{Colors.ENDC}")
            raise typer.Exit(1)

    # Check if destination directories already exist
    if os.path.exists(newReleaseFolder):
        print(f"{Colors.FAIL}Error: Release directory already exists: {newReleaseFolder}{Colors.ENDC}")
        print(f"Please choose a different {template_type} name or remove the existing directory.")
        raise typer.Exit(1)

    if os.path.exists(newRepoPath):
        print(f"{Colors.FAIL}Error: Repository directory already exists: {newRepoPath}{Colors.ENDC}")
        print(f"Please choose a different {template_type} name or remove the existing directory.")
        raise typer.Exit(1)

    try:
        # Create the release folder
        os.makedirs(newReleaseFolder)
        # Copy the source template to the repo
        copyanything(templatePath, newRepoPath)
    except Exception as e:
        print(f"{Colors.FAIL}Error: Failed to copy template files: {e}{Colors.ENDC}")
        # Clean up partially created directories
        if os.path.exists(newReleaseFolder):
            shutil.rmtree(newReleaseFolder)
        if os.path.exists(newRepoPath):
            shutil.rmtree(newRepoPath)
        raise typer.Exit(1)

    try:
        # Rename files named with template name (with space)
        renameFiles(newRepoPath, source_template_name, newName)

        # Also rename files named without space
        if template_type == "mod":
            renameFiles(newRepoPath, 'ModTemplate', newNameNoSpaces)
        else:
            renameFiles(newRepoPath, 'BroTemplate', newNameNoSpaces)

        # File types to process
        if template_type == "mod":
            fileTypes = ["*.csproj", "*.cs", "*.sln", "*.json", "*.xml"]
        else:
            fileTypes = ["*.csproj", "*.cs", "*.sln", "*.json"]

        for fileType in fileTypes:
            # Replace template names
            findReplace(newRepoPath, source_template_name, newName, fileType)
            findReplace(newRepoPath, source_template_name.replace(' ', '_'), newNameWithUnderscore, fileType)
            if template_type == "mod":
                findReplace(newRepoPath, "ModTemplate", newNameNoSpaces, fileType)
            else:
                findReplace(newRepoPath, "BroTemplate", newNameNoSpaces, fileType)

            # Replace author placeholder
            findReplace(newRepoPath, "AUTHOR_NAME", authorName, fileType)

            # Replace repository URL with output repository name
            findReplace(newRepoPath, "REPO_NAME", output_repo_name, fileType)

        # Special handling for .csproj file references for Bros
        if template_type == "bro":
            findReplace(newRepoPath, "BroTemplate.cs", f"{newNameNoSpaces}.cs", "*.csproj")

            # Get BroMaker version from Thunderstore API (cached)
            dep_versions = get_dependency_versions()
            bromaker_version = dep_versions.get('BroMaker', '2.6.0')

            # Replace BroMaker version placeholder
            findReplace(newRepoPath, "BROMAKER_VERSION", bromaker_version, "*.json")

        # Create the Changelog.md file in the Releases folder
        changelogPath = os.path.join(newReleaseFolder, 'Changelog.md')
        changelogContent = '''## v1.0.0 (unreleased)
- Initial release
'''

        with open(changelogPath, 'w', encoding='utf-8') as changelogFile:
            changelogFile.write(changelogContent)

        print(f"\n{Colors.GREEN}{Colors.BOLD}Success! Created new {template_type} '{newName}'{Colors.ENDC}")
        if output_repo:
            print(f"{Colors.CYAN}Output repository:{Colors.ENDC} {output_repo_name}")
        print(f"{Colors.CYAN}Source files:{Colors.ENDC} {newRepoPath}")
        print(f"{Colors.CYAN}Releases folder:{Colors.ENDC} {newReleaseFolder}")

        # Ask if user wants to set up Thunderstore metadata
        setup_thunderstore = questionary.confirm(
            "Set up Thunderstore metadata now?",
            default=True
        ).ask()

        if setup_thunderstore is None:
            raise typer.Exit()
        elif setup_thunderstore:
            print()
            do_init_thunderstore(newName, script_dir, repos_parent)
        else:
            print(f"\n{Colors.CYAN}Next steps:{Colors.ENDC}")
            print(f"  1. Open the project in Visual Studio")
            print(f"  2. Build the project (builds to game automatically)")
            print(f"  3. Launch Broforce to test your {template_type}")
            print(f"  4. Run 'bt init-thunderstore' when ready to publish")

    except Exception as e:
        print(f"{Colors.FAIL}Error: Failed during file processing: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


# Typer CLI application
app = typer.Typer(
    help="Tool for creating Broforce mods and packaging for Thunderstore",
    add_completion=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _get_paths():
    """Get common paths used by commands"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_repo_dir = os.path.dirname(script_dir)
    repos_parent = os.path.dirname(template_repo_dir)
    return script_dir, template_repo_dir, repos_parent


def _get_repos_for_completion(repos_parent: str) -> list[str]:
    """Get repos to use for completion - current repo if inside one, otherwise all configured repos"""
    current_repo = detect_current_repo(repos_parent)
    if current_repo:
        return [current_repo]
    config = load_config()
    return config.get('repos', [])


def _escape_for_completion(name: str) -> str:
    """Quote project names with spaces for shell completion display"""
    if ' ' in name:
        return f'"{name}"'
    return name


def _complete_project_names_without_metadata(incomplete: str) -> list[str]:
    """Autocompletion for project names (only projects WITHOUT Thunderstore metadata)"""
    _, _, repos_parent = _get_paths()
    repos = _get_repos_for_completion(repos_parent)
    projects = find_projects(repos_parent, repos, exclude_with_metadata=True)
    return [_escape_for_completion(p[0]) for p in projects]


def _complete_project_names_with_metadata(incomplete: str) -> list[str]:
    """Autocompletion for project names (only projects with Thunderstore metadata)"""
    _, _, repos_parent = _get_paths()
    repos = _get_repos_for_completion(repos_parent)
    projects = find_projects(repos_parent, repos, require_metadata=True)
    return [_escape_for_completion(p[0]) for p in projects]


def _complete_project_type(incomplete: str) -> list[str]:
    """Autocompletion for project type (mod or bro)"""
    types = ["mod", "bro"]
    return [t for t in types if t.startswith(incomplete.lower())]


def _complete_repos(incomplete: str) -> list[str]:
    """Autocompletion for repository names"""
    config = load_config()
    repos = config.get('repos', [])
    return [r for r in repos if r.lower().startswith(incomplete.lower())]


def _complete_none(incomplete: str) -> list[str]:
    """Return empty list to prevent file completion fallback"""
    return []


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    clear_cache: bool = typer.Option(False, "--clear-cache", help="Clear dependency version cache"),
    add_repo: Optional[str] = typer.Option(None, "--add-repo", help="Add repo to config (uses current if empty string)", autocompletion=_complete_none),
):
    """Tool for creating Broforce mods and packaging for Thunderstore."""
    script_dir, template_repo_dir, repos_parent = _get_paths()

    # Handle --clear-cache flag
    if clear_cache:
        if os.path.exists(CACHE_FILE):
            try:
                os.remove(CACHE_FILE)
                print(f"{Colors.GREEN}Dependency cache cleared: {CACHE_FILE}{Colors.ENDC}")
            except OSError as e:
                print(f"{Colors.FAIL}Error clearing cache: {e}{Colors.ENDC}")
                raise typer.Exit(1)
        else:
            print(f"{Colors.BLUE}Cache file does not exist: {CACHE_FILE}{Colors.ENDC}")
        raise typer.Exit()

    # Handle --add-repo flag
    if add_repo is not None:
        # Determine repo name to add
        if add_repo == '':
            # No argument provided, detect from current directory
            repo_name = detect_current_repo(repos_parent)
            if not repo_name:
                print(f"{Colors.FAIL}Error: Could not detect current repo from working directory{Colors.ENDC}")
                print(f"Run from within a repo directory, or specify repo name: --add-repo RepoName")
                raise typer.Exit(1)
        else:
            repo_name = add_repo

        # Load current config and add repo
        config = load_config()
        repos = config.get('repos', [])

        if repo_name in repos:
            print(f"{Colors.BLUE}'{repo_name}' is already in configured repos{Colors.ENDC}")
        else:
            repos.append(repo_name)
            config['repos'] = repos
            if save_config(config):
                print(f"{Colors.GREEN}Added '{repo_name}' to configured repos{Colors.ENDC}")
            else:
                print(f"{Colors.FAIL}Error: Failed to save config file{Colors.ENDC}")
                raise typer.Exit(1)

        print(f"\n{Colors.CYAN}Configured repos:{Colors.ENDC}")
        for r in repos:
            print(f"  - {r}")
        raise typer.Exit()

    # If no subcommand, show interactive menu
    if ctx.invoked_subcommand is None:
        print(f"{Colors.HEADER}Broforce Mod Tools{Colors.ENDC}\n")

        choice = questionary.select(
            "What would you like to do?",
            choices=[
                "Create new mod / bro project",
                "Setup Thunderstore metadata for an existing project",
                "Package for releasing on Thunderstore",
                "Show help"
            ]
        ).ask()

        if not choice:  # User cancelled
            raise typer.Exit()

        if choice == "Show help":
            # Show help by invoking --help
            print(ctx.get_help())
            raise typer.Exit()
        elif choice == "Create new mod / bro project":
            do_create_project(None, None, None, None)
        elif choice == "Setup Thunderstore metadata for an existing project":
            selected = select_projects_interactive(repos_parent, 'init', use_all_repos=False)
            if not selected:
                raise typer.Exit()
            for project_name, repo in selected:
                if len(selected) > 1:
                    print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
                do_init_thunderstore(project_name, script_dir, repos_parent)
        elif choice == "Package for releasing on Thunderstore":
            selected = select_projects_interactive(repos_parent, 'package', use_all_repos=False)
            if not selected:
                raise typer.Exit()
            for project_name, repo in selected:
                if len(selected) > 1:
                    print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
                do_package(project_name, script_dir, repos_parent, None)


@app.command()
def create(
    type: Optional[str] = typer.Option(None, "-t", "--type", help="Project type: mod or bro", autocompletion=_complete_project_type),
    name: Optional[str] = typer.Option(None, "-n", "--name", help="Project name", autocompletion=_complete_none),
    author: Optional[str] = typer.Option(None, "-a", "--author", help="Author name", autocompletion=_complete_none),
    output_repo: Optional[str] = typer.Option(None, "-o", "--output-repo", help="Target repository", autocompletion=_complete_repos),
):
    """Create a new mod or bro project from templates."""
    do_create_project(type, name, author, output_repo)


@app.command("init-thunderstore")
def init_thunderstore_cmd(
    project_name: Optional[str] = typer.Argument(None, help="Project name (optional)", autocompletion=_complete_project_names_without_metadata),
    all_repos: bool = typer.Option(False, "--all-repos", help="Show projects from all configured repos"),
):
    """Initialize Thunderstore metadata for an existing project."""
    script_dir, template_repo_dir, repos_parent = _get_paths()

    if project_name:
        do_init_thunderstore(project_name, script_dir, repos_parent)
    else:
        selected = select_projects_interactive(repos_parent, 'init', use_all_repos=all_repos)
        if not selected:
            raise typer.Exit()
        for proj_name, repo in selected:
            if len(selected) > 1:
                print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
            do_init_thunderstore(proj_name, script_dir, repos_parent)


@app.command()
def package(
    project_name: Optional[str] = typer.Argument(None, help="Project name (optional)", autocompletion=_complete_project_names_with_metadata),
    version: Optional[str] = typer.Option(None, "--version", help="Override version", autocompletion=_complete_none),
    all_repos: bool = typer.Option(False, "--all-repos", help="Show projects from all configured repos"),
):
    """Create a Thunderstore-ready ZIP package."""
    script_dir, template_repo_dir, repos_parent = _get_paths()

    if project_name:
        do_package(project_name, script_dir, repos_parent, version)
    else:
        selected = select_projects_interactive(repos_parent, 'package', use_all_repos=all_repos)
        if not selected:
            raise typer.Exit()
        for proj_name, repo in selected:
            if len(selected) > 1:
                print(f"\n{Colors.HEADER}{'='*50}{Colors.ENDC}")
            do_package(proj_name, script_dir, repos_parent, version)


def main():
    """Entry point for the CLI"""
    app()


if __name__ == "__main__":
    main()

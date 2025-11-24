import shutil, errno
import os, fnmatch
import sys
import re
import argparse
import json
import xml.etree.ElementTree as ET
import time
import tempfile

try:
    import questionary
except ImportError:
    questionary = None

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
    'BroMaker': '1.0.0',  # Placeholder - not yet uploaded
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
    path = input("Enter Broforce installation path: ").strip()
    if not os.path.exists(path):
        print(f"{Colors.FAIL}Error: Path does not exist: {path}{Colors.ENDC}")
        sys.exit(1)
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

    # Find .csproj file
    csproj_files = []
    for root, dirs, files in os.walk(project_path):
        for file in files:
            if file.endswith('.csproj'):
                csproj_files.append(os.path.join(root, file))
        # Only check first level
        break

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

def get_version_from_changelog(changelog_path):
    """Parse version from Changelog.md"""
    if not os.path.exists(changelog_path):
        return None

    try:
        with open(changelog_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Try patterns in order of preference
        patterns = [
            r'##\s*v?(\d+\.\d+\.\d+)\s*\(unreleased\)',  # ## v1.0.0 (unreleased)
            r'##\s*v?(\d+\.\d+\.\d+)',  # ## v1.0.0 or ## 1.0.0
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                return match.group(1)

        return None
    except Exception as e:
        print(f"{Colors.WARNING}Warning: Could not parse Changelog.md: {e}{Colors.ENDC}")
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
    if cwd_abs.startswith('c:/'):
        cwd_abs = '/mnt/c/' + cwd_abs[3:]
    elif cwd_abs.startswith('/mnt/c/'):
        cwd_abs_alt = 'c:/' + cwd_abs[7:]
    else:
        cwd_abs_alt = None

    if repos_abs.startswith('c:/'):
        repos_abs = '/mnt/c/' + repos_abs[3:]
    elif repos_abs.startswith('/mnt/c/'):
        repos_abs_alt = 'c:/' + repos_abs[7:]
    else:
        repos_abs_alt = None

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

def find_all_projects(repos_parent, require_thunderstore_metadata=False, filter_repo=None):
    """Find all valid projects across all repos (or filtered to one repo)

    Handles two repo structures:
    1. Multi-project repos: {repo}/Releases/{project}/ (e.g., BroforceMods)
    2. Single-project repos: {repo}/Release/ (e.g., RocketLib, BroMaker)

    Args:
        repos_parent: Parent directory containing all repos
        require_thunderstore_metadata: If True, only return projects with manifest.json
        filter_repo: If provided, only search this repo name
    """
    projects = []

    # Get all repos in parent directory
    try:
        if filter_repo:
            repos = [filter_repo]
        else:
            repos = [d for d in os.listdir(repos_parent) if os.path.isdir(os.path.join(repos_parent, d))]
    except (OSError, FileNotFoundError):
        return projects

    # Search each repo for projects
    for repo in repos:
        repo_path = os.path.join(repos_parent, repo)

        # Skip if repo doesn't exist
        if not os.path.exists(repo_path):
            continue

        # Check for single-project repo structure: {repo}/Release/
        release_dir = os.path.join(repo_path, 'Release')
        if os.path.exists(release_dir) and os.path.isdir(release_dir):
            # Single-project repo: find the actual project directory
            # First try repo name (e.g., RocketLib/RocketLib/)
            project_name = repo
            project_path = os.path.join(repo_path, project_name)

            # If that doesn't exist, search for directories with _ModContent
            if not os.path.exists(project_path):
                try:
                    for item in os.listdir(repo_path):
                        item_path = os.path.join(repo_path, item)
                        if os.path.isdir(item_path):
                            modcontent_path = os.path.join(item_path, '_ModContent')
                            if os.path.exists(modcontent_path):
                                project_name = item
                                project_path = item_path
                                break
                except (OSError, FileNotFoundError):
                    pass

            # Verify we found a valid project
            if os.path.exists(project_path) and os.path.isdir(project_path):
                # If requiring Thunderstore metadata, check for manifest.json
                if require_thunderstore_metadata:
                    manifest_path = os.path.join(release_dir, 'manifest.json')
                    if os.path.exists(manifest_path):
                        projects.append((project_name, repo))
                else:
                    projects.append((project_name, repo))

        # Check for multi-project repo structure: {repo}/Releases/{project}/
        releases_dir = os.path.join(repo_path, 'Releases')
        if os.path.exists(releases_dir):
            # Multi-project repo
            try:
                for item in os.listdir(releases_dir):
                    release_path = os.path.join(releases_dir, item)
                    if not os.path.isdir(release_path):
                        continue

                    # Check if corresponding project directory exists
                    project_path = os.path.join(repo_path, item)
                    if not os.path.exists(project_path) or not os.path.isdir(project_path):
                        continue

                    # If requiring Thunderstore metadata, check for manifest.json
                    if require_thunderstore_metadata:
                        manifest_path = os.path.join(release_path, 'manifest.json')
                        if not os.path.exists(manifest_path):
                            continue

                    projects.append((item, repo))
            except (OSError, FileNotFoundError):
                continue

    # Sort by project name
    return sorted(projects, key=lambda x: x[0])

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
        sys.exit(1)

    print(f"{Colors.GREEN}Found project in: {output_repo}{Colors.ENDC}")

    # Detect project type
    project_type = detect_project_type(project_path)
    if not project_type:
        print(f"{Colors.FAIL}Error: Could not detect project type (no _ModContent or missing detection files){Colors.ENDC}")
        sys.exit(1)

    print(f"{Colors.BLUE}Detected project type: {project_type}{Colors.ENDC}")

    # Prompt for Thunderstore metadata
    print(f"\n{Colors.HEADER}Enter Thunderstore package information:{Colors.ENDC}")

    # Namespace
    namespace = input(f"{Colors.CYAN}Namespace/Author (e.g., AlexNeargarder): {Colors.ENDC}").strip()
    valid, msg = validate_package_name(namespace)
    if not valid:
        print(f"{Colors.FAIL}Error: Invalid namespace - {msg}{Colors.ENDC}")
        sys.exit(1)

    # Package name
    suggested_name = sanitize_package_name(project_name)
    package_name = input(f"{Colors.CYAN}Package name [{suggested_name}]: {Colors.ENDC}").strip() or suggested_name
    valid, msg = validate_package_name(package_name)
    if not valid:
        print(f"{Colors.FAIL}Error: Invalid package name - {msg}{Colors.ENDC}")
        sys.exit(1)

    # Description
    description = input(f"{Colors.CYAN}Description (max 250 chars): {Colors.ENDC}").strip()
    if len(description) > 250:
        print(f"{Colors.WARNING}Warning: Description truncated to 250 characters{Colors.ENDC}")
        description = description[:250]

    # Website URL
    website_url = input(f"{Colors.CYAN}Website/GitHub URL: {Colors.ENDC}").strip()

    # Check if Changelog.md exists, create if missing
    changelog_path = os.path.join(releases_path, 'Changelog.md')
    if not os.path.exists(changelog_path):
        print(f"{Colors.WARNING}Changelog.md not found, creating default{Colors.ENDC}")
        with open(changelog_path, 'w', encoding='utf-8') as f:
            f.write('## v1.0.0 (unreleased)\n- Initial release\n')

    # Detect dependencies from .csproj
    detected_deps = detect_dependencies_from_csproj(project_path)
    if len(detected_deps) > 1:  # More than just UMM
        print(f"{Colors.CYAN}Detected dependencies:{Colors.ENDC}")
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

    # Copy README template
    readme_template = os.path.join(template_repo_dir, 'ThunderstorePackage', 'README.md')
    readme_dest = os.path.join(releases_path, 'README.md')

    if os.path.exists(readme_template):
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

    # Copy icon placeholder
    icon_template = os.path.join(template_repo_dir, 'ThunderstorePackage', 'icon.png')
    icon_dest = os.path.join(releases_path, 'icon.png')

    if os.path.exists(icon_template):
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
    print(f"  4. Run: python create-project.py package \"{project_name}\"")

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
        sys.exit(1)

    # Validate metadata exists
    manifest_path = os.path.join(releases_path, 'manifest.json')
    readme_path = os.path.join(releases_path, 'README.md')
    icon_path = os.path.join(releases_path, 'icon.png')
    changelog_path = os.path.join(releases_path, 'Changelog.md')

    if not os.path.exists(manifest_path):
        print(f"{Colors.FAIL}Error: manifest.json not found{Colors.ENDC}")
        print(f"Run: python create-project.py init-thunderstore \"{project_name}\"")
        sys.exit(1)

    if not os.path.exists(readme_path):
        print(f"{Colors.FAIL}Error: README.md not found{Colors.ENDC}")
        sys.exit(1)

    if not os.path.exists(icon_path):
        print(f"{Colors.FAIL}Error: icon.png not found{Colors.ENDC}")
        sys.exit(1)

    # Detect project type
    project_type = detect_project_type(project_path)
    if not project_type:
        print(f"{Colors.FAIL}Error: Could not detect project type{Colors.ENDC}")
        sys.exit(1)

    # Validate DLL exists
    source_dir = get_source_directory(project_path)
    if not source_dir:
        print(f"{Colors.FAIL}Error: Could not find source directory with _ModContent{Colors.ENDC}")
        sys.exit(1)

    modcontent_path = os.path.join(source_dir, '_ModContent')
    dll_path = find_dll_in_modcontent(modcontent_path)

    if not dll_path:
        print(f"{Colors.FAIL}Error: No DLL found in _ModContent{Colors.ENDC}")
        print(f"Build the project first")
        sys.exit(1)

    # Check if icon is placeholder
    icon_template = os.path.join(template_repo_dir, 'ThunderstorePackage', 'icon.png')
    if os.path.exists(icon_template) and filecmp.cmp(icon_path, icon_template, shallow=False):
        print(f"{Colors.WARNING}⚠️  Warning: Using placeholder icon{Colors.ENDC}")

    # Get version from all sources and find the highest
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
            'Changelog.md': changelog_version,
            'manifest.json': manifest_version,
            'Info.json/.mod.json': info_version
        }

        # Filter out None values
        valid_versions = {k: v for k, v in versions.items() if v is not None}

        if not valid_versions:
            print(f"{Colors.FAIL}Error: Could not find version in any file{Colors.ENDC}")
            print(f"Expected version in Changelog.md, manifest.json, or Info.json/.mod.json")
            sys.exit(1)

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
            print(f"\n{Colors.WARNING}Warning: Changelog.md is out of date!{Colors.ENDC}")
            print(f"{Colors.CYAN}Changelog version: {changelog_version}{Colors.ENDC}")
            print(f"{Colors.CYAN}Highest version found: {version} (from {highest_source}){Colors.ENDC}")
            print(f"\n{Colors.WARNING}Did you forget to update Changelog.md?{Colors.ENDC}")

            if questionary:
                continue_package = questionary.confirm(
                    f"Continue packaging with version {version}?",
                    default=False
                ).ask()
            else:
                response = input(f"\nContinue packaging with version {version}? (y/n): ").strip().lower()
                continue_package = response in ['y', 'yes']

            if not continue_package:
                print(f"\n{Colors.CYAN}Packaging cancelled.{Colors.ENDC}")
                print(f"Update Changelog.md to version {version} before packaging.")
                sys.exit(0)

    # Load and update manifest
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest_data = json.load(f)

    namespace = manifest_data.get('author', 'Unknown')
    package_name = manifest_data.get('name', project_name.replace(' ', '_'))

    # Check for missing author
    if namespace == 'Unknown' or not namespace:
        print(f"\n{Colors.WARNING}Warning: No author/namespace set in manifest.json{Colors.ENDC}")
        print(f"{Colors.CYAN}The author field is used for the package filename and Thunderstore namespace.{Colors.ENDC}")

        if questionary:
            set_author = questionary.confirm(
                "Set author name now?",
                default=True
            ).ask()
        else:
            response = input("\nSet author name now? (y/n): ").strip().lower()
            set_author = response in ['y', 'yes']

        if set_author:
            if questionary:
                namespace = questionary.text(
                    "Enter namespace/author (alphanumeric + underscores only):",
                    validate=lambda text: validate_package_name(text)[0]
                ).ask()
            else:
                while True:
                    namespace = input("Enter namespace/author (alphanumeric + underscores only): ").strip()
                    valid, msg = validate_package_name(namespace)
                    if valid:
                        break
                    print(f"{Colors.FAIL}Invalid: {msg}{Colors.ENDC}")

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

        if questionary:
            update = questionary.confirm(
                "Update dependencies to latest versions?",
                default=True
            ).ask()
        else:
            response = input("\nUpdate dependencies to latest versions? (y/n): ").strip().lower()
            update = response in ['y', 'yes']

        if update:
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

        if questionary:
            add_deps = questionary.confirm(
                "Add missing dependencies to manifest?",
                default=True
            ).ask()
        else:
            response = input("\nAdd missing dependencies to manifest? (y/n): ").strip().lower()
            add_deps = response in ['y', 'yes']

        if add_deps:
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

    # Create package filename
    zip_filename = f"{namespace}-{package_name}-{version}.zip"
    zip_path = os.path.join(releases_path, zip_filename)

    # Check if package with this exact version already exists
    if os.path.exists(zip_path):
        print(f"\n{Colors.WARNING}Package {zip_filename} already exists{Colors.ENDC}")

        # Prompt user to confirm overwrite
        if questionary:
            overwrite = questionary.confirm(
                "Overwrite existing package?",
                default=True
            ).ask()
        else:
            response = input("Overwrite existing package? (y/n): ").strip().lower()
            overwrite = response in ['y', 'yes']

        if not overwrite:
            print(f"\n{Colors.CYAN}Packaging cancelled.{Colors.ENDC}")
            print(f"To create a new package, update the version in Changelog.md")
            sys.exit(0)

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
            r'(##\s*v?\d+\.\d+\.\d+)\s*\(unreleased\)',
            r'\1',
            changelog_content,
            flags=re.IGNORECASE
        )

        # Update source Changelog.md if it was modified
        if changelog_cleaned != changelog_content:
            with open(changelog_path, 'w', encoding='utf-8') as f:
                f.write(changelog_cleaned)
            print(f"{Colors.GREEN}Removed (unreleased) tag from Changelog.md{Colors.ENDC}")

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

# Parse command line arguments
parser = argparse.ArgumentParser(
    description='Create Broforce mod/bro projects and Thunderstore packages',
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog='''Examples:
  # Interactive mode (shows menu)
  %(prog)s

  # Create new project
  %(prog)s create -t mod -n "My Mod" -a "MyName"
  %(prog)s create -t bro -n "My Bro" -a "MyName" -o "BroforceMods"

  # Initialize Thunderstore metadata
  %(prog)s init-thunderstore
  %(prog)s init-thunderstore "Project Name"

  # Package for Thunderstore
  %(prog)s package
  %(prog)s package "Project Name"
  %(prog)s package --version 1.2.3

  # Clear dependency version cache (force fresh API fetch on next run)
  %(prog)s --clear-cache
'''
)

# Global arguments
parser.add_argument('--clear-cache', action='store_true',
                    help='Clear the dependency version cache and exit')

subparsers = parser.add_subparsers(dest='command', help='Command to run')

# create subcommand
create_parser = subparsers.add_parser('create', help='Create new mod or bro project')
create_parser.add_argument('-t', '--type', choices=['mod', 'bro'], help='Project type (mod or bro)')
create_parser.add_argument('-n', '--name', help='Name of the mod or bro')
create_parser.add_argument('-a', '--author', help='Author name')
create_parser.add_argument('-o', '--output-repo', help='Name of the repository to output to (defaults to current repo)')

# init-thunderstore subcommand
init_parser = subparsers.add_parser('init-thunderstore', help='Initialize Thunderstore metadata for a project')
init_parser.add_argument('project_name', nargs='?', help='Name of the project (optional: auto-detect from current repo)')

# package subcommand
package_parser = subparsers.add_parser('package', help='Create Thunderstore package')
package_parser.add_argument('project_name', nargs='?', help='Name of the project (optional: auto-detect from current repo)')
package_parser.add_argument('--version', help='Override version (default: read from Changelog.md)')

args = parser.parse_args()

# Handle --clear-cache flag
if args.clear_cache:
    if os.path.exists(CACHE_FILE):
        try:
            os.remove(CACHE_FILE)
            print(f"{Colors.GREEN}Dependency cache cleared: {CACHE_FILE}{Colors.ENDC}")
        except OSError as e:
            print(f"{Colors.FAIL}Error clearing cache: {e}{Colors.ENDC}")
            sys.exit(1)
    else:
        print(f"{Colors.BLUE}Cache file does not exist: {CACHE_FILE}{Colors.ENDC}")
    sys.exit(0)

# Get paths needed by all modes
script_dir = os.path.dirname(os.path.abspath(__file__))
template_repo_dir = os.path.dirname(script_dir)
repos_parent = os.path.dirname(template_repo_dir)
template_repo_name = os.path.basename(template_repo_dir)

# Interactive mode - no command specified
if args.command is None:
    print(f"{Colors.HEADER}Broforce Mod Tools{Colors.ENDC}\n")

    # Use questionary for main menu if available
    if questionary:
        choice = questionary.select(
            "What would you like to do?",
            choices=[
                "Create new mod / bro project",
                "Setup Thunderstore metadata for an existing project",
                "Package for releasing on Thunderstore"
            ]
        ).ask()

        if not choice:  # User cancelled
            sys.exit(0)

        # Map selection to choice number
        if choice == "Create new mod / bro project":
            choice = "1"
        elif choice == "Setup Thunderstore metadata for an existing project":
            choice = "2"
        else:
            choice = "3"
    else:
        # Fallback if questionary not available
        print(f"{Colors.CYAN}What would you like to do?{Colors.ENDC}")
        print(f"{Colors.CYAN}1.{Colors.ENDC} Create new mod / bro project")
        print(f"{Colors.CYAN}2.{Colors.ENDC} Setup Thunderstore metadata for an existing project")
        print(f"{Colors.CYAN}3.{Colors.ENDC} Package for releasing on Thunderstore")
        choice = input("\nEnter your choice (1-3): ").strip()

    if choice == "1":
        # Set command to 'create' to continue to create project mode below
        args.command = 'create'
        args.type = None
        args.name = None
        args.author = None
        args.output_repo = None
    elif choice == "2":
        # Detect current repo
        current_repo = detect_current_repo(repos_parent)

        if not current_repo:
            print(f"{Colors.FAIL}Error: Please run this command from within a repo directory{Colors.ENDC}")
            print(f"(e.g., C:\\Users\\Alex\\repos\\BroforceMods\\)")
            sys.exit(1)

        # Find projects in current repo only
        projects = find_all_projects(repos_parent, filter_repo=current_repo)

        if not projects:
            print(f"{Colors.FAIL}Error: No projects found in {current_repo}{Colors.ENDC}")
            sys.exit(1)

        # Select project
        if questionary and len(projects) > 1:
            # Only show project names since they're all from same repo
            choices = [name for name, repo in projects]
            project_name = questionary.select(
                f"Select project from {current_repo}:",
                choices=choices
            ).ask()
            if not project_name:  # User cancelled
                sys.exit(0)
        elif len(projects) == 1:
            project_name = projects[0][0]
            print(f"{Colors.CYAN}Using project: {project_name}{Colors.ENDC}")
        else:
            # Fallback if questionary not available
            print(f"\n{Colors.CYAN}Available projects in {current_repo}:{Colors.ENDC}")
            for i, (name, repo) in enumerate(projects, 1):
                print(f"  {i}. {name}")
            selection = input(f"\nEnter project number (1-{len(projects)}): ").strip()
            try:
                idx = int(selection) - 1
                if 0 <= idx < len(projects):
                    project_name = projects[idx][0]
                else:
                    print(f"{Colors.FAIL}Invalid selection{Colors.ENDC}")
                    sys.exit(1)
            except ValueError:
                print(f"{Colors.FAIL}Invalid input{Colors.ENDC}")
                sys.exit(1)

        do_init_thunderstore(project_name, script_dir, repos_parent)
        sys.exit(0)
    elif choice == "3":
        # Detect current repo
        current_repo = detect_current_repo(repos_parent)

        if not current_repo:
            print(f"{Colors.FAIL}Error: Please run this command from within a repo directory{Colors.ENDC}")
            print(f"(e.g., C:\\Users\\Alex\\repos\\BroforceMods\\)")
            sys.exit(1)

        # Find projects with Thunderstore metadata in current repo only
        projects = find_all_projects(repos_parent, require_thunderstore_metadata=True, filter_repo=current_repo)

        if not projects:
            print(f"{Colors.FAIL}Error: No projects with Thunderstore metadata found in {current_repo}{Colors.ENDC}")
            print(f"Run option 2 to setup Thunderstore metadata for a project first")
            sys.exit(1)

        # Select project
        if questionary and len(projects) > 1:
            # Only show project names since they're all from same repo
            choices = [name for name, repo in projects]
            project_name = questionary.select(
                f"Select project from {current_repo}:",
                choices=choices
            ).ask()
            if not project_name:  # User cancelled
                sys.exit(0)
        elif len(projects) == 1:
            project_name = projects[0][0]
            print(f"{Colors.CYAN}Using project: {project_name}{Colors.ENDC}")
        else:
            # Fallback if questionary not available
            print(f"\n{Colors.CYAN}Available projects in {current_repo}:{Colors.ENDC}")
            for i, (name, repo) in enumerate(projects, 1):
                print(f"  {i}. {name}")
            selection = input(f"\nEnter project number (1-{len(projects)}): ").strip()
            try:
                idx = int(selection) - 1
                if 0 <= idx < len(projects):
                    project_name = projects[idx][0]
                else:
                    print(f"{Colors.FAIL}Invalid selection{Colors.ENDC}")
                    sys.exit(1)
            except ValueError:
                print(f"{Colors.FAIL}Invalid input{Colors.ENDC}")
                sys.exit(1)

        do_package(project_name, script_dir, repos_parent)
        sys.exit(0)
    else:
        print(f"{Colors.FAIL}Invalid choice{Colors.ENDC}")
        sys.exit(1)

# Helper function to select project when not provided
def select_project_for_subcommand(repos_parent, require_thunderstore_metadata=False):
    """Auto-detect repo and select project (auto-select if only one, menu if multiple)"""
    current_repo = detect_current_repo(repos_parent)

    if not current_repo:
        print(f"{Colors.FAIL}Error: Please run this command from within a repo directory{Colors.ENDC}")
        print(f"(e.g., C:\\Users\\Alex\\repos\\BroforceMods\\)")
        sys.exit(1)

    projects = find_all_projects(repos_parent, require_thunderstore_metadata=require_thunderstore_metadata, filter_repo=current_repo)

    if not projects:
        if require_thunderstore_metadata:
            print(f"{Colors.FAIL}Error: No projects with Thunderstore metadata found in {current_repo}{Colors.ENDC}")
            print(f"Run: broforce-tools init-thunderstore")
        else:
            print(f"{Colors.FAIL}Error: No projects found in {current_repo}{Colors.ENDC}")
        sys.exit(1)

    # Auto-select if only one project
    if len(projects) == 1:
        project_name = projects[0][0]
        print(f"{Colors.CYAN}Using project: {project_name}{Colors.ENDC}")
        return project_name

    # Show menu if multiple projects
    if questionary:
        choices = [name for name, repo in projects]
        project_name = questionary.select(
            f"Select project from {current_repo}:",
            choices=choices
        ).ask()
        if not project_name:  # User cancelled
            sys.exit(0)
        return project_name
    else:
        # Fallback if questionary not available
        print(f"\n{Colors.CYAN}Available projects in {current_repo}:{Colors.ENDC}")
        for i, (name, repo) in enumerate(projects, 1):
            print(f"  {i}. {name}")
        selection = input(f"\nEnter project number (1-{len(projects)}): ").strip()
        try:
            idx = int(selection) - 1
            if 0 <= idx < len(projects):
                return projects[idx][0]
            else:
                print(f"{Colors.FAIL}Invalid selection{Colors.ENDC}")
                sys.exit(1)
        except ValueError:
            print(f"{Colors.FAIL}Invalid input{Colors.ENDC}")
            sys.exit(1)

# Route to subcommand modes
if args.command == 'init-thunderstore':
    project_name = args.project_name
    if not project_name:
        project_name = select_project_for_subcommand(repos_parent, require_thunderstore_metadata=False)
    do_init_thunderstore(project_name, script_dir, repos_parent)
    sys.exit(0)
elif args.command == 'package':
    project_name = args.project_name
    if not project_name:
        project_name = select_project_for_subcommand(repos_parent, require_thunderstore_metadata=True)
    do_package(project_name, script_dir, repos_parent, args.version)
    sys.exit(0)
elif args.command == 'create':
    # Continue with create project mode below
    pass
else:
    # No valid command
    parser.print_help()
    sys.exit(1)

# Create project mode

# Determine output repository
if args.output_repo:
    output_repo_name = args.output_repo
    print(f"{Colors.BLUE}Using output repository: {output_repo_name}{Colors.ENDC}")
else:
    # Interactive mode: always ask for repo
    print(f"\n{Colors.HEADER}Select output repository:{Colors.ENDC}")
    print(f"{Colors.CYAN}1.{Colors.ENDC} {template_repo_name} (current repository)")
    print(f"{Colors.CYAN}2.{Colors.ENDC} Enter another repository name")
    repo_choice = input("Enter your choice (1 or 2): ").strip()

    if repo_choice == "1":
        output_repo_name = template_repo_name
    elif repo_choice == "2":
        output_repo_name = input("Enter repository name: ").strip()
        if not output_repo_name:
            print(f"{Colors.FAIL}Error: Repository name cannot be empty.{Colors.ENDC}")
            sys.exit(1)
    else:
        print(f"{Colors.FAIL}Invalid choice. Please run the script again and enter 1 or 2.{Colors.ENDC}")
        sys.exit(1)

    print(f"{Colors.BLUE}Using output repository: {output_repo_name}{Colors.ENDC}")

# Get Broforce path from props files
broforce_path = get_broforce_path(repos_parent)

# Check if Broforce path exists
if not os.path.exists(broforce_path):
    print(f"{Colors.FAIL}Error: Broforce path does not exist: {broforce_path}{Colors.ENDC}")
    sys.exit(1)

# Get project type
if args.type:
    template_type = args.type
else:
    print(f"{Colors.HEADER}What would you like to create?{Colors.ENDC}")
    print(f"{Colors.CYAN}1.{Colors.ENDC} Mod")
    print(f"{Colors.CYAN}2.{Colors.ENDC} Bro")
    choice = input("Enter your choice (1 or 2): ").strip()

    if choice == "1":
        template_type = "mod"
    elif choice == "2":
        template_type = "bro"
    else:
        print(f"{Colors.FAIL}Invalid choice. Please run the script again and enter 1 or 2.{Colors.ENDC}")
        sys.exit(1)

# Set template parameters based on type
if template_type == "mod":
    template_type_title = "Mod"
    source_template_name = "Mod Template"
else:
    template_type_title = "Bro"
    source_template_name = "Bro Template"

# Get the name for the new template
if args.name:
    newName = args.name
else:
    newName = input(f'Enter {template_type} name:\n')

newNameWithUnderscore = newName.replace(' ', '_')
newNameNoSpaces = newName.replace(' ', '')

# Get the author name
if args.author:
    authorName = args.author
else:
    authorName = input('Enter author name (e.g., YourName):\n')

# Define paths
templatePath = os.path.join(template_repo_dir, source_template_name)
output_repo_path = os.path.join(repos_parent, output_repo_name)

# Check if output repository exists
if not os.path.exists(output_repo_path):
    print(f"{Colors.FAIL}Error: Output repository does not exist: {output_repo_path}{Colors.ENDC}")
    print(f"{Colors.WARNING}Please ensure the repository '{output_repo_name}' exists in: {repos_parent}{Colors.ENDC}")
    sys.exit(1)

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
                import filecmp
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
    sys.exit(1)

# Create Releases directory if it doesn't exist
if not os.path.exists(releasesPath):
    try:
        os.makedirs(releasesPath)
        print(f"{Colors.GREEN}Created Releases directory: {releasesPath}{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}Error: Failed to create Releases directory: {e}{Colors.ENDC}")
        sys.exit(1)

# Check if destination directories already exist
if os.path.exists(newReleaseFolder):
    print(f"{Colors.FAIL}Error: Release directory already exists: {newReleaseFolder}{Colors.ENDC}")
    print(f"Please choose a different {template_type} name or remove the existing directory.")
    sys.exit(1)

if os.path.exists(newRepoPath):
    print(f"{Colors.FAIL}Error: Repository directory already exists: {newRepoPath}{Colors.ENDC}")
    print(f"Please choose a different {template_type} name or remove the existing directory.")
    sys.exit(1)

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
    sys.exit(1)

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

        # Get BroMaker version from its Info.json
        bromaker_info_path = os.path.join(broforce_path, "Mods", "BroMaker", "Info.json")
        bromaker_version = "2.6.0"  # Default fallback version

        if os.path.exists(bromaker_info_path):
            try:
                with open(bromaker_info_path, 'r', encoding='utf-8') as f:
                    bromaker_info = json.load(f)
                    bromaker_version = bromaker_info.get('Version', bromaker_version)
                    print(f"{Colors.GREEN}Detected BroMaker version: {bromaker_version}{Colors.ENDC}")
            except Exception as e:
                print(f"{Colors.WARNING}Warning: Could not read BroMaker version from Info.json: {e}{Colors.ENDC}")
                print(f"{Colors.WARNING}Using default BroMaker version: {bromaker_version}{Colors.ENDC}")
        else:
            print(f"{Colors.WARNING}Warning: BroMaker Info.json not found at {bromaker_info_path}{Colors.ENDC}")
            print(f"Using default BroMaker version: {bromaker_version}")

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
    if args.output_repo:
        print(f"{Colors.CYAN}Output repository:{Colors.ENDC} {output_repo_name}")
    print(f"{Colors.CYAN}Source files:{Colors.ENDC} {newRepoPath}")
    print(f"{Colors.CYAN}Releases folder:{Colors.ENDC} {newReleaseFolder}")
    print(f"\n{Colors.CYAN}Next steps:{Colors.ENDC}")
    print(f"  1. Open the project in Visual Studio")
    print(f"  2. Build the project (builds to game automatically)")
    print(f"  3. Launch Broforce to test your {template_type}")

except Exception as e:
    print(f"{Colors.FAIL}Error: Failed during file processing: {e}{Colors.ENDC}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
